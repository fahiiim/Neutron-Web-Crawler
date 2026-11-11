"""Search Gateway Microservice (FastAPI + Gradio SDK).

Serves the interactive web search UI, queries Turso LibSQL FTS5 index,
enforces rate limiting and security headers, and dispatches JIT crawl bursts.
"""

import asyncio
from contextlib import asynccontextmanager
import json
import os
import time
from typing import Any, AsyncGenerator, Coroutine, Dict, List, Set

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import httpx
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sse_starlette.sse import EventSourceResponse
from starlette.middleware.base import BaseHTTPMiddleware
import structlog

try:
    import gradio as gr
except ImportError:
    gr = None

try:
    from .compression import decompress_text
    from .config import settings
    from .db_turso import turso_client
except ImportError:
    from compression import decompress_text
    from config import settings
    from db_turso import turso_client

logger = structlog.get_logger("neutron.gateway")
_START_TIME = time.time()

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_TEMPLATES_DIR = os.path.join(_BASE_DIR, "templates")
_STATIC_DIR = os.path.join(_BASE_DIR, "static")
_UI_ASSETS_DIR = os.path.join(_STATIC_DIR, "ui-assets")
_REACT_INDEX = os.path.join(_STATIC_DIR, "index.html")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)


def _ephemeral_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else get_remote_address(request)


limiter = Limiter(key_func=_ephemeral_key)


def _fire_and_log(coro: Coroutine[Any, Any, Any], task_name: str) -> asyncio.Task:
    task = asyncio.create_task(coro)

    def _done(t: asyncio.Task) -> None:
        try:
            exc = t.exception()
            if exc is not None:
                logger.warning("gateway_task_failed", task=task_name, error=str(exc))
        except asyncio.CancelledError:
            pass

    task.add_done_callback(_done)
    return task


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown lifecycle."""
    try:
        await turso_client.connect()
        logger.info("gateway_turso_connected")
    except Exception as exc:
        logger.warning("gateway_turso_startup_warning", error=str(exc))
    yield
    await turso_client.close()
    logger.info("gateway_shutdown_complete")


app = FastAPI(
    title="Neutron Search Gateway",
    description="Federated search query coordinator and SSE streaming gateway.",
    version="3.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"error": "rate_limit_exceeded", "detail": f"Too many requests: {exc.detail}"},
    )


class _PrivacySecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "interest-cohort=()")
        return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)
app.add_middleware(_PrivacySecurityHeadersMiddleware)
if os.path.isdir(_UI_ASSETS_DIR):
    app.mount("/ui-assets", StaticFiles(directory=_UI_ASSETS_DIR), name="ui-assets")


@app.get("/", response_class=HTMLResponse)
async def serve_home(request: Request) -> Any:
    """Serve the compiled React search application with no-cache headers."""
    no_cache_headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    if os.path.isfile(_REACT_INDEX):
        return FileResponse(
            _REACT_INDEX, media_type="text/html", headers=no_cache_headers
        )
    return templates.TemplateResponse(request, "index.html", headers=no_cache_headers)


@app.get("/health")
async def health_check() -> Dict[str, Any]:
    """Health check endpoint."""
    return {"status": "ok", "service": "neutron-gateway", "version": "3.0.0"}


@app.get("/trending")
async def trending_endpoint() -> Dict[str, Any]:
    return {"trending": await turso_client.get_trending_topics(limit=8)}


@app.get("/suggest")
async def suggest_endpoint(q: str = Query(..., min_length=2, max_length=64)) -> Dict[str, Any]:
    return {"query": q, "suggestions": await turso_client.get_autocomplete_suggestions(q, limit=6)}


@app.get("/stats")
async def stats_endpoint() -> Dict[str, Any]:
    db_stats = await turso_client.get_stats()
    return {
        **db_stats,
        "background_crawler_active": True,
        "uptime_seconds": int(time.time() - _START_TIME),
    }


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_endpoint() -> str:
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        "<title>Neutron Privacy</title></head><body style='background:#000000;color:#ffffff;"
        "font-family:Georgia,serif;max-width:680px;margin:40px auto;padding:20px'>"
        "<h1>Neutron Privacy Promise</h1>"
        "<p>Zero Tracking &bull; Zero Cookies &bull; Zero Telemetry.</p>"
        "<p><a href='/' style='color:#4ade80'>&larr; Back to Neutron</a></p></body></html>"
    )


@app.get("/search")
@limiter.limit(settings.RATE_LIMIT_SEARCH)
async def search_endpoint(
    request: Request,
    q: str = Query(..., min_length=1, max_length=256, description="Search query string"),
    limit: int = Query(15, ge=1, le=50),
) -> Dict[str, Any]:
    """Execute unified search: Turso FTS5 BM25 index + JIT crawl cascade."""
    clean_query = q.strip()
    if not clean_query:
        return {"query": q, "total": 0, "results": []}

    _fire_and_log(turso_client.record_hot_topic(clean_query), "record_hot_topic")
    cached_hits = await turso_client.search(clean_query, limit=limit)

    if len(cached_hits) >= settings.JIT_CACHE_THRESHOLD:
        return {
            "query": clean_query,
            "source": "index_cache",
            "total": len(cached_hits),
            "results": cached_hits,
        }

    jit_hits: List[Dict[str, Any]] = []
    if settings.INTERNAL_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                response = await client.post(
                    f"{settings.CRAWLER_SERVICE_URL.rstrip('/')}/crawl/jit",
                    json={"query": clean_query, "max_pages": 8},
                    headers={"Authorization": f"Bearer {settings.INTERNAL_API_KEY}"},
                )
                if response.status_code == 200:
                    jit_hits = response.json().get("results", [])
        except Exception as exc:
            logger.warning("gateway_jit_dispatch_failed", error=str(exc))

    seen_urls: Set[str] = set()
    merged: List[Dict[str, Any]] = []
    for hit in cached_hits + jit_hits:
        url = hit.get("url")
        if url and url not in seen_urls:
            seen_urls.add(url)
            merged.append(hit)

    return {
        "query": clean_query,
        "source": "hybrid_jit",
        "total": len(merged),
        "results": merged[:limit],
    }


@app.get("/search/stream")
@limiter.limit(settings.RATE_LIMIT_STREAM)
async def search_stream(
    request: Request,
    q: str = Query(..., min_length=1, max_length=256, description="Search query"),
) -> Any:
    """Stream search results in real time using Server-Sent Events (SSE)."""
    clean_query = q.strip()
    _fire_and_log(turso_client.record_hot_topic(clean_query), "record_hot_topic")

    async def event_generator() -> AsyncGenerator[Dict[str, str], None]:
        t0 = time.perf_counter()
        cached_hits = await turso_client.search(clean_query, limit=10)
        yield {
            "event": "cached_results",
            "data": json.dumps(
                {
                    "count": len(cached_hits),
                    "duration_ms": round((time.perf_counter() - t0) * 1000),
                    "results": cached_hits,
                }
            ),
        }

        if len(cached_hits) < settings.JIT_CACHE_THRESHOLD and settings.INTERNAL_API_KEY:
            if await request.is_disconnected():
                return
            yield {
                "event": "status",
                "data": json.dumps({"message": "Triggering live JIT crawl across discovery seeds..."}),
            }

            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.post(
                        f"{settings.CRAWLER_SERVICE_URL.rstrip('/')}/crawl/jit",
                        json={"query": clean_query, "max_pages": 8},
                        headers={"Authorization": f"Bearer {settings.INTERNAL_API_KEY}"},
                    )
                    if resp.status_code == 200:
                        jit_results = resp.json().get("results", [])
                        for item in jit_results:
                            yield {"event": "live_result", "data": json.dumps(item)}
            except Exception as exc:
                logger.warning("gateway_stream_jit_failed", error=str(exc))
                yield {
                    "event": "error",
                    "data": json.dumps({"message": f"Live crawler unavailable: {exc}"}),
                }

        yield {"event": "done", "data": json.dumps({"completed": True})}

    return EventSourceResponse(event_generator())


@app.get("/doc/{url_hash}")
async def get_document(url_hash: int) -> Dict[str, Any]:
    """Retrieve full extracted markdown article directly from Turso."""
    if url_hash < -(1 << 63) or url_hash >= (1 << 63):
        raise HTTPException(status_code=400, detail="Invalid 64-bit url_hash")

    meta = await turso_client.get_document_metadata(url_hash)
    payload_bytes = await turso_client.get_document_payload(url_hash)
    if payload_bytes:
        full_markdown = decompress_text(payload_bytes)
        if full_markdown:
            return {
                "url_hash": str(url_hash),
                "url": meta.get("url") if meta else None,
                "title": meta.get("title") if meta else None,
                "crawled_at": meta.get("crawled_at") if meta else None,
                "full_markdown": full_markdown,
                "source": "turso_blob",
            }

    if not meta:
        raise HTTPException(status_code=404, detail="Document not found")

    return {
        "url_hash": str(url_hash),
        "url": meta.get("url"),
        "title": meta.get("title"),
        "crawled_at": meta.get("crawled_at"),
        "full_markdown": meta.get("snippet", ""),
        "source": "snippet_fallback",
    }


if gr is not None:
    with gr.Blocks(title="Neutron Search API Explorer") as demo:
        gr.Markdown("# Neutron Search Engine Gateway")
        gr.Markdown("Direct API & Web Search Interface powered by **Turso LibSQL FTS5**.")
        gr.Markdown("Open the root [URL](/) to view the real-time search interface.")

    app = gr.mount_gradio_app(app, demo, path="/gradio")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=settings.PORT)

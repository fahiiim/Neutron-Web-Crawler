"""Neutron Unified Search Gateway & Crawler Worker (FastAPI + Gradio).

Combines the public search engine UI, API coordinator, real-time JIT crawler,
and background politeness crawler into a single high-performance microservice.
"""

import asyncio
from contextlib import asynccontextmanager
import json
import os
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Set

from curl_cffi.requests import AsyncSession
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import gradio as gr
import httpx
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from compression import compress_text, decompress_text
from config import settings
from db_turso import turso_crawler_client
from dedup import (
    compute_simhash,
    extract_domain_host,
    hash_domain,
    hash_url,
)
from discovery import discover_seed_urls
from parser import parse_page_content
from robots import robots_manager

templates = Jinja2Templates(directory="templates")


class JITCrawlRequest(BaseModel):
    """Payload schema for live on-demand crawl triggers."""

    query: str
    max_pages: int = 8


def verify_internal_auth(
    authorization: Optional[str] = Header(None),
) -> None:
    """Ensure requests originate from authenticated internal microservices."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")
    token = authorization.split(" ")[1]
    if token != settings.INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid internal API key")


_bg_worker_task: Optional[asyncio.Task] = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage lifecycle: initialize database connection and background worker."""
    global _bg_worker_task
    try:
        if (
            settings.TURSO_DATABASE_URL
            and "placeholder" not in settings.TURSO_AUTH_TOKEN
        ):
            await turso_crawler_client.connect()
            print("[Neutron] Connected to Turso DB successfully.")

            if settings.BACKGROUND_CRAWLER_ENABLED:
                _bg_worker_task = asyncio.create_task(background_politeness_worker())
                print("[Neutron] Background politeness crawler started.")
        else:
            print("[Neutron] Awaiting TURSO secrets in Space Settings.")
    except Exception as exc:
        print(f"[Neutron Startup Warning]: {exc}")

    yield

    if _bg_worker_task and not _bg_worker_task.done():
        _bg_worker_task.cancel()
    try:
        await turso_crawler_client.close()
    except Exception:
        pass
    print("[Neutron] Shut down cleanly.")


app = FastAPI(
    title="Neutron Search Engine & Crawler",
    description="Unified search gateway, real-time JIT crawler, and background frontier worker.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# 1. SEARCH ENGINE FRONTEND & PUBLIC APIS
# --------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def serve_home(request: Request) -> Any:
    """Serve the interactive web search engine frontend."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health_check() -> Dict[str, Any]:
    """Health check for Hugging Face Spaces."""
    is_worker_alive = _bg_worker_task is not None and not _bg_worker_task.done()
    return {
        "status": "ok",
        "service": "neutron-crawler-gateway",
        "background_crawler_running": is_worker_alive,
    }


@app.get("/search")
async def search_endpoint(
    q: str = Query(..., description="Search query string"),
    limit: int = Query(15, ge=1, le=50),
) -> Dict[str, Any]:
    """Execute unified search: Turso FTS5 BM25 index + in-process JIT crawl cascade."""
    clean_query = q.strip()
    if not clean_query:
        return {"query": q, "total": 0, "results": []}

    asyncio.create_task(turso_crawler_client.record_hot_topic(clean_query))

    # 1. Query Turso FTS5 Index (<15ms)
    cached_hits = await turso_crawler_client.search(clean_query, limit=limit)

    # 2. Return immediately if we have enough indexed matches
    if len(cached_hits) >= 5:
        return {
            "query": clean_query,
            "source": "index_cache",
            "total": len(cached_hits),
            "results": cached_hits,
        }

    # 3. Cache sparse or miss: trigger in-process live JIT crawl directly!
    candidates = await discover_seed_urls(clean_query, max_urls=8)
    jit_hits: List[Dict[str, Any]] = []

    if candidates:
        async with AsyncSession(impersonate="chrome124") as session:
            tasks = [fetch_and_index_document(session, url) for url in candidates]
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)
            for item in outcomes:
                if isinstance(item, dict) and item:
                    jit_hits.append(item)

    # Merge and deduplicate results
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
async def search_stream(q: str = Query(..., description="Search query")) -> Any:
    """Stream search results in real time using Server-Sent Events (SSE)."""
    clean_query = q.strip()

    async def event_generator() -> AsyncGenerator[Dict[str, str], None]:
        # 1. Yield indexed hits first (<15ms)
        cached_hits = await turso_crawler_client.search(clean_query, limit=10)
        yield {
            "event": "cached_results",
            "data": json.dumps({"count": len(cached_hits), "results": cached_hits}),
        }

        # 2. Trigger live JIT crawl if cached hits are sparse
        if len(cached_hits) < 5:
            yield {
                "event": "status",
                "data": json.dumps(
                    {"message": "Triggering live JIT crawl across discovery seeds..."}
                ),
            }

            candidates = await discover_seed_urls(clean_query, max_urls=8)
            if candidates:
                async with AsyncSession(impersonate="chrome124") as session:
                    for url in candidates:
                        try:
                            doc = await fetch_and_index_document(session, url)
                            if doc:
                                yield {"event": "live_result", "data": json.dumps(doc)}
                        except Exception as exc:
                            print(f"[Stream JIT Error]: {exc}")

        # 3. Final completion event
        yield {"event": "done", "data": json.dumps({"completed": True})}

    return EventSourceResponse(event_generator())


@app.get("/doc/{url_hash}")
async def get_document(url_hash: int) -> Dict[str, Any]:
    """Retrieve full extracted markdown article directly from Turso (Sub-5ms, Zero Card)."""
    payload_bytes = await turso_crawler_client.get_document_payload(url_hash)
    if payload_bytes:
        full_markdown = decompress_text(payload_bytes)
        return {
            "url_hash": url_hash,
            "full_markdown": full_markdown,
            "source": "turso_blob",
        }

    hits = await turso_crawler_client.search(str(url_hash), limit=1)
    if not hits:
        raise HTTPException(status_code=404, detail="Document not found")

    meta = hits[0]
    return {
        "url": meta.get("url"),
        "title": meta.get("title"),
        "full_markdown": meta.get("snippet", ""),
        "source": "snippet_fallback",
    }


# --------------------------------------------------------------------------
# 2. CRAWLER CORE ENGINE
# --------------------------------------------------------------------------
async def fetch_and_index_document(
    session: AsyncSession,
    url: str,
) -> Optional[Dict[str, Any]]:
    """Fetch URL with Chrome TLS fingerprint impersonation, parse, and index."""
    try:
        is_allowed = await robots_manager.is_allowed(url)
        if not is_allowed:
            return None

        response = await session.get(url, timeout=3.5)
        if response.status_code != 200:
            return None

        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type:
            return None

        extracted = parse_page_content(response.text, url)

        # Stage 3 Escalation: Headless browser fallback if page is an empty client SPA
        if extracted["is_spa_empty"]:
            try:
                async with httpx.AsyncClient(timeout=5.5) as client:
                    rend_resp = await client.post(
                        f"{settings.RENDERER_SERVICE_URL}/render",
                        json={"url": url},
                        headers={"Authorization": f"Bearer {settings.INTERNAL_API_KEY}"},
                    )
                    if rend_resp.status_code == 200:
                        rendered = rend_resp.json()
                        extracted["title"] = rendered.get("title", extracted["title"])
                        extracted["snippet"] = rendered.get("snippet", extracted["snippet"])
                        extracted["text"] = rendered.get("text", extracted["text"])
            except Exception as exc:
                print(f"[Renderer Escalation Error]: {exc}")

        url_id = hash_url(url)
        domain_id = hash_domain(extract_domain_host(url))
        simhash_val = compute_simhash(extracted["text"])

        # Compress text payload with Zstandard
        compressed = compress_text(extracted["text"])

        # Store index metadata and compressed payload directly in Turso (Zero-Card Solution!)
        await turso_crawler_client.insert_search_index(
            url_hash=url_id,
            domain_hash=domain_id,
            canonical_url=url,
            title=extracted["title"],
            snippet=extracted["snippet"],
            opic_authority=0.25,
            simhash=simhash_val,
            compressed_text=compressed,
        )

        # Enqueue discovered outbound links into frontier queue
        if extracted.get("links"):
            queue_payload = [
                {
                    "url_hash": hash_url(item["url"]),
                    "domain_hash": hash_domain(extract_domain_host(item["url"])),
                    "url": item["url"],
                    "priority": 0.5,
                }
                for item in extracted["links"][:20]
            ]
            asyncio.create_task(
                turso_crawler_client.enqueue_frontier_urls(queue_payload)
            )

        return {
            "url_hash": url_id,
            "url": url,
            "title": extracted["title"],
            "snippet": extracted["snippet"],
            "score": 1.0,
        }
    except Exception as exc:
        print(f"[Fetch Error for {url}]: {exc}")
        return None


@app.post("/crawl/jit", dependencies=[Depends(verify_internal_auth)])
async def crawl_jit_endpoint(request: JITCrawlRequest) -> Dict[str, Any]:
    """Execute live JIT search crawl across resilient discovery seeds."""
    candidates = await discover_seed_urls(request.query, max_urls=request.max_pages)
    if not candidates:
        return {"query": request.query, "results": []}

    results: List[Dict[str, Any]] = []
    async with AsyncSession(impersonate="chrome124") as session:
        tasks = [fetch_and_index_document(session, url) for url in candidates]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)

        for item in outcomes:
            if isinstance(item, dict) and item:
                results.append(item)

    return {"query": request.query, "total": len(results), "results": results}


async def background_politeness_worker() -> None:
    """Continuous background crawler loop."""
    await asyncio.sleep(4.0)
    async with AsyncSession(impersonate="chrome124") as session:
        while True:
            try:
                leased = await turso_crawler_client.lease_next_frontier_url()
                if leased is None:
                    await asyncio.sleep(10.0)
                    continue

                target_url = leased["url"]
                url_id = leased["url_hash"]

                custom_delay = await robots_manager.get_crawl_delay(target_url)
                delay_to_wait = (
                    custom_delay
                    if custom_delay is not None
                    else settings.BACKGROUND_FETCH_INTERVAL_SECONDS
                )

                outcome = await fetch_and_index_document(session, target_url)
                new_status = 2 if outcome is not None else 3
                await turso_crawler_client.update_frontier_status(url_id, new_status)

                await asyncio.sleep(delay_to_wait)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                print(f"[Background Crawler Warning]: {exc}")
                await asyncio.sleep(5.0)


# Gradio monitor interface mounted on /gradio
with gr.Blocks(title="Neutron Engine Explorer") as demo:
    gr.Markdown("# 🚀 Neutron Real-Time Search Engine")
    gr.Markdown("Unified search gateway and crawler worker.")
    gr.Markdown("Open the root [URL](/) to use the web search interface.")

app = gr.mount_gradio_app(app, demo, path="/gradio")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=7860)

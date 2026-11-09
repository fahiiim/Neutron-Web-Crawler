"""Search Gateway Microservice (FastAPI).

Coordinates user search queries, queries the Turso LibSQL FTS5 index,
dispatches JIT crawl bursts to the crawler worker, and serves the web UI.
"""

import asyncio
from contextlib import asynccontextmanager
import json
import os
from typing import Any, AsyncGenerator, Dict, List, Set

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import httpx
from sse_starlette.sse import EventSourceResponse

from compression import decompress_text
from config import settings
from db_turso import turso_client
from storage_r2 import r2_reader

templates = Jinja2Templates(directory="templates")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown lifecycle."""
    try:
        await turso_client.connect()
        print("[Gateway] Connected to Turso DB successfully.")
    except Exception as exc:
        print(f"[Gateway Startup Warning]: {exc}")
    yield
    await turso_client.close()
    print("[Gateway] Turso DB connection closed.")


app = FastAPI(
    title="Neutron Search Gateway",
    description="Federated search query coordinator and SSE streaming gateway.",
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


@app.get("/", response_class=HTMLResponse)
async def serve_home(request: Request) -> Any:
    """Serve the interactive web search engine frontend."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health_check() -> Dict[str, str]:
    """Health check endpoint for Hugging Face Spaces status monitoring."""
    return {"status": "ok", "service": "neutron-gateway"}


@app.get("/search")
async def search_endpoint(
    q: str = Query(..., description="Search query string"),
    limit: int = Query(15, ge=1, le=50),
) -> Dict[str, Any]:
    """Execute unified search.

    Hits Turso FTS5 BM25 index (<15ms). If results < 5, dispatches
    a JIT crawl request to the crawler worker microservice.
    """
    clean_query = q.strip()
    if not clean_query:
        return {"query": q, "total": 0, "results": []}

    # Record hot topic query for crawler focused learning
    asyncio.create_task(turso_client.record_hot_topic(clean_query))

    # 1. Query Turso FTS5 Index
    cached_hits = await turso_client.search(clean_query, limit=limit)

    # 2. Return immediately if we have sufficient indexed matches
    if len(cached_hits) >= 5:
        return {
            "query": clean_query,
            "source": "index_cache",
            "total": len(cached_hits),
            "results": cached_hits,
        }

    # 3. Cache sparse or miss: trigger live JIT crawl to crawler worker
    jit_hits: List[Dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=4.5) as client:
            response = await client.post(
                f"{settings.CRAWLER_SERVICE_URL}/crawl/jit",
                json={"query": clean_query, "max_pages": 8},
                headers={"Authorization": f"Bearer {settings.INTERNAL_API_KEY}"},
            )
            if response.status_code == 200:
                jit_hits = response.json().get("results", [])
    except Exception as exc:
        print(f"[Gateway JIT Request Warning]: {exc}")

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
        cached_hits = await turso_client.search(clean_query, limit=10)
        yield {
            "event": "cached_results",
            "data": json.dumps({"count": len(cached_hits), "results": cached_hits}),
        }

        # 2. Trigger live JIT crawl if cached hits are sparse
        if len(cached_hits) < 5:
            yield {
                "event": "status",
                "data": json.dumps({"message": "Triggering live JIT crawl across discovery seeds..."}),
            }

            try:
                async with httpx.AsyncClient(timeout=6.0) as client:
                    resp = await client.post(
                        f"{settings.CRAWLER_SERVICE_URL}/crawl/jit",
                        json={"query": clean_query, "max_pages": 8},
                        headers={"Authorization": f"Bearer {settings.INTERNAL_API_KEY}"},
                    )
                    if resp.status_code == 200:
                        jit_results = resp.json().get("results", [])
                        for item in jit_results:
                            yield {
                                "event": "live_result",
                                "data": json.dumps(item),
                            }
            except Exception as exc:
                yield {
                    "event": "error",
                    "data": json.dumps({"message": f"Live crawler unavailable: {exc}"}),
                }

        # 3. Final completion event
        yield {"event": "done", "data": json.dumps({"completed": True})}

    return EventSourceResponse(event_generator())


@app.get("/doc/{url_hash}")
async def get_document(url_hash: int) -> Dict[str, Any]:
    """Retrieve full extracted markdown article from Cloudflare R2 at $0 egress."""
    # Look up pointer from Turso
    hits = await turso_client.search(str(url_hash), limit=1)
    if not hits:
        raise HTTPException(status_code=404, detail="Document not found in index")

    meta = hits[0]
    batch_id = meta.get("r2_batch_id")
    offset = meta.get("r2_byte_offset", 0)
    length = meta.get("r2_byte_length", 0)

    if not batch_id or length <= 0:
        return {"title": meta.get("title"), "full_markdown": meta.get("snippet", "")}

    compressed_bytes = await r2_reader.get_byte_range(batch_id, offset, length)
    full_markdown = decompress_text(compressed_bytes)

    return {
        "url": meta.get("url"),
        "title": meta.get("title"),
        "full_markdown": full_markdown,
    }


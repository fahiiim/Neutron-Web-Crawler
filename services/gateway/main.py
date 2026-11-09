import asyncio
import json
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Query, HTTPException, Header
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
import httpx

from shared.config import settings
from shared.db_turso import turso_db
from shared.storage_r2 import r2_storage
from shared.compression import decompress_text

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize Turso connection
    try:
        await turso_db.connect()
        print("[Gateway] Connected to Turso DB successfully.")
    except Exception as e:
        print(f"[Gateway] Turso DB connection warning: {e}")
    yield
    await turso_db.close()
    print("[Gateway] Turso DB connections closed.")

app = FastAPI(
    title="Neutron Search Gateway Microservice",
    description="Federated search query coordinator, cache router, and SSE streamer.",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    """Kubernetes liveness & readiness probe."""
    return {"status": "ok", "service": "svc-search-gateway"}

@app.get("/search")
async def search(
    q: str = Query(..., description="Search query string"),
    limit: int = Query(15, ge=1, le=50)
):
    """
    Parallel fast search:
    1. Query Turso FTS5 BM25 index (<15ms).
    2. If hits < 5, trigger JIT crawl to svc-crawler-worker.
    """
    clean_q = q.strip()
    if not clean_q:
        return {"query": q, "total": 0, "results": []}

    # Record hot topic query for crawler focused learning
    asyncio.create_task(turso_db.record_hot_topic(clean_q))

    # Step 1: Query Turso FTS5 Index
    cached_hits = await turso_db.search(clean_q, limit=limit)

    # Step 2: If we have enough high-confidence results, return immediately
    if len(cached_hits) >= 5:
        return {
            "query": clean_q,
            "source": "index_cache",
            "total": len(cached_hits),
            "results": cached_hits
        }

    # Step 3: Sparse cache or miss: Request JIT crawl from svc-crawler-worker
    jit_hits = []
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(
                f"{settings.CRAWLER_SERVICE_URL}/crawl/jit",
                json={"query": clean_q, "max_pages": 8},
                headers={"Authorization": f"Bearer {settings.INTERNAL_API_KEY}"}
            )
            if resp.status_code == 200:
                jit_hits = resp.json().get("results", [])
    except Exception as e:
        print(f"[Gateway] JIT crawl request failed: {e}")

    # Merge and deduplicate results by URL
    seen_urls = set()
    merged = []
    for hit in (cached_hits + jit_hits):
        u = hit.get("url")
        if u and u not in seen_urls:
            seen_urls.add(u)
            merged.append(hit)

    return {
        "query": clean_q,
        "source": "hybrid_jit",
        "total": len(merged),
        "results": merged[:limit]
    }

@app.get("/search/stream")
async def search_stream(q: str = Query(..., description="Search query")):
    """Server-Sent Events (SSE) streaming waterfall for real-time live answers."""
    clean_q = q.strip()

    async def event_generator():
        # 1. First event: Send cached hits (<15ms)
        cached_hits = await turso_db.search(clean_q, limit=10)
        yield {
            "event": "cached_results",
            "data": json.dumps({"count": len(cached_hits), "results": cached_hits})
        }

        # 2. If cached hits are sparse, stream live JIT crawler results
        if len(cached_hits) < 5:
            yield {
                "event": "status",
                "data": json.dumps({"message": "Triggering live JIT crawl across discovery seeds..."})
            }

            try:
                async with httpx.AsyncClient(timeout=6.0) as client:
                    resp = await client.post(
                        f"{settings.CRAWLER_SERVICE_URL}/crawl/jit",
                        json={"query": clean_q, "max_pages": 8},
                        headers={"Authorization": f"Bearer {settings.INTERNAL_API_KEY}"}
                    )
                    if resp.status_code == 200:
                        jit_results = resp.json().get("results", [])
                        for item in jit_results:
                            yield {
                                "event": "live_result",
                                "data": json.dumps(item)
                            }
            except Exception as e:
                yield {
                    "event": "error",
                    "data": json.dumps({"message": f"Live crawler unavailable: {str(e)}"})
                }

        # 3. Final event
        yield {"event": "done", "data": json.dumps({"completed": True})}

    return EventSourceResponse(event_generator())

@app.get("/doc/{url_hash}")
async def get_document(url_hash: int):
    """
    Retrieve full extracted markdown content of a page:
    Reads exact byte range from Cloudflare R2 ($0 egress) and decompresses Zstandard.
    """
    # 1. Lookup batch pointer from Turso
    hits = await turso_db.search(f"{url_hash}", limit=1)
    if not hits:
        raise HTTPException(status_code=404, detail="Document not found in index")

    doc_meta = hits[0]
    batch_id = doc_meta.get("r2_batch_id")
    offset = doc_meta.get("r2_byte_offset")
    length = doc_meta.get("r2_byte_length")

    if not batch_id or length <= 0:
        return {"meta": doc_meta, "full_text": doc_meta.get("snippet", "")}

    # 2. Read byte range from R2
    compressed_bytes = await r2_storage.get_byte_range(batch_id, offset, length)
    full_markdown = decompress_text(compressed_bytes)

    return {
        "url": doc_meta.get("url"),
        "title": doc_meta.get("title"),
        "full_markdown": full_markdown
    }


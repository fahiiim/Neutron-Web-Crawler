"""Crawler Worker Microservice (FastAPI).

Executes live Just-In-Time (JIT) crawl bursts for the search gateway,
and runs a polite background crawler frontier maintaining ~27,400 pages/day.
"""

import asyncio
from contextlib import asynccontextmanager
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from curl_cffi.requests import AsyncSession
from fastapi import Depends, FastAPI, Header, HTTPException
import httpx
from pydantic import BaseModel

from compression import compress_text
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
from storage_r2 import r2_uploader


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
        await turso_crawler_client.connect()
        print("[Crawler Worker] Connected to Turso DB.")
    except Exception as exc:
        print(f"[Crawler Worker Startup Warning]: {exc}")

    if settings.BACKGROUND_CRAWLER_ENABLED:
        _bg_worker_task = asyncio.create_task(background_politeness_worker())
        print("[Crawler Worker] Background politeness crawler started.")

    yield

    if _bg_worker_task and not _bg_worker_task.done():
        _bg_worker_task.cancel()
    await turso_crawler_client.close()
    print("[Crawler Worker] Shut down cleanly.")


app = FastAPI(
    title="Neutron Crawler Worker",
    description="Dual-lane async crawler: JIT user bursts + background politeness loop.",
    version="2.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check() -> Dict[str, Any]:
    """Health check for Hugging Face Spaces."""
    is_worker_alive = _bg_worker_task is not None and not _bg_worker_task.done()
    return {
        "status": "ok",
        "service": "neutron-crawler",
        "background_crawler_running": is_worker_alive,
    }


async def fetch_and_index_document(
    session: AsyncSession,
    url: str,
) -> Optional[Dict[str, Any]]:
    """Fetch URL with Chrome TLS fingerprint impersonation, parse, and index.

    Args:
        session: curl_cffi AsyncSession instance.
        url: Target canonical URL string.

    Returns:
        Document summary record if successfully indexed, None otherwise.
    """
    try:
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
        chunk_key = f"chunk_{time.strftime('%Y%m%d')}.zst"
        offset = 0
        length = len(compressed)

        # Upload payload to Cloudflare R2
        await r2_uploader.put_chunk(chunk_key, compressed)

        # Write index metadata into Turso FTS5
        await turso_crawler_client.insert_search_index(
            url_hash=url_id,
            domain_hash=domain_id,
            canonical_url=url,
            title=extracted["title"],
            snippet=extracted["snippet"],
            r2_batch_id=chunk_key,
            r2_byte_offset=offset,
            r2_byte_length=length,
            opic_authority=0.25,
            simhash=simhash_val,
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
        print(f"[Fetch & Index Error]: {exc}")
        return None


@app.post("/crawl/jit", dependencies=[Depends(verify_internal_auth)])
async def crawl_jit_endpoint(request: JITCrawlRequest) -> Dict[str, Any]:
    """Execute live JIT search crawl across resilient discovery seeds.

    Fetches candidate pages concurrently in under 600ms using curl_cffi.
    """
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
    """Continuous background crawler loop.

    Fetches URLs from the Turso frontier queue at ~0.32 pages/second
    (~27,400 pages/day), enforcing domain rate limits.
    """
    await asyncio.sleep(4.0)  # Grace startup delay
    async with AsyncSession(impersonate="chrome124") as session:
        while True:
            try:
                leased = await turso_crawler_client.lease_next_frontier_url()
                if leased is None:
                    await asyncio.sleep(10.0)
                    continue

                target_url = leased["url"]
                url_id = leased["url_hash"]

                outcome = await fetch_and_index_document(session, target_url)
                new_status = 2 if outcome is not None else 3
                await turso_crawler_client.update_frontier_status(url_id, new_status)

                # Sustain politeness rate: ~3.1 seconds delay per request
                await asyncio.sleep(settings.BACKGROUND_FETCH_INTERVAL_SECONDS)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                print(f"[Background Crawler Warning]: {exc}")
                await asyncio.sleep(5.0)

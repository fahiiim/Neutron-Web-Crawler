"""Neutron Unified Search Gateway & Crawler Worker (FastAPI + Gradio).

Combines the public search engine UI, API coordinator, real-time JIT crawler,
and background Mercator politeness crawler into a hardened microservice.
"""

import asyncio
from contextlib import asynccontextmanager
import hmac
import json
import time
from typing import Any, AsyncGenerator, Coroutine, Dict, List, Optional, Set
import urllib.parse

try:
    import spaces

    @spaces.GPU
    def _zero_gpu_guard() -> str:
        """Hugging Face ZeroGPU requirement guard."""
        return "Neutron Search Engine Online"
except Exception:
    def _zero_gpu_guard() -> str:
        return "Neutron Search Engine Online"


def _notify_zerogpu_startup() -> None:
    """Trigger ZeroGPU startup report when running inside a ZeroGPU container."""
    try:
        import spaces.zero

        if hasattr(spaces.zero, "startup"):
            spaces.zero.startup()
        else:
            import spaces.zero.client as zero_client

            zero_client.startup_report()
    except Exception:
        pass


_notify_zerogpu_startup()

from curl_cffi.requests import AsyncSession
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import httpx
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

try:
    import gradio as gr
except ImportError:
    gr = None  # Allows running pure FastAPI / unit tests without Gradio

try:
    from .bloom import URLBloomFilter
    from .compression import compress_text, decompress_text
    from .config import settings
    from .db_turso import turso_crawler_client
    from .dedup import (
        canonicalize_url,
        compute_simhash,
        extract_domain_host,
        hash_domain,
        hash_url,
    )
    from .discovery import discover_seed_urls, discover_seed_urls_detailed
    from .logging_utils import get_logger
    from .middleware import configure_middleware, limiter
    from .parser import parse_page_content
    from .robots import robots_manager
    from .sitemap import discover_sitemap_urls
except ImportError:
    from bloom import URLBloomFilter
    from compression import compress_text, decompress_text
    from config import settings
    from db_turso import turso_crawler_client
    from dedup import (
        canonicalize_url,
        compute_simhash,
        extract_domain_host,
        hash_domain,
        hash_url,
    )
    from discovery import discover_seed_urls, discover_seed_urls_detailed
    from logging_utils import get_logger
    from middleware import configure_middleware, limiter
    from parser import parse_page_content
    from robots import robots_manager
    from sitemap import discover_sitemap_urls

import os

logger = get_logger("neutron.crawler")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_TEMPLATES_DIR = os.path.join(_BASE_DIR, "templates")
_STATIC_DIR = os.path.join(_BASE_DIR, "static")
_UI_ASSETS_DIR = os.path.join(_STATIC_DIR, "ui-assets")
_REACT_INDEX = os.path.join(_STATIC_DIR, "index.html")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)

_START_TIME = time.time()
_RETRY_BACKOFF = (0.5, 1.5, 3.0)
_AUTHORITATIVE_DOMAINS = (
    ".edu",
    ".gov",
    "wikipedia.org",
    "arxiv.org",
    "github.com",
    "mozilla.org",
    "python.org",
    "rust-lang.org",
    "w3.org",
)

url_bloom = URLBloomFilter(
    capacity=settings.BLOOM_CAPACITY,
    fp_rate=settings.BLOOM_FP_RATE,
)
_jit_semaphore = asyncio.Semaphore(max(1, settings.MAX_CONCURRENT_JIT_FETCHES))
_seen_sitemap_domains: Set[str] = set()
_bg_worker_task: Optional[asyncio.Task] = None


class JITCrawlRequest(BaseModel):
    """Validated payload schema for internal on-demand crawl triggers."""

    query: str = Field(..., min_length=1, max_length=256)
    max_pages: int = Field(8, ge=1, le=20)


def _fire_and_log(coro: Coroutine[Any, Any, Any], task_name: str) -> asyncio.Task:
    """Schedule a background task and log any unhandled exception."""
    task = asyncio.create_task(coro)

    def _on_done(done_task: asyncio.Task) -> None:
        try:
            exc = done_task.exception()
            if exc is not None:
                logger.warning("background_task_failed", task=task_name, error=str(exc))
        except asyncio.CancelledError:
            pass

    task.add_done_callback(_on_done)
    return task


def verify_internal_auth(
    authorization: Optional[str] = Header(None),
) -> None:
    """Verify bearer token from internal callers using constant-time comparison."""
    expected_key = settings.INTERNAL_API_KEY
    if not expected_key:
        raise HTTPException(
            status_code=503,
            detail="Internal authentication is not configured on this server.",
        )

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")

    token = authorization.split(" ", 1)[1].strip()
    if not hmac.compare_digest(token.encode("utf-8"), expected_key.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Invalid internal API key")


def compute_opic_authority(url: str, extracted: Dict[str, Any]) -> float:
    """Compute a bounded [0.1, 0.95] authority score from domain & content signals."""
    score = 0.25
    parsed = urllib.parse.urlsplit(url)
    host = parsed.netloc.lower()

    if parsed.scheme == "https":
        score += 0.05
    if any(host.endswith(suffix) or suffix in host for suffix in _AUTHORITATIVE_DOMAINS):
        score += 0.25

    depth = len([seg for seg in parsed.path.split("/") if seg])
    if depth <= 2:
        score += 0.05

    text_len = len(extracted.get("text", ""))
    if text_len >= 1500:
        score += 0.15
    elif text_len >= 400:
        score += 0.08

    if extracted.get("author") or extracted.get("published_at"):
        score += 0.10

    return round(min(0.95, max(0.1, score)), 3)


async def fetch_with_retry(
    session: AsyncSession,
    url: str,
    max_retries: int = settings.MAX_RETRY_ATTEMPTS,
) -> Optional[Any]:
    """Fetch a URL with Chrome TLS impersonation and exponential backoff retries."""
    attempts = max(1, max_retries)
    for attempt in range(attempts):
        timeout = settings.FETCH_TIMEOUT_SECONDS + (attempt * 1.5)
        try:
            response = await session.get(url, timeout=timeout)
            if response.status_code == 200:
                return response
            if response.status_code in (429, 502, 503, 504) and attempt < attempts - 1:
                delay = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
                logger.info(
                    "fetch_retry_backoff",
                    url=url,
                    status=response.status_code,
                    attempt=attempt + 1,
                    delay=delay,
                )
                await asyncio.sleep(delay)
                continue
            return response
        except Exception as exc:
            if attempt < attempts - 1:
                delay = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
                logger.debug(
                    "fetch_exception_retrying",
                    url=url,
                    attempt=attempt + 1,
                    error=str(exc),
                )
                await asyncio.sleep(delay)
            else:
                logger.warning("fetch_exhausted_retries", url=url, error=str(exc))
    return None


async def _warm_bloom_filter() -> None:
    """Pre-load indexed URLs from Turso into the in-memory Bloom filter."""
    try:
        urls = await turso_crawler_client.get_indexed_urls(limit=50000)
        count = url_bloom.add_many(urls)
        logger.info("bloom_filter_warmed", entries=count)
    except Exception as exc:
        logger.warning("bloom_warmup_failed", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage lifecycle: DB initialization, Bloom warm-up, and background worker."""
    global _bg_worker_task
    _notify_zerogpu_startup()

    if settings.REQUIRE_INTERNAL_API_KEY and not settings.INTERNAL_API_KEY:
        raise RuntimeError(
            "REQUIRE_INTERNAL_API_KEY is true, but INTERNAL_API_KEY is not set."
        )
    if not settings.INTERNAL_API_KEY:
        logger.warning(
            "internal_api_key_not_configured",
            detail="Internal routes (/crawl/jit) are disabled until INTERNAL_API_KEY is set.",
        )

    try:
        if turso_crawler_client.is_configured():
            await turso_crawler_client.connect()
            logger.info("turso_connected")
            await _warm_bloom_filter()
            await turso_crawler_client.recover_expired_leases()

            if settings.BACKGROUND_CRAWLER_ENABLED:
                _bg_worker_task = asyncio.create_task(background_politeness_worker())
                logger.info("background_politeness_crawler_started")
        else:
            logger.info("turso_credentials_awaiting_configuration")
    except Exception as exc:
        logger.error("lifespan_startup_error", error=str(exc), exc_info=True)

    yield

    if _bg_worker_task and not _bg_worker_task.done():
        _bg_worker_task.cancel()
        try:
            await _bg_worker_task
        except asyncio.CancelledError:
            pass
    try:
        await turso_crawler_client.close()
    except Exception as exc:
        logger.warning("turso_close_error", error=str(exc))
    logger.info("neutron_shutdown_complete")


app = FastAPI(
    title="Neutron Search Engine & Crawler",
    description="Unified search gateway, real-time JIT crawler, and background frontier worker.",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
configure_middleware(app)
if os.path.isdir(_UI_ASSETS_DIR):
    app.mount("/ui-assets", StaticFiles(directory=_UI_ASSETS_DIR), name="ui-assets")


# --------------------------------------------------------------------------
# 1. SEARCH ENGINE FRONTEND & PUBLIC APIS
# --------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def serve_home(request: Request) -> Any:
    """Serve the compiled React search application (or fallback template)."""
    if os.path.isfile(_REACT_INDEX):
        return FileResponse(_REACT_INDEX, media_type="text/html")
    return templates.TemplateResponse(request, "index.html")


@app.get("/health")
async def health_check() -> Dict[str, Any]:
    """Health check endpoint for Hugging Face Spaces & Docker healthchecks."""
    is_worker_alive = _bg_worker_task is not None and not _bg_worker_task.done()
    return {
        "status": "ok",
        "service": "neutron-crawler-gateway",
        "version": "3.0.0",
        "turso_configured": turso_crawler_client.is_configured(),
        "background_crawler_running": is_worker_alive,
        "bloom_entries": len(url_bloom),
    }


@app.get("/trending")
async def trending_endpoint() -> Dict[str, Any]:
    """Return top trending search topics from hot_topics."""
    topics = await turso_crawler_client.get_trending_topics(limit=8)
    return {"trending": topics}


@app.get("/suggest")
async def suggest_endpoint(
    q: str = Query(..., min_length=2, max_length=64),
) -> Dict[str, Any]:
    """Return fast autocomplete suggestions from hot topics and indexed titles."""
    suggestions = await turso_crawler_client.get_autocomplete_suggestions(q, limit=6)
    return {"query": q, "suggestions": suggestions}


@app.get("/stats")
async def stats_endpoint() -> Dict[str, Any]:
    """Return live index statistics for the crawl dashboard."""
    db_stats = await turso_crawler_client.get_stats()
    is_worker_alive = _bg_worker_task is not None and not _bg_worker_task.done()
    return {
        **db_stats,
        "background_crawler_active": is_worker_alive,
        "bloom_entries": len(url_bloom),
        "uptime_seconds": int(time.time() - _START_TIME),
    }


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_endpoint() -> str:
    """Serve human-readable privacy summary."""
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        "<title>Neutron Privacy</title>"
        "<link href='https://fonts.googleapis.com/css2?family=Graduate&family=Lora:wght@400;600&display=swap' rel='stylesheet'>"
        "<style>body{background:#000000;color:#ffffff;font-family:'Lora',Georgia,serif;"
        "max-width:680px;margin:56px auto;padding:0 20px;line-height:1.75;}"
        "h1,h2{font-family:'Graduate',Georgia,serif;color:#ffffff;letter-spacing:0.04em;}"
        "a,.glow{color:#4ade80;text-shadow:0 0 12px rgba(74,222,128,0.55);}</style></head><body>"
        "<h1>Neutron Privacy Promise</h1>"
        "<p><strong>Zero Tracking &bull; Zero Cookies &bull; Zero Telemetry</strong></p>"
        "<h2>What We Never Collect</h2>"
        "<ul><li>No client IP addresses persisted to disk or databases.</li>"
        "<li>No cookies, advertising IDs, or third-party analytics trackers.</li>"
        "<li>No outbound click-tracking redirects.</li></ul>"
        "<h2>Local Browser Storage</h2>"
        "<p>Recent search chips and theme preferences stay strictly inside your browser's "
        "<code>localStorage</code> and never leave your device.</p>"
        "<p><a href='/'>&larr; Back to Neutron Search</a></p></body></html>"
    )


@app.get("/search")
@limiter.limit(settings.RATE_LIMIT_SEARCH)
async def search_endpoint(
    request: Request,
    q: str = Query(..., min_length=1, max_length=256, description="Search query string"),
    limit: int = Query(15, ge=1, le=50),
) -> Dict[str, Any]:
    """Execute unified search: Turso FTS5 BM25 index + rate-limited JIT crawl cascade."""
    clean_query = q.strip()
    if not clean_query:
        return {"query": q, "total": 0, "results": []}

    _fire_and_log(turso_crawler_client.record_hot_topic(clean_query), "record_hot_topic")

    cached_hits = await turso_crawler_client.search(clean_query, limit=limit)
    if len(cached_hits) >= settings.JIT_CACHE_THRESHOLD:
        return {
            "query": clean_query,
            "source": "index_cache",
            "total": len(cached_hits),
            "results": cached_hits,
        }

    candidates = await discover_seed_urls(clean_query, max_urls=8)
    jit_hits: List[Dict[str, Any]] = []

    if candidates:
        existing_urls = {h.get("url") for h in cached_hits}
        fetch_targets = [u for u in candidates if u not in existing_urls]
        if fetch_targets:
            async with AsyncSession(impersonate="chrome124") as session:
                tasks = [
                    fetch_and_index_document(session, url, check_robots=True)
                    for url in fetch_targets
                ]
                outcomes = await asyncio.gather(*tasks, return_exceptions=True)
                for item in outcomes:
                    if isinstance(item, dict) and item:
                        jit_hits.append(item)

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
    """Stream search results and live crawl telemetry via Server-Sent Events (SSE)."""
    clean_query = q.strip()
    _fire_and_log(turso_crawler_client.record_hot_topic(clean_query), "record_hot_topic")

    async def event_generator() -> AsyncGenerator[Dict[str, str], None]:
        t_start = time.perf_counter()
        cached_hits = await turso_crawler_client.search(clean_query, limit=10)
        index_ms = round((time.perf_counter() - t_start) * 1000)

        yield {
            "event": "cached_results",
            "data": json.dumps(
                {
                    "count": len(cached_hits),
                    "duration_ms": index_ms,
                    "results": cached_hits,
                }
            ),
        }

        if len(cached_hits) < settings.JIT_CACHE_THRESHOLD and not await request.is_disconnected():
            sources = ["duckduckgo", "wikipedia", "hackernews", "arxiv", "github", "reddit"]
            if settings.BRAVE_SEARCH_API_KEY:
                sources.insert(0, "brave")

            yield {
                "event": "discovery_start",
                "data": json.dumps({"sources": sources}),
            }
            yield {
                "event": "status",
                "data": json.dumps(
                    {"message": "Discovering live web sources across 6 search adapters..."}
                ),
            }

            discovery_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

            async def _on_source(metric: Dict[str, Any]) -> None:
                await discovery_queue.put(metric)

            discovery_task = asyncio.create_task(
                discover_seed_urls_detailed(
                    clean_query, max_urls=8, on_source_complete=_on_source
                )
            )

            while not discovery_task.done() or not discovery_queue.empty():
                if await request.is_disconnected():
                    discovery_task.cancel()
                    return
                try:
                    metric = await asyncio.wait_for(discovery_queue.get(), timeout=0.1)
                    yield {
                        "event": "discovery_result",
                        "data": json.dumps(metric),
                    }
                except asyncio.TimeoutError:
                    continue

            candidates, _ = await discovery_task
            existing_urls = {h.get("url") for h in cached_hits}
            crawl_targets = [u for u in candidates if u not in existing_urls]

            if crawl_targets:
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {"message": f"Crawling {len(crawl_targets)} live web sources in parallel..."}
                    ),
                }

                crawl_events: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

                async def _crawl_with_events(
                    session: AsyncSession, target_url: str
                ) -> None:
                    domain = extract_domain_host(target_url)
                    await crawl_events.put(
                        {
                            "event": "crawl_start",
                            "data": {"url": target_url, "domain": domain},
                        }
                    )
                    t0 = time.perf_counter()
                    try:
                        allowed = await robots_manager.is_allowed(target_url)
                        if not allowed:
                            await crawl_events.put(
                                {
                                    "event": "crawl_blocked",
                                    "data": {
                                        "url": target_url,
                                        "domain": domain,
                                        "reason": "robots.txt",
                                    },
                                }
                            )
                            return

                        doc = await fetch_and_index_document(
                            session, target_url, check_robots=False
                        )
                        dur_ms = round((time.perf_counter() - t0) * 1000)
                        if doc:
                            await crawl_events.put(
                                {
                                    "event": "crawl_success",
                                    "data": {
                                        "url": target_url,
                                        "domain": domain,
                                        "title": doc.get("title", domain),
                                        "duration_ms": dur_ms,
                                    },
                                }
                            )
                            await crawl_events.put(
                                {"event": "live_result", "data": doc}
                            )
                        else:
                            await crawl_events.put(
                                {
                                    "event": "crawl_error",
                                    "data": {
                                        "url": target_url,
                                        "domain": domain,
                                        "error": "empty or duplicate",
                                    },
                                }
                            )
                    except Exception as exc:
                        await crawl_events.put(
                            {
                                "event": "crawl_error",
                                "data": {
                                    "url": target_url,
                                    "domain": domain,
                                    "error": str(exc)[:80],
                                },
                            }
                        )

                async with AsyncSession(impersonate="chrome124") as session:
                    crawl_tasks = [
                        asyncio.create_task(_crawl_with_events(session, url))
                        for url in crawl_targets
                    ]
                    gather_future = asyncio.gather(*crawl_tasks, return_exceptions=True)

                    while not gather_future.done() or not crawl_events.empty():
                        if await request.is_disconnected():
                            for t in crawl_tasks:
                                t.cancel()
                            return
                        try:
                            ev = await asyncio.wait_for(crawl_events.get(), timeout=0.1)
                            yield {
                                "event": ev["event"],
                                "data": json.dumps(ev["data"]),
                            }
                        except asyncio.TimeoutError:
                            continue

                    await gather_future

        yield {"event": "done", "data": json.dumps({"completed": True})}

    return EventSourceResponse(event_generator())


@app.get("/doc/{url_hash}")
async def get_document(url_hash: int) -> Dict[str, Any]:
    """Retrieve full extracted markdown article directly from Turso."""
    if url_hash < -(1 << 63) or url_hash >= (1 << 63):
        raise HTTPException(status_code=400, detail="Invalid 64-bit url_hash")

    meta = await turso_crawler_client.get_document_metadata(url_hash)
    payload_bytes = await turso_crawler_client.get_document_payload(url_hash)
    if payload_bytes:
        full_markdown = decompress_text(payload_bytes)
        if full_markdown:
            return {
                "url_hash": url_hash,
                "url": meta.get("url") if meta else None,
                "title": meta.get("title") if meta else None,
                "crawled_at": meta.get("crawled_at") if meta else None,
                "full_markdown": full_markdown,
                "source": "turso_blob",
            }

    if not meta:
        raise HTTPException(status_code=404, detail="Document not found")

    return {
        "url_hash": url_hash,
        "url": meta.get("url"),
        "title": meta.get("title"),
        "crawled_at": meta.get("crawled_at"),
        "full_markdown": meta.get("snippet", ""),
        "source": "snippet_fallback",
    }


# --------------------------------------------------------------------------
# 2. CRAWLER CORE ENGINE
# --------------------------------------------------------------------------
async def fetch_and_index_document(
    session: AsyncSession,
    url: str,
    check_robots: bool = True,
    skip_if_seen: bool = False,
) -> Optional[Dict[str, Any]]:
    """Fetch URL with TLS impersonation, retry, dedup, parse, and index."""
    canonical = canonicalize_url(url) or url
    try:
        if skip_if_seen and url_bloom.might_contain(canonical):
            logger.debug("bloom_skip_known_url", url=canonical)
            return None

        if check_robots:
            is_allowed = await robots_manager.is_allowed(canonical)
            if not is_allowed:
                logger.info("robots_disallowed", url=canonical)
                return None

        extracted = None

        async with _jit_semaphore:
            response = await fetch_with_retry(session, canonical)
            if response is not None and response.status_code == 200:
                content_type = response.headers.get("content-type", "")
                if "text/html" in content_type or "application/xhtml" in content_type:
                    parsed = parse_page_content(response.text, canonical)
                    if not parsed.get("is_spa_empty"):
                        extracted = parsed

            # Stage 3 Escalation: Headless Playwright Renderer for dynamic SPAs / WAF challenges
            if (
                not extracted
                and settings.RENDERER_SERVICE_URL
                and settings.INTERNAL_API_KEY
            ):
                try:
                    async with httpx.AsyncClient(timeout=8.0) as client:
                        rend_resp = await client.post(
                            f"{settings.RENDERER_SERVICE_URL.rstrip('/')}/render",
                            json={"url": canonical},
                            headers={
                                "Authorization": f"Bearer {settings.INTERNAL_API_KEY}"
                            },
                        )
                        if rend_resp.status_code == 200:
                            rendered = rend_resp.json()
                            if rendered.get("text"):
                                extracted = {
                                    "title": rendered.get("title", canonical),
                                    "snippet": rendered.get("snippet", ""),
                                    "text": rendered.get("text", ""),
                                    "links": rendered.get("links", []),
                                }
                except Exception as exc:
                    logger.warning(
                        "renderer_escalation_failed",
                        url=canonical,
                        error=str(exc),
                    )

        if not extracted or not extracted.get("text"):
            return None

        url_id = hash_url(canonical)
        domain_host = extract_domain_host(canonical)
        domain_id = hash_domain(domain_host)
        simhash_val = compute_simhash(extracted["text"])

        # SimHash near-duplicate check against existing documents in same domain
        if await turso_crawler_client.is_near_duplicate(
            simhash_val=simhash_val,
            domain_hash=domain_id,
            threshold=settings.SIMHASH_HAMMING_THRESHOLD,
            exclude_url_hash=url_id,
        ):
            logger.info("simhash_near_duplicate_skipped", url=canonical, domain=domain_host)
            url_bloom.add(canonical)
            return None

        opic_score = compute_opic_authority(canonical, extracted)
        compressed = compress_text(extracted["text"])

        saved = await turso_crawler_client.insert_search_index(
            url_hash=url_id,
            domain_hash=domain_id,
            canonical_url=canonical,
            title=extracted["title"],
            snippet=extracted["snippet"],
            opic_authority=opic_score,
            simhash=simhash_val,
            compressed_text=compressed,
        )

        if saved:
            url_bloom.add(canonical)

        # Filter outbound links with Bloom filter and enqueue via single batch call
        outbound_links = extracted.get("links") or []
        if outbound_links:
            queue_payload = []
            for item in outbound_links[:25]:
                out_url = item["url"]
                if url_bloom.might_contain(out_url):
                    continue
                queue_payload.append(
                    {
                        "url_hash": hash_url(out_url),
                        "domain_hash": hash_domain(extract_domain_host(out_url)),
                        "url": out_url,
                        "priority": 0.5,
                    }
                )
            if queue_payload:
                _fire_and_log(
                    turso_crawler_client.enqueue_frontier_urls(queue_payload),
                    "enqueue_frontier_urls",
                )

        return {
            "url_hash": url_id,
            "url": canonical,
            "title": extracted["title"],
            "snippet": extracted["snippet"],
            "score": opic_score,
            "crawled_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        }
    except Exception as exc:
        logger.error("fetch_and_index_error", url=canonical, error=str(exc), exc_info=True)
        return None


@app.post("/crawl/jit", dependencies=[Depends(verify_internal_auth)])
async def crawl_jit_endpoint(request: JITCrawlRequest) -> Dict[str, Any]:
    """Execute live JIT search crawl across resilient discovery seeds."""
    candidates = await discover_seed_urls(request.query, max_urls=request.max_pages)
    if not candidates:
        return {"query": request.query, "total": 0, "results": []}

    results: List[Dict[str, Any]] = []
    async with AsyncSession(impersonate="chrome124") as session:
        tasks = [
            fetch_and_index_document(session, url, check_robots=True)
            for url in candidates
        ]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)

        for item in outcomes:
            if isinstance(item, dict) and item:
                results.append(item)

    return {"query": request.query, "total": len(results), "results": results}


async def _discover_domain_sitemap(target_url: str) -> None:
    """Enqueue sitemap URLs once per newly encountered domain."""
    domain = extract_domain_host(target_url)
    if not domain or domain == "unknown" or domain in _seen_sitemap_domains:
        return
    if len(_seen_sitemap_domains) > 10000:
        _seen_sitemap_domains.clear()
    _seen_sitemap_domains.add(domain)

    try:
        robots_sitemaps = await robots_manager.get_sitemaps(target_url)
        async with httpx.AsyncClient(follow_redirects=True) as client:
            sitemap_urls = await discover_sitemap_urls(
                client, domain, max_urls=30, extra_sitemap_urls=robots_sitemaps
            )
        payload = [
            {
                "url_hash": hash_url(u),
                "domain_hash": hash_domain(extract_domain_host(u)),
                "url": u,
                "priority": 0.65,
            }
            for u in sitemap_urls
            if not url_bloom.might_contain(u)
        ]
        if payload:
            await turso_crawler_client.enqueue_frontier_urls(payload)
            logger.info("sitemap_urls_enqueued", domain=domain, count=len(payload))
    except Exception as exc:
        logger.debug("sitemap_discovery_skipped", domain=domain, error=str(exc))


async def background_politeness_worker() -> None:
    """Continuous Mercator-style background frontier worker with lease recovery & session rotation."""
    await asyncio.sleep(4.0)
    empty_backoff = 10.0
    processed_count = 0

    while True:
        try:
            async with AsyncSession(impersonate="chrome124") as session:
                for _ in range(500):
                    if processed_count % 50 == 0:
                        await turso_crawler_client.recover_expired_leases()

                    leased = await turso_crawler_client.lease_next_frontier_url()
                    if leased is None:
                        await asyncio.sleep(empty_backoff)
                        empty_backoff = min(60.0, empty_backoff * 1.5)
                        continue

                    empty_backoff = 10.0
                    processed_count += 1
                    target_url = leased["url"]
                    url_id = leased["url_hash"]

                    custom_delay = await robots_manager.get_crawl_delay(target_url)
                    delay_to_wait = (
                        custom_delay
                        if custom_delay is not None
                        else settings.BACKGROUND_FETCH_INTERVAL_SECONDS
                    )

                    _fire_and_log(
                        _discover_domain_sitemap(target_url),
                        "discover_domain_sitemap",
                    )

                    outcome = await fetch_and_index_document(
                        session,
                        target_url,
                        check_robots=True,
                        skip_if_seen=True,
                    )
                    new_status = 2 if outcome is not None else 3
                    await turso_crawler_client.update_frontier_status(url_id, new_status)

                    await asyncio.sleep(delay_to_wait)

        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("background_worker_warning", error=str(exc), exc_info=True)
            await asyncio.sleep(5.0)


if gr is not None:
    with gr.Blocks(title="Neutron Engine Explorer") as demo:
        gr.Markdown("# Neutron Real-Time Search Engine")
        gr.Markdown("Unified search gateway and crawler worker.")
        gr.Markdown("Open the root [URL](/) to use the web search interface.")

        with gr.Row():
            status_box = gr.Textbox(value="Initializing...", label="Cluster Status")
            status_btn = gr.Button("Refresh Status")

        status_btn.click(fn=_zero_gpu_guard, inputs=[], outputs=[status_box])
        demo.load(fn=_zero_gpu_guard, inputs=[], outputs=[status_box])

    app = gr.mount_gradio_app(app, demo, path="/gradio")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=settings.PORT)

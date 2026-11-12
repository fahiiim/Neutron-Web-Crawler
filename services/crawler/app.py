"""Neutron On-Demand Crawler & Discovery ConnectRPC/gRPC Microservice."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import time
from typing import Any, AsyncGenerator, AsyncIterator, Dict, List, Optional

from connectrpc.request import RequestContext
from curl_cffi.requests import AsyncSession
from fastapi import FastAPI

from neutron_rpc.neutron.v1 import neutron_connect, neutron_pb
from services.common.config import CrawlerServiceSettings
from services.common.rpc import (
    InternalAuthInterceptor,
    configure_cors,
    doc_to_proto,
    mount_connect_service,
)
from spaces.crawler import app as legacy_crawler
from spaces.crawler.db_turso import turso_crawler_client
from spaces.crawler.dedup import extract_domain_host
from spaces.crawler.discovery import discover_seed_urls_detailed
from spaces.crawler.logging_utils import get_logger
from spaces.crawler.middleware import configure_middleware
from spaces.crawler.robots import robots_manager
from spaces.crawler.synthesis import extract_query_focused_snippet

settings = CrawlerServiceSettings()
logger = get_logger("neutron.service.crawler")
_START_TIME = time.time()
_bg_task: Optional[asyncio.Task] = None


def _to_metric_proto(metric: Dict[str, Any]) -> neutron_pb.DiscoveryMetric:
    return neutron_pb.DiscoveryMetric(
        source=str(metric.get("source") or ""),
        urls_found=int(
            metric.get("urls_found") or metric.get("url_count") or metric.get("count") or 0
        ),
        duration_ms=int(metric.get("duration_ms") or 0),
        status=str(metric.get("status") or "ok"),
        error=str(metric.get("error") or ""),
    )


async def _crawl_one_outcome(
    session: AsyncSession,
    target_url: str,
    query: str,
    *,
    fast_live: bool,
    include_full_text: bool,
    check_robots: bool,
) -> neutron_pb.CrawlOutcome:
    """Execute robots check + live fetch for one URL and normalize into CrawlOutcome."""
    domain = extract_domain_host(target_url)
    t0 = time.perf_counter()

    if not target_url:
        return neutron_pb.CrawlOutcome(ok=False, error="Empty URL", domain=domain)

    try:
        if check_robots:
            allowed = await robots_manager.is_allowed(target_url)
            if not allowed:
                return neutron_pb.CrawlOutcome(
                    ok=False,
                    robots_blocked=True,
                    error="robots.txt",
                    domain=domain,
                    duration_ms=round((time.perf_counter() - t0) * 1000),
                )

        doc = await legacy_crawler.fetch_and_index_document(
            session,
            target_url,
            check_robots=False,
            skip_if_seen=False,
            query=(query or "").strip() or None,
            fast_live=fast_live,
            include_full_text=include_full_text,
        )
        dur_ms = round((time.perf_counter() - t0) * 1000)

        if not doc:
            return neutron_pb.CrawlOutcome(
                ok=False,
                error="blocked, empty, or off-topic",
                domain=domain,
                duration_ms=dur_ms,
            )

        if doc.get("_full_text"):
            doc["snippet"] = (
                extract_query_focused_snippet(query, doc["_full_text"], max_len=320)
                or str(doc.get("snippet") or "")[:320]
            )

        return neutron_pb.CrawlOutcome(
            ok=True,
            domain=domain,
            duration_ms=dur_ms,
            document=doc_to_proto(doc, include_full_text=include_full_text),
        )
    except Exception as exc:
        return neutron_pb.CrawlOutcome(
            ok=False,
            error=str(exc)[:120],
            domain=domain,
            duration_ms=round((time.perf_counter() - t0) * 1000),
        )


class CrawlerServiceImpl:
    """ConnectRPC/gRPC implementation for multi-source discovery and live crawling."""

    async def discover_seeds(
        self,
        request: neutron_pb.DiscoverSeedsRequest,
        ctx: RequestContext,
        /,
    ) -> neutron_pb.DiscoverSeedsResponse:
        clean_query = (request.query or "").strip()
        if not clean_query:
            return neutron_pb.DiscoverSeedsResponse()

        max_urls = max(1, min(int(request.max_urls or 8), 20))
        mode = (request.mode or "all").strip().lower()
        urls, metrics = await discover_seed_urls_detailed(
            clean_query,
            max_urls=max_urls,
            mode=mode,
            skip_domains=legacy_crawler._get_active_waf_domains(),
        )
        return neutron_pb.DiscoverSeedsResponse(
            urls=urls,
            metrics=[_to_metric_proto(m) for m in metrics],
        )

    async def crawl_url(
        self,
        request: neutron_pb.CrawlUrlRequest,
        ctx: RequestContext,
        /,
    ) -> neutron_pb.CrawlUrlResponse:
        target_url = (request.url or "").strip()
        async with AsyncSession(impersonate="chrome124") as session:
            outcome = await _crawl_one_outcome(
                session,
                target_url,
                request.query or "",
                fast_live=bool(request.fast_live),
                include_full_text=bool(request.include_full_text),
                check_robots=bool(request.check_robots),
            )
        return neutron_pb.CrawlUrlResponse(outcome=outcome)

    async def stream_crawl(
        self,
        request: neutron_pb.StreamCrawlRequest,
        ctx: RequestContext,
        /,
    ) -> AsyncIterator[neutron_pb.CrawlStreamEvent]:
        """Discover live candidate URLs and stream crawl outcomes over a single ConnectRPC stream."""
        clean_query = (request.query or "").strip()
        if not clean_query:
            return

        max_pages = max(1, min(int(request.max_pages or 8), 20))
        mode = (request.mode or "all").strip().lower()
        skip_urls = set() if request.force_refresh else set(request.skip_urls or ())
        include_full_text = bool(request.include_full_text)

        candidates, metrics = await discover_seed_urls_detailed(
            clean_query,
            max_urls=max_pages,
            mode=mode,
            skip_domains=legacy_crawler._get_active_waf_domains(),
        )
        for m in metrics:
            yield neutron_pb.CrawlStreamEvent(
                event_type="discovery_result",
                metric=_to_metric_proto(m),
            )

        fetch_targets = [u for u in candidates if u not in skip_urls]
        if not fetch_targets:
            return

        yield neutron_pb.CrawlStreamEvent(
            event_type="status",
            message=f"Fetching {len(fetch_targets)} live web pages...",
        )

        event_queue: asyncio.Queue[Optional[neutron_pb.CrawlStreamEvent]] = asyncio.Queue()
        sem = asyncio.Semaphore(settings.MAX_CONCURRENT_JIT_FETCHES)

        async with AsyncSession(impersonate="chrome124") as session:
            async def _worker(url: str) -> None:
                domain = extract_domain_host(url)
                await event_queue.put(
                    neutron_pb.CrawlStreamEvent(
                        event_type="crawl_start",
                        url=url,
                        domain=domain,
                    )
                )
                async with sem:
                    outcome = await _crawl_one_outcome(
                        session,
                        url,
                        clean_query,
                        fast_live=True,
                        include_full_text=include_full_text,
                        check_robots=True,
                    )
                if outcome.robots_blocked:
                    evt_type = "crawl_blocked"
                elif outcome.ok and outcome.document.url:
                    evt_type = "crawl_success"
                else:
                    evt_type = "crawl_error"
                await event_queue.put(
                    neutron_pb.CrawlStreamEvent(
                        event_type=evt_type,
                        url=url,
                        domain=outcome.domain or domain,
                        outcome=outcome,
                    )
                )

            async def _run_batch() -> None:
                tasks = [asyncio.create_task(_worker(u)) for u in fetch_targets]
                try:
                    done, pending = await asyncio.wait(
                        tasks, timeout=settings.LIVE_JIT_DEADLINE_SECONDS
                    )
                    for p in pending:
                        p.cancel()
                    for t in done:
                        if not t.cancelled():
                            t.exception()
                finally:
                    await event_queue.put(None)

            runner = asyncio.create_task(_run_batch())
            try:
                while True:
                    item = await event_queue.get()
                    if item is None:
                        break
                    yield item
            finally:
                if not runner.done():
                    runner.cancel()
                    try:
                        await runner
                    except asyncio.CancelledError:
                        pass

    async def discover_and_crawl(
        self,
        request: neutron_pb.DiscoverAndCrawlRequest,
        ctx: RequestContext,
        /,
    ) -> neutron_pb.DiscoverAndCrawlResponse:
        clean_query = (request.query or "").strip()
        if not clean_query:
            return neutron_pb.DiscoverAndCrawlResponse()

        max_pages = max(1, min(int(request.max_pages or 8), 20))
        mode = (request.mode or "all").strip().lower()
        skip_urls = set(request.skip_urls or ())
        include_full_text = bool(request.include_full_text)

        candidates, metrics = await discover_seed_urls_detailed(
            clean_query,
            max_urls=max_pages,
            mode=mode,
            skip_domains=legacy_crawler._get_active_waf_domains(),
        )
        fetch_targets = [u for u in candidates if u not in skip_urls]
        crawled_docs: List[neutron_pb.SearchDocument] = []

        if fetch_targets:
            async with AsyncSession(impersonate="chrome124") as session:
                tasks = [
                    asyncio.create_task(
                        legacy_crawler.fetch_and_index_document(
                            session,
                            url,
                            check_robots=True,
                            query=clean_query,
                            fast_live=True,
                            include_full_text=include_full_text,
                        )
                    )
                    for url in fetch_targets
                ]
                done, pending = await asyncio.wait(
                    tasks, timeout=settings.LIVE_JIT_DEADLINE_SECONDS
                )
                for p in pending:
                    p.cancel()
                for t in done:
                    try:
                        item = t.result()
                        if isinstance(item, dict) and item:
                            crawled_docs.append(
                                doc_to_proto(item, include_full_text=include_full_text)
                            )
                    except Exception:
                        continue

        return neutron_pb.DiscoverAndCrawlResponse(
            documents=crawled_docs,
            metrics=[_to_metric_proto(m) for m in metrics],
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Connect Turso, warm Bloom filter, and keep background loop disabled unless enabled."""
    global _bg_task
    if settings.REQUIRE_INTERNAL_API_KEY and not settings.INTERNAL_API_KEY:
        raise RuntimeError("REQUIRE_INTERNAL_API_KEY is true, but INTERNAL_API_KEY is missing.")

    try:
        if turso_crawler_client.is_configured():
            await turso_crawler_client.connect()
            await legacy_crawler._warm_bloom_filter()
            await turso_crawler_client.recover_expired_leases()
            logger.info("crawler_service_turso_connected")
            if settings.BACKGROUND_CRAWLER_ENABLED:
                _bg_task = asyncio.create_task(legacy_crawler.background_politeness_worker())
                logger.info("crawler_service_bg_worker_started")
    except Exception as exc:
        logger.warning("crawler_service_startup_warning", error=str(exc))

    yield

    if _bg_task and not _bg_task.done():
        _bg_task.cancel()
        try:
            await _bg_task
        except asyncio.CancelledError:
            pass
    await turso_crawler_client.close()


app = FastAPI(
    title="Neutron Discovery & Crawler Service",
    version="3.0.0",
    lifespan=lifespan,
)
configure_cors(app, settings.cors_origins_list())
configure_middleware(app)

_auth_interceptor = InternalAuthInterceptor(
    settings.INTERNAL_API_KEY,
    require_key=settings.REQUIRE_INTERNAL_API_KEY,
)
_rpc_app = neutron_connect.CrawlerServiceASGIApplication(
    CrawlerServiceImpl(),
    interceptors=[_auth_interceptor],
)
mount_connect_service(app, _rpc_app)


@app.get("/health")
@app.get("/kaithhealth")
async def health_check() -> Dict[str, Any]:
    """Health check endpoint reporting serverless-safe crawler mode."""
    return {
        "status": "ok",
        "service": "neutron-crawler",
        "version": "3.0.0",
        "turso_configured": turso_crawler_client.is_configured(),
        "background_crawler_active": bool(_bg_task and not _bg_task.done()),
        "uptime_seconds": int(time.time() - _START_TIME),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=settings.PORT)


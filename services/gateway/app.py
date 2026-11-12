"""Neutron Public Edge Gateway (REST + SSE + ConnectRPC/gRPC) for Leapcell & GitHub Pages."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import time
from typing import Any, AsyncGenerator, Coroutine, Dict, List, Tuple
import urllib.parse

from connectrpc.code import Code
from connectrpc.errors import ConnectError
from connectrpc.request import RequestContext
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pyqwest import Client as PyqwestClient, HTTPTransport
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sse_starlette.sse import EventSourceResponse
from starlette.middleware.base import BaseHTTPMiddleware
import structlog

from neutron_rpc.neutron.v1 import neutron_connect, neutron_pb
from services.common.config import GatewayServiceSettings
from services.common.rpc import (
    answer_to_proto,
    configure_cors,
    doc_to_proto,
    internal_auth_headers,
    mount_connect_service,
    proto_to_answer,
    proto_to_doc,
    resolve_protocol,
)

settings = GatewayServiceSettings()
logger = structlog.get_logger("neutron.service.gateway")
_START_TIME = time.time()
_LAST_CRAWLER_WAKE_TS = 0.0


def _ephemeral_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else get_remote_address(request)


limiter = Limiter(key_func=_ephemeral_key)


class _PrivacyHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "interest-cohort=()")
        return response


def _fire_and_log(coro: Coroutine[Any, Any, Any], task_name: str) -> asyncio.Task:
    task = asyncio.create_task(coro)

    def _done(t: asyncio.Task) -> None:
        try:
            exc = t.exception()
            if exc is not None:
                logger.warning("gateway_bg_task_failed", task=task_name, error=str(exc))
        except asyncio.CancelledError:
            pass

    task.add_done_callback(_done)
    return task


def _rpc_headers() -> Dict[str, str]:
    return internal_auth_headers(settings.INTERNAL_API_KEY)


def _get_search_client() -> neutron_connect.SearchServiceClient:
    override = getattr(app.state, "search_client", None)
    if override is not None:
        return override
    return app.state._owned_search_client


def _get_crawler_client() -> neutron_connect.CrawlerServiceClient:
    override = getattr(app.state, "crawler_client", None)
    if override is not None:
        return override
    return app.state._owned_crawler_client


def _build_clients(
    transport: HTTPTransport,
) -> Tuple[neutron_connect.SearchServiceClient, neutron_connect.CrawlerServiceClient]:
    http_client = PyqwestClient(transport=transport)
    proto = resolve_protocol(settings.RPC_PROTOCOL)
    search_client = neutron_connect.SearchServiceClient(
        settings.SEARCH_SERVICE_URL.rstrip("/"),
        protocol=proto,
        send_compression=None,
        timeout_ms=settings.RPC_TIMEOUT_MS,
        http_client=http_client,
    )
    crawler_client = neutron_connect.CrawlerServiceClient(
        settings.CRAWLER_SERVICE_URL.rstrip("/"),
        protocol=proto,
        send_compression=None,
        timeout_ms=settings.RPC_TIMEOUT_MS,
        http_client=http_client,
    )
    return search_client, crawler_client


async def _execute_gateway_search(
    clean_query: str,
    *,
    limit: int = 15,
    mode: str = "all",
    include_markdown: bool = False,
) -> Dict[str, Any]:
    """Coordinate SearchService + CrawlerService over ConnectRPC/gRPC."""
    search_client = _get_search_client()
    crawler_client = _get_crawler_client()
    headers = _rpc_headers()

    _fire_and_log(
        search_client.record_hot_topic(
            neutron_pb.RecordHotTopicRequest(query=clean_query),
            headers=headers,
        ),
        "record_hot_topic",
    )

    cached_resp = await search_client.query_index(
        neutron_pb.QueryIndexRequest(
            query=clean_query,
            limit=limit,
            mode=mode,
            include_markdown=include_markdown,
        ),
        headers=headers,
    )
    cached_docs = [proto_to_doc(d, include_full_text=False) for d in cached_resp.results]

    if len(cached_docs) >= settings.JIT_CACHE_THRESHOLD:
        return {
            "query": clean_query,
            "mode": mode,
            "source": "index_cache",
            "total": len(cached_docs),
            "answer": proto_to_answer(cached_resp.answer, has_answer=cached_resp.has_answer),
            "results": cached_docs[:limit],
        }

    live_proto_docs: List[neutron_pb.SearchDocument] = []
    try:
        crawl_resp = await crawler_client.discover_and_crawl(
            neutron_pb.DiscoverAndCrawlRequest(
                query=clean_query,
                max_pages=8,
                mode=mode,
                skip_urls=[d["url"] for d in cached_docs if d.get("url")],
                include_full_text=True,
            ),
            headers=headers,
        )
        live_proto_docs = list(crawl_resp.documents)
    except Exception as exc:
        logger.warning("gateway_crawler_rpc_failed", error=str(exc))

    if not live_proto_docs:
        return {
            "query": clean_query,
            "mode": mode,
            "source": "hybrid_jit",
            "total": len(cached_docs),
            "answer": proto_to_answer(cached_resp.answer, has_answer=cached_resp.has_answer),
            "results": cached_docs[:limit],
        }

    # Merge unique hits preserving cached hits first, then synthesize over the combined pool
    seen_urls = {d.get("url") for d in cached_docs if d.get("url")}
    combined_proto: List[neutron_pb.SearchDocument] = [
        doc_to_proto(d, include_full_text=False) for d in cached_docs
    ]
    for ld in live_proto_docs:
        if ld.url and ld.url not in seen_urls:
            seen_urls.add(ld.url)
            combined_proto.append(ld)

    combined_proto = combined_proto[:limit]
    synth_resp = await search_client.synthesize_answer(
        neutron_pb.SynthesizeAnswerRequest(
            query=clean_query,
            documents=combined_proto,
            include_markdown=include_markdown,
            max_sentences=settings.SYNTHESIS_MAX_SOURCES,
        ),
        headers=headers,
    )
    formatted = [proto_to_doc(d, include_full_text=False) for d in synth_resp.results]
    return {
        "query": clean_query,
        "mode": mode,
        "source": "hybrid_jit",
        "total": len(formatted),
        "answer": proto_to_answer(synth_resp.answer, has_answer=synth_resp.has_answer),
        "results": formatted,
    }


class GatewayServiceImpl:
    """Public ConnectRPC/gRPC mirror exposed alongside REST/SSE endpoints."""

    async def search(
        self,
        request: neutron_pb.GatewaySearchRequest,
        ctx: RequestContext,
        /,
    ) -> neutron_pb.GatewaySearchResponse:
        clean_query = (request.query or "").strip()
        if not clean_query:
            return neutron_pb.GatewaySearchResponse(query=clean_query, total=0)
        limit = max(1, min(int(request.limit or 15), 50))
        payload = await _execute_gateway_search(
            clean_query,
            limit=limit,
            mode=(request.mode or "all").strip().lower(),
            include_markdown=bool(request.include_markdown),
        )
        ans_proto, has_ans = answer_to_proto(payload.get("answer"))
        return neutron_pb.GatewaySearchResponse(
            query=payload["query"],
            mode=payload["mode"],
            source=payload["source"],
            total=payload["total"],
            answer=ans_proto,
            has_answer=has_ans,
            results=[doc_to_proto(r) for r in payload.get("results", [])],
        )

    async def suggest(
        self,
        request: neutron_pb.SuggestRequest,
        ctx: RequestContext,
        /,
    ) -> neutron_pb.SuggestResponse:
        return await _get_search_client().suggest(request, headers=_rpc_headers())

    async def get_stats(
        self,
        request: neutron_pb.GetStatsRequest,
        ctx: RequestContext,
        /,
    ) -> neutron_pb.GetStatsResponse:
        return await _get_search_client().get_stats(request, headers=_rpc_headers())

    async def get_document(
        self,
        request: neutron_pb.GetDocumentRequest,
        ctx: RequestContext,
        /,
    ) -> neutron_pb.GetDocumentResponse:
        return await _get_search_client().get_document(request, headers=_rpc_headers())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize reusable async ConnectRPC clients backed by pyqwest HTTPTransport."""
    async with HTTPTransport() as transport:
        search_client, crawler_client = _build_clients(transport)
        app.state._http_client = PyqwestClient(transport=transport)
        app.state._owned_search_client = search_client
        app.state._owned_crawler_client = crawler_client
        try:
            yield
        finally:
            await search_client.close()
            await crawler_client.close()


async def _wake_crawler_health() -> None:
    http_client = getattr(app.state, "_http_client", None)
    base = (settings.CRAWLER_SERVICE_URL or "").strip().rstrip("/")
    if http_client is None or not base:
        return
    try:
        await http_client.get(f"{base}/health")
    except Exception:
        pass


def _maybe_wake_crawler() -> None:
    """Throttled non-blocking ping so sleeping Render/free crawler services start warming."""
    global _LAST_CRAWLER_WAKE_TS
    now = time.monotonic()
    if now - _LAST_CRAWLER_WAKE_TS < 180.0:
        return
    _LAST_CRAWLER_WAKE_TS = now
    _fire_and_log(_wake_crawler_health(), "wake_crawler_health")


app = FastAPI(
    title="Neutron Search Edge Gateway",
    description="Public REST, SSE, and ConnectRPC/gRPC coordinator for Leapcell & GitHub Pages.",
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


configure_cors(app, settings.cors_origins_list())
app.add_middleware(_PrivacyHeadersMiddleware)
mount_connect_service(
    app, neutron_connect.GatewayServiceASGIApplication(GatewayServiceImpl())
)


@app.get("/health")
@app.get("/kaithhealth")
async def health_check() -> Dict[str, Any]:
    """Readiness probe for Leapcell gateway."""
    return {
        "status": "ok",
        "service": "neutron-gateway",
        "version": "3.0.0",
        "rpc_protocol": settings.RPC_PROTOCOL,
        "uptime_seconds": int(time.time() - _START_TIME),
    }


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_endpoint() -> str:
    """Serve monochrome privacy statement."""
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Neutron Privacy</title></head><body style='background:#000000;color:#d4d4d4;"
        "font-family:-apple-system,BlinkMacSystemFont,\"Segoe UI\",Inter,sans-serif;max-width:640px;margin:64px auto;padding:0 24px;line-height:1.7;font-size:15px'>"
        "<h1 style='color:#ffffff;font-size:24px;font-weight:600;letter-spacing:-0.02em'>Neutron Privacy</h1>"
        "<p>Zero Tracking. Zero Cookies. Zero server-side query telemetry.</p>"
        "<p style='margin-top:28px'><a href='/' style='color:#ffffff;text-decoration:underline;text-underline-offset:4px'>&larr; Back to Neutron</a></p></body></html>"
    )


@app.get("/stats")
async def stats_endpoint() -> Dict[str, Any]:
    """Return index metrics retrieved via SearchService ConnectRPC."""
    _maybe_wake_crawler()
    try:
        resp = await _get_search_client().get_stats(
            neutron_pb.GetStatsRequest(), headers=_rpc_headers()
        )
        s = resp.stats
        return {
            "pages_indexed": int(s.pages_indexed),
            "domains_covered": int(s.domains_covered),
            "frontier_pending": int(s.frontier_pending),
            "payloads_stored": int(s.payloads_stored),
            "connected": bool(s.connected),
            "uptime_seconds": int(time.time() - _START_TIME),
        }
    except Exception as exc:
        logger.warning("gateway_stats_rpc_failed", error=str(exc))
        return {
            "pages_indexed": 0,
            "domains_covered": 0,
            "frontier_pending": 0,
            "payloads_stored": 0,
            "connected": False,
            "uptime_seconds": int(time.time() - _START_TIME),
        }


@app.get("/suggest")
async def suggest_endpoint(
    q: str = Query(..., min_length=2, max_length=64),
) -> Dict[str, Any]:
    resp = await _get_search_client().suggest(
        neutron_pb.SuggestRequest(query=q, limit=6), headers=_rpc_headers()
    )
    return {"query": q, "suggestions": list(resp.suggestions)}


@app.get("/trending")
async def trending_endpoint() -> Dict[str, Any]:
    resp = await _get_search_client().get_trending(
        neutron_pb.GetTrendingRequest(limit=8), headers=_rpc_headers()
    )
    return {
        "trending": [{"topic": t.topic, "hits": int(t.hits)} for t in resp.trending]
    }


@app.get("/doc/{url_hash}")
async def get_document(url_hash: str) -> Dict[str, Any]:
    """Fetch compressed full document Markdown via SearchService ConnectRPC."""
    try:
        resp = await _get_search_client().get_document(
            neutron_pb.GetDocumentRequest(url_hash=url_hash),
            headers=_rpc_headers(),
        )
    except ConnectError as exc:
        status = 400 if exc.code == Code.INVALID_ARGUMENT else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc

    if not resp.found:
        raise HTTPException(status_code=404, detail="Document not found")

    return {
        "url_hash": resp.url_hash,
        "url": resp.url or None,
        "title": resp.title or None,
        "crawled_at": resp.crawled_at or None,
        "full_markdown": resp.full_markdown,
        "source": resp.source,
    }


@app.get("/search")
@limiter.limit(settings.RATE_LIMIT_SEARCH)
async def search_endpoint(
    request: Request,
    q: str = Query(..., min_length=1, max_length=256),
    limit: int = Query(15, ge=1, le=50),
    mode: str = Query("all"),
) -> Dict[str, Any]:
    """Execute unified hybrid search over ConnectRPC microservices."""
    clean_query = q.strip()
    if not clean_query:
        return {"query": q, "total": 0, "answer": None, "results": []}
    return await _execute_gateway_search(clean_query, limit=limit, mode=mode)


@app.get("/api/research")
@limiter.limit(settings.RATE_LIMIT_RESEARCH)
async def research_endpoint(
    request: Request,
    q: str = Query(..., min_length=1, max_length=256),
    max_results: int = Query(5, ge=1, le=15),
    include_markdown: bool = Query(True),
    mode: str = Query("all"),
) -> Dict[str, Any]:
    """Developer & AI-Agent JSON API backed by SearchService + CrawlerService RPC."""
    clean_query = q.strip()
    if not clean_query:
        return {"query": q, "total": 0, "answer": None, "sources": []}
    payload = await _execute_gateway_search(
        clean_query,
        limit=max_results,
        mode=mode,
        include_markdown=include_markdown,
    )
    return {
        "query": payload["query"],
        "mode": payload["mode"],
        "source": payload["source"],
        "answer": payload["answer"],
        "total": payload["total"],
        "sources": payload["results"],
    }


@app.get("/search/stream")
@limiter.limit(settings.RATE_LIMIT_STREAM)
async def search_stream(
    request: Request,
    q: str = Query(..., min_length=1, max_length=256),
    mode: str = Query("all"),
) -> Any:
    """Stream cached index hits, microservice JIT crawl progress, and cited synthesis via SSE."""
    clean_query = q.strip()
    search_client = _get_search_client()
    crawler_client = _get_crawler_client()
    headers = _rpc_headers()

    _fire_and_log(
        search_client.record_hot_topic(
            neutron_pb.RecordHotTopicRequest(query=clean_query), headers=headers
        ),
        "record_hot_topic",
    )

    async def event_generator() -> AsyncGenerator[Dict[str, str], None]:
        cached_resp = await search_client.query_index(
            neutron_pb.QueryIndexRequest(
                query=clean_query, limit=10, mode=mode, include_markdown=False
            ),
            headers=headers,
        )
        cached_docs = [proto_to_doc(d, include_full_text=False) for d in cached_resp.results]
        collected_proto: List[neutron_pb.SearchDocument] = list(cached_resp.results)

        yield {
            "event": "cached_results",
            "data": json.dumps(
                {
                    "count": len(cached_docs),
                    "duration_ms": int(cached_resp.duration_ms),
                    "results": cached_docs,
                }
            ),
        }

        if len(cached_docs) < settings.JIT_CACHE_THRESHOLD and not await request.is_disconnected():
            yield {
                "event": "discovery_start",
                "data": json.dumps(
                    {"sources": ["duckduckgo", "wikipedia", "hackernews", "arxiv", "github", "reddit"]}
                ),
            }
            yield {
                "event": "status",
                "data": json.dumps({"message": "Discovering live web sources..."}),
            }

            try:
                seeds_resp = await crawler_client.discover_seeds(
                    neutron_pb.DiscoverSeedsRequest(
                        query=clean_query, max_urls=8, mode=mode
                    ),
                    headers=headers,
                )
                for m in seeds_resp.metrics:
                    yield {
                        "event": "discovery_result",
                        "data": json.dumps(
                            {
                                "source": m.source,
                                "urls_found": int(m.urls_found),
                                "duration_ms": int(m.duration_ms),
                                "status": m.status,
                            }
                        ),
                    }

                existing_urls = {d.get("url") for d in cached_docs if d.get("url")}
                crawl_targets = [u for u in seeds_resp.urls if u not in existing_urls]

                if crawl_targets:
                    yield {
                        "event": "status",
                        "data": json.dumps(
                            {"message": f"Fetching {len(crawl_targets)} live web pages..."}
                        ),
                    }

                    crawl_events: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

                    async def _crawl_one(url: str) -> None:
                        host = urllib.parse.urlsplit(url).netloc.lower()
                        host = host[4:] if host.startswith("www.") else (host or url)
                        await crawl_events.put(
                            {"event": "crawl_start", "data": {"url": url, "domain": host}}
                        )
                        try:
                            resp = await crawler_client.crawl_url(
                                neutron_pb.CrawlUrlRequest(
                                    url=url,
                                    query=clean_query,
                                    fast_live=True,
                                    include_full_text=True,
                                    check_robots=True,
                                ),
                                headers=headers,
                            )
                            oc = resp.outcome
                            if oc.robots_blocked:
                                await crawl_events.put(
                                    {
                                        "event": "crawl_blocked",
                                        "data": {
                                            "url": url,
                                            "domain": oc.domain,
                                            "reason": oc.error or "robots.txt",
                                        },
                                    }
                                )
                            elif oc.ok and oc.document.url:
                                collected_proto.append(oc.document)
                                pub_doc = proto_to_doc(oc.document, include_full_text=False)
                                await crawl_events.put(
                                    {
                                        "event": "crawl_success",
                                        "data": {
                                            "url": url,
                                            "domain": oc.domain,
                                            "title": pub_doc.get("title", oc.domain),
                                            "duration_ms": int(oc.duration_ms),
                                        },
                                    }
                                )
                                await crawl_events.put(
                                    {"event": "live_result", "data": pub_doc}
                                )
                            else:
                                await crawl_events.put(
                                    {
                                        "event": "crawl_error",
                                        "data": {
                                            "url": url,
                                            "domain": oc.domain,
                                            "error": oc.error or "skipped",
                                        },
                                    }
                                )
                        except Exception as exc:
                            await crawl_events.put(
                                {
                                    "event": "crawl_error",
                                    "data": {"url": url, "domain": url, "error": str(exc)[:80]},
                                }
                            )

                    tasks = [asyncio.create_task(_crawl_one(u)) for u in crawl_targets]
                    gather_fut = asyncio.gather(*tasks, return_exceptions=True)
                    deadline = time.monotonic() + settings.LIVE_JIT_DEADLINE_SECONDS

                    while not gather_fut.done() or not crawl_events.empty():
                        if await request.is_disconnected():
                            for t in tasks:
                                t.cancel()
                            return
                        if time.monotonic() >= deadline and not gather_fut.done():
                            for t in tasks:
                                if not t.done():
                                    t.cancel()
                            break
                        try:
                            ev = await asyncio.wait_for(crawl_events.get(), timeout=0.1)
                            yield {"event": ev["event"], "data": json.dumps(ev["data"])}
                        except asyncio.TimeoutError:
                            continue

                    while not crawl_events.empty():
                        ev = crawl_events.get_nowait()
                        yield {"event": ev["event"], "data": json.dumps(ev["data"])}
            except Exception as exc:
                logger.warning("gateway_stream_crawler_failed", error=str(exc))

        if collected_proto and not await request.is_disconnected():
            # Reuse cached synthesis if no live documents were added
            if len(collected_proto) == len(cached_docs) and cached_resp.has_answer:
                ans = proto_to_answer(cached_resp.answer, has_answer=True)
                if ans:
                    yield {"event": "answer", "data": json.dumps(ans)}
            else:
                try:
                    synth = await search_client.synthesize_answer(
                        neutron_pb.SynthesizeAnswerRequest(
                            query=clean_query,
                            documents=collected_proto[: settings.SYNTHESIS_MAX_SOURCES],
                            include_markdown=False,
                            max_sentences=settings.SYNTHESIS_MAX_SOURCES,
                        ),
                        headers=headers,
                    )
                    ans = proto_to_answer(synth.answer, has_answer=synth.has_answer)
                    if ans:
                        yield {"event": "answer", "data": json.dumps(ans)}
                except Exception as exc:
                    logger.warning("gateway_stream_synth_failed", error=str(exc))

        yield {"event": "done", "data": json.dumps({"completed": True})}

    return EventSourceResponse(event_generator())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=settings.PORT)

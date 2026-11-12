"""Neutron Public Edge Gateway (REST + SSE + ConnectRPC/gRPC) for Render & GitHub Pages."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
import json
import time
from typing import Any, AsyncGenerator, Coroutine, Dict, List, Optional, Tuple
import uuid

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
_LAST_DOWNSTREAM_WAKE_TS = 0.0


class _TTLCache:
    """Bounded in-memory LRU+TTL response cache for hot queries and stats."""

    def __init__(self, *, maxsize: int = 256, ttl_seconds: float = 300.0) -> None:
        self._maxsize = max(1, int(maxsize))
        self._ttl = max(1.0, float(ttl_seconds))
        self._data: OrderedDict[Any, Tuple[float, Any]] = OrderedDict()

    def get(self, key: Any) -> Optional[Any]:
        entry = self._data.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: Any, value: Any, *, ttl_seconds: Optional[float] = None) -> None:
        ttl = self._ttl if ttl_seconds is None else max(1.0, float(ttl_seconds))
        self._data[key] = (time.monotonic() + ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self._maxsize:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()


_search_cache = _TTLCache(maxsize=256, ttl_seconds=float(settings.CACHE_TTL_SECONDS))
_stats_cache = _TTLCache(maxsize=4, ttl_seconds=30.0)


def _ephemeral_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else get_remote_address(request)


limiter = Limiter(key_func=_ephemeral_key)


class _PrivacyHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Any:
        req_id = (request.headers.get("x-request-id") or "").strip()[:64] or uuid.uuid4().hex[:12]
        request.state.request_id = req_id
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "interest-cohort=()")
        response.headers["X-Request-Id"] = req_id
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


def _rpc_headers(request_id: Optional[str] = None) -> Dict[str, str]:
    return internal_auth_headers(settings.INTERNAL_API_KEY, request_id=request_id)


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
    refresh: bool = False,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Coordinate SearchService + CrawlerService over ConnectRPC/gRPC with TTL caching & timings."""
    cache_key = ("json", clean_query.lower(), mode, limit, include_markdown)
    if not refresh:
        cached_payload = _search_cache.get(cache_key)
        if cached_payload is not None:
            return {
                **cached_payload,
                "cache_hit": True,
                "request_id": request_id or "",
            }

    total_t0 = time.perf_counter()
    search_client = _get_search_client()
    crawler_client = _get_crawler_client()
    headers = _rpc_headers(request_id)

    _fire_and_log(
        search_client.record_hot_topic(
            neutron_pb.RecordHotTopicRequest(query=clean_query),
            headers=headers,
        ),
        "record_hot_topic",
    )

    search_ok = True
    search_err = ""
    cached_resp = None
    cached_docs: List[Dict[str, Any]] = []
    index_t0 = time.perf_counter()
    try:
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
    except Exception as exc:
        search_ok = False
        search_err = str(exc)
        logger.warning("gateway_search_rpc_failed", request_id=request_id, error=search_err)
    index_ms = round((time.perf_counter() - index_t0) * 1000)

    if not refresh and cached_resp is not None and len(cached_docs) >= settings.JIT_CACHE_THRESHOLD:
        total_ms = round((time.perf_counter() - total_t0) * 1000)
        payload = {
            "query": clean_query,
            "mode": mode,
            "source": "index_cache",
            "total": len(cached_docs),
            "answer": proto_to_answer(cached_resp.answer, has_answer=cached_resp.has_answer),
            "results": cached_docs[:limit],
            "cache_hit": False,
            "request_id": request_id or "",
            "timings": {"index_ms": index_ms, "crawl_ms": 0, "synth_ms": 0, "total_ms": total_ms},
        }
        if payload["results"]:
            _search_cache.set(cache_key, payload)
        return payload

    live_proto_docs: List[neutron_pb.SearchDocument] = []
    crawl_t0 = time.perf_counter()
    try:
        crawl_resp = await crawler_client.discover_and_crawl(
            neutron_pb.DiscoverAndCrawlRequest(
                query=clean_query,
                max_pages=8,
                mode=mode,
                skip_urls=[] if refresh else [d["url"] for d in cached_docs if d.get("url")],
                include_full_text=True,
            ),
            headers=headers,
        )
        live_proto_docs = list(crawl_resp.documents)
    except Exception as exc:
        logger.warning("gateway_crawler_rpc_failed", request_id=request_id, error=str(exc))
    crawl_ms = round((time.perf_counter() - crawl_t0) * 1000)

    if not search_ok and not live_proto_docs:
        _maybe_wake_downstream()
        raise HTTPException(
            status_code=503,
            detail=f"Search backend unavailable: {search_err or 'connection failed'}",
        )

    if not live_proto_docs:
        total_ms = round((time.perf_counter() - total_t0) * 1000)
        payload = {
            "query": clean_query,
            "mode": mode,
            "source": "hybrid_jit",
            "total": len(cached_docs),
            "answer": (
                proto_to_answer(cached_resp.answer, has_answer=cached_resp.has_answer)
                if cached_resp is not None
                else None
            ),
            "results": cached_docs[:limit],
            "cache_hit": False,
            "request_id": request_id or "",
            "timings": {"index_ms": index_ms, "crawl_ms": crawl_ms, "synth_ms": 0, "total_ms": total_ms},
        }
        if payload["results"]:
            _search_cache.set(cache_key, payload)
        return payload

    # Merge unique hits, letting fresh live docs replace stale cached entries on refresh
    live_by_url: Dict[str, neutron_pb.SearchDocument] = {
        ld.url: ld for ld in live_proto_docs if ld.url
    }
    combined_proto: List[neutron_pb.SearchDocument] = []
    seen_urls: set[str] = set()
    for d in cached_docs:
        u = d.get("url")
        if not u or u in seen_urls:
            continue
        seen_urls.add(u)
        combined_proto.append(live_by_url.get(u) or doc_to_proto(d, include_full_text=False))
    for ld in live_proto_docs:
        if ld.url and ld.url not in seen_urls:
            seen_urls.add(ld.url)
            combined_proto.append(ld)

    synth_pool = combined_proto[: max(limit, 12)]
    synth_ms = 0
    if search_ok:
        synth_t0 = time.perf_counter()
        try:
            synth_resp = await search_client.synthesize_answer(
                neutron_pb.SynthesizeAnswerRequest(
                    query=clean_query,
                    documents=synth_pool,
                    include_markdown=include_markdown,
                    max_sentences=settings.SYNTHESIS_MAX_SOURCES,
                ),
                headers=headers,
            )
            synth_ms = round((time.perf_counter() - synth_t0) * 1000)
            total_ms = round((time.perf_counter() - total_t0) * 1000)
            formatted = [proto_to_doc(d, include_full_text=False) for d in synth_resp.results][:limit]
            payload = {
                "query": clean_query,
                "mode": mode,
                "source": "hybrid_jit",
                "total": len(formatted),
                "answer": proto_to_answer(synth_resp.answer, has_answer=synth_resp.has_answer),
                "results": formatted,
                "cache_hit": False,
                "request_id": request_id or "",
                "timings": {
                    "index_ms": index_ms,
                    "crawl_ms": crawl_ms,
                    "synth_ms": synth_ms,
                    "total_ms": total_ms,
                },
            }
            if payload["results"]:
                _search_cache.set(cache_key, payload)
            return payload
        except Exception as exc:
            synth_ms = round((time.perf_counter() - synth_t0) * 1000)
            logger.warning("gateway_synth_rpc_failed", request_id=request_id, error=str(exc))

    fallback_docs = [proto_to_doc(d, include_full_text=False) for d in combined_proto[:limit]]
    total_ms = round((time.perf_counter() - total_t0) * 1000)
    return {
        "query": clean_query,
        "mode": mode,
        "source": "live_fallback",
        "total": len(fallback_docs),
        "answer": None,
        "results": fallback_docs,
        "cache_hit": False,
        "request_id": request_id or "",
        "timings": {"index_ms": index_ms, "crawl_ms": crawl_ms, "synth_ms": synth_ms, "total_ms": total_ms},
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
            refresh=bool(request.refresh),
            request_id=ctx.request_headers.get("x-request-id"),
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
        return await _get_search_client().suggest(
            request, headers=_rpc_headers(ctx.request_headers.get("x-request-id"))
        )

    async def get_stats(
        self,
        request: neutron_pb.GetStatsRequest,
        ctx: RequestContext,
        /,
    ) -> neutron_pb.GetStatsResponse:
        return await _get_search_client().get_stats(
            request, headers=_rpc_headers(ctx.request_headers.get("x-request-id"))
        )

    async def get_document(
        self,
        request: neutron_pb.GetDocumentRequest,
        ctx: RequestContext,
        /,
    ) -> neutron_pb.GetDocumentResponse:
        return await _get_search_client().get_document(
            request, headers=_rpc_headers(ctx.request_headers.get("x-request-id"))
        )


def _load_tls_ca_cert() -> bytes | None:
    """Load certifi PEM root CAs so pyqwest verifies HTTPS origins inside containers."""
    try:
        import certifi

        with open(certifi.where(), "rb") as fh:
            return fh.read()
    except Exception:
        return None


def _build_http_transport() -> HTTPTransport:
    return HTTPTransport(
        tls_ca_cert=_load_tls_ca_cert(),
        tls_include_system_certs=True,
        timeout=max(10.0, settings.RPC_TIMEOUT_MS / 1000.0),
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize reusable async ConnectRPC clients backed by pyqwest HTTPTransport."""
    _search_cache.clear()
    _stats_cache.clear()
    async with _build_http_transport() as transport:
        search_client, crawler_client = _build_clients(transport)
        app.state._http_client = PyqwestClient(transport=transport)
        app.state._owned_search_client = search_client
        app.state._owned_crawler_client = crawler_client
        try:
            yield
        finally:
            _search_cache.clear()
            _stats_cache.clear()
            await search_client.close()
            await crawler_client.close()


async def _ping_health(http_client: PyqwestClient, base_url: str) -> None:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return
    try:
        await http_client.get(f"{base}/health")
    except Exception:
        pass


async def _wake_downstream_health() -> None:
    http_client = getattr(app.state, "_http_client", None)
    if http_client is None:
        return
    await asyncio.gather(
        _ping_health(http_client, settings.SEARCH_SERVICE_URL),
        _ping_health(http_client, settings.CRAWLER_SERVICE_URL),
        return_exceptions=True,
    )


def _maybe_wake_downstream() -> None:
    """Throttled non-blocking ping so sleeping Render search and crawler services warm up."""
    global _LAST_DOWNSTREAM_WAKE_TS
    now = time.monotonic()
    if now - _LAST_DOWNSTREAM_WAKE_TS < 180.0:
        return
    _LAST_DOWNSTREAM_WAKE_TS = now
    _fire_and_log(_wake_downstream_health(), "wake_downstream_health")


app = FastAPI(
    title="Neutron Search Edge Gateway",
    description="Public REST, SSE, and ConnectRPC/gRPC coordinator for Render & GitHub Pages.",
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


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("gateway_unhandled_exception", path=str(request.url.path), error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"error": "gateway_internal_error", "detail": "Internal gateway error"},
    )


configure_cors(app, settings.cors_origins_list())
app.add_middleware(_PrivacyHeadersMiddleware)
mount_connect_service(
    app, neutron_connect.GatewayServiceASGIApplication(GatewayServiceImpl())
)


@app.get("/health")
@app.get("/kaithhealth")
async def health_check() -> Dict[str, Any]:
    """Readiness probe that also triggers throttled downstream warm-up."""
    _maybe_wake_downstream()
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
async def stats_endpoint(request: Request) -> Dict[str, Any]:
    """Return index metrics retrieved via SearchService ConnectRPC (cached 30s when connected)."""
    _maybe_wake_downstream()
    cached = _stats_cache.get("stats")
    if cached is not None:
        return {**cached, "uptime_seconds": int(time.time() - _START_TIME)}
    req_id = getattr(request.state, "request_id", None)
    try:
        resp = await _get_search_client().get_stats(
            neutron_pb.GetStatsRequest(), headers=_rpc_headers(req_id)
        )
        s = resp.stats
        payload = {
            "pages_indexed": int(s.pages_indexed),
            "domains_covered": int(s.domains_covered),
            "frontier_pending": int(s.frontier_pending),
            "payloads_stored": int(s.payloads_stored),
            "connected": bool(s.connected),
            "uptime_seconds": int(time.time() - _START_TIME),
        }
        if payload["connected"]:
            _stats_cache.set("stats", payload, ttl_seconds=30.0)
        return payload
    except Exception as exc:
        logger.warning("gateway_stats_rpc_failed", request_id=req_id, error=str(exc))
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
    request: Request,
    q: str = Query(..., min_length=2, max_length=64),
) -> Dict[str, Any]:
    req_id = getattr(request.state, "request_id", None)
    try:
        resp = await _get_search_client().suggest(
            neutron_pb.SuggestRequest(query=q, limit=6), headers=_rpc_headers(req_id)
        )
        return {"query": q, "suggestions": list(resp.suggestions)}
    except Exception as exc:
        logger.warning("gateway_suggest_rpc_failed", request_id=req_id, error=str(exc))
        return {"query": q, "suggestions": []}


@app.get("/trending")
async def trending_endpoint(request: Request) -> Dict[str, Any]:
    req_id = getattr(request.state, "request_id", None)
    try:
        resp = await _get_search_client().get_trending(
            neutron_pb.GetTrendingRequest(limit=8), headers=_rpc_headers(req_id)
        )
        return {
            "trending": [{"topic": t.topic, "hits": int(t.hits)} for t in resp.trending]
        }
    except Exception as exc:
        logger.warning("gateway_trending_rpc_failed", request_id=req_id, error=str(exc))
        return {"trending": []}


@app.get("/doc/{url_hash}")
async def get_document(request: Request, url_hash: str) -> Dict[str, Any]:
    """Fetch compressed full document Markdown via SearchService ConnectRPC."""
    req_id = getattr(request.state, "request_id", None)
    try:
        resp = await _get_search_client().get_document(
            neutron_pb.GetDocumentRequest(url_hash=url_hash),
            headers=_rpc_headers(req_id),
        )
    except ConnectError as exc:
        status = 400 if exc.code == Code.INVALID_ARGUMENT else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Search backend unavailable: {exc}") from exc

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
    refresh: bool = Query(False),
) -> Dict[str, Any]:
    """Execute unified hybrid search over ConnectRPC microservices."""
    clean_query = q.strip()
    if not clean_query:
        return {"query": q, "total": 0, "answer": None, "results": []}
    return await _execute_gateway_search(
        clean_query,
        limit=limit,
        mode=mode,
        refresh=refresh,
        request_id=getattr(request.state, "request_id", None),
    )


@app.get("/api/research")
@limiter.limit(settings.RATE_LIMIT_RESEARCH)
async def research_endpoint(
    request: Request,
    q: str = Query(..., min_length=1, max_length=256),
    max_results: int = Query(5, ge=1, le=15),
    include_markdown: bool = Query(True),
    mode: str = Query("all"),
    refresh: bool = Query(False),
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
        refresh=refresh,
        request_id=getattr(request.state, "request_id", None),
    )
    return {
        "query": payload["query"],
        "mode": payload["mode"],
        "source": payload["source"],
        "answer": payload["answer"],
        "total": payload["total"],
        "sources": payload["results"],
        "timings": payload.get("timings"),
        "request_id": payload.get("request_id"),
    }


@app.get("/search/stream")
@limiter.limit(settings.RATE_LIMIT_STREAM)
async def search_stream(
    request: Request,
    q: str = Query(..., min_length=1, max_length=256),
    mode: str = Query("all"),
    refresh: bool = Query(False),
) -> Any:
    """Stream cached index hits, microservice StreamCrawl progress, and cited synthesis via SSE."""
    clean_query = q.strip()
    req_id = getattr(request.state, "request_id", None) or ""
    if not clean_query:
        async def _empty_stream() -> AsyncGenerator[Dict[str, str], None]:
            yield {
                "event": "cached_results",
                "data": json.dumps({"count": 0, "duration_ms": 0, "results": [], "cache_hit": False}),
            }
            yield {
                "event": "done",
                "data": json.dumps({"completed": True, "cache_hit": False, "request_id": req_id}),
            }

        return EventSourceResponse(_empty_stream())

    search_client = _get_search_client()
    crawler_client = _get_crawler_client()
    headers = _rpc_headers(req_id)

    _fire_and_log(
        search_client.record_hot_topic(
            neutron_pb.RecordHotTopicRequest(query=clean_query), headers=headers
        ),
        "record_hot_topic",
    )

    async def event_generator() -> AsyncGenerator[Dict[str, str], None]:
        total_t0 = time.perf_counter()
        stream_cache_key = ("stream", clean_query.lower(), mode)
        if not refresh:
            cached_stream = _search_cache.get(stream_cache_key)
            if cached_stream is not None:
                yield {
                    "event": "cached_results",
                    "data": json.dumps(
                        {
                            "count": len(cached_stream["results"]),
                            "duration_ms": 0,
                            "results": cached_stream["results"],
                            "cache_hit": True,
                        }
                    ),
                }
                if cached_stream.get("answer"):
                    yield {"event": "answer", "data": json.dumps(cached_stream["answer"])}
                yield {
                    "event": "done",
                    "data": json.dumps(
                        {
                            "completed": True,
                            "cache_hit": True,
                            "request_id": req_id,
                            "timings": {"index_ms": 0, "crawl_ms": 0, "synth_ms": 0, "total_ms": 0},
                        }
                    ),
                }
                return

        cached_resp = None
        cached_docs: List[Dict[str, Any]] = []
        collected_proto: List[neutron_pb.SearchDocument] = []
        search_ok = True
        crawl_ok = True
        index_ms = 0
        crawl_ms = 0
        synth_ms = 0

        try:
            cached_resp = await search_client.query_index(
                neutron_pb.QueryIndexRequest(
                    query=clean_query, limit=10, mode=mode, include_markdown=False
                ),
                headers=headers,
            )
            cached_docs = [proto_to_doc(d, include_full_text=False) for d in cached_resp.results]
            collected_proto = list(cached_resp.results)
            index_ms = int(cached_resp.duration_ms)
        except Exception as exc:
            search_ok = False
            logger.warning("gateway_stream_search_rpc_failed", request_id=req_id, error=str(exc))

        yield {
            "event": "cached_results",
            "data": json.dumps(
                {
                    "count": len(cached_docs),
                    "duration_ms": index_ms,
                    "results": cached_docs,
                    "cache_hit": False,
                }
            ),
        }

        should_crawl = refresh or len(cached_docs) < settings.JIT_CACHE_THRESHOLD
        added_live = False
        if should_crawl and not await request.is_disconnected():
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

            crawl_t0 = time.perf_counter()
            seen_urls = {d.get("url") for d in cached_docs if d.get("url")}
            try:
                async for ev in crawler_client.stream_crawl(
                    neutron_pb.StreamCrawlRequest(
                        query=clean_query,
                        max_pages=8,
                        mode=mode,
                        skip_urls=[] if refresh else list(seen_urls),
                        include_full_text=True,
                        force_refresh=refresh,
                    ),
                    headers=headers,
                ):
                    if await request.is_disconnected():
                        return
                    etype = ev.event_type
                    if etype == "discovery_result":
                        m = ev.metric
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
                    elif etype == "status":
                        yield {"event": "status", "data": json.dumps({"message": ev.message})}
                    elif etype == "crawl_start":
                        yield {
                            "event": "crawl_start",
                            "data": json.dumps({"url": ev.url, "domain": ev.domain}),
                        }
                    elif etype == "crawl_blocked":
                        oc = ev.outcome
                        yield {
                            "event": "crawl_blocked",
                            "data": json.dumps(
                                {
                                    "url": ev.url,
                                    "domain": oc.domain or ev.domain,
                                    "reason": oc.error or "robots.txt",
                                }
                            ),
                        }
                    elif etype == "crawl_success" and ev.outcome.document.url:
                        oc = ev.outcome
                        pub_doc = proto_to_doc(oc.document, include_full_text=False)
                        live_url = pub_doc.get("url")
                        if live_url:
                            if live_url not in seen_urls:
                                seen_urls.add(live_url)
                                collected_proto.append(oc.document)
                            else:
                                collected_proto = [
                                    oc.document if d.url == live_url else d
                                    for d in collected_proto
                                ]
                            added_live = True
                        yield {
                            "event": "crawl_success",
                            "data": json.dumps(
                                {
                                    "url": ev.url,
                                    "domain": oc.domain or ev.domain,
                                    "title": pub_doc.get("title", oc.domain or ev.domain),
                                    "duration_ms": int(oc.duration_ms),
                                }
                            ),
                        }
                        yield {"event": "live_result", "data": json.dumps(pub_doc)}
                    elif etype == "crawl_error":
                        oc = ev.outcome
                        yield {
                            "event": "crawl_error",
                            "data": json.dumps(
                                {
                                    "url": ev.url,
                                    "domain": oc.domain or ev.domain,
                                    "error": oc.error or "skipped",
                                }
                            ),
                        }
            except Exception as exc:
                crawl_ok = False
                logger.warning("gateway_stream_crawler_failed", request_id=req_id, error=str(exc))
            crawl_ms = round((time.perf_counter() - crawl_t0) * 1000)

        if not search_ok and (not should_crawl or not crawl_ok) and not collected_proto:
            _maybe_wake_downstream()
            yield {
                "event": "backend_error",
                "data": json.dumps(
                    {
                        "detail": "Search backend services are waking up or temporarily unavailable. Please retry in a few seconds.",
                        "request_id": req_id,
                    }
                ),
            }

        final_answer: Optional[Dict[str, Any]] = None
        if collected_proto and not await request.is_disconnected():
            if (
                not added_live
                and not refresh
                and cached_resp is not None
                and cached_resp.has_answer
            ):
                final_answer = proto_to_answer(cached_resp.answer, has_answer=True)
                if final_answer:
                    yield {"event": "answer", "data": json.dumps(final_answer)}
            else:
                synth_t0 = time.perf_counter()
                try:
                    synth = await search_client.synthesize_answer(
                        neutron_pb.SynthesizeAnswerRequest(
                            query=clean_query,
                            documents=collected_proto[: max(12, settings.SYNTHESIS_MAX_SOURCES)],
                            include_markdown=False,
                            max_sentences=settings.SYNTHESIS_MAX_SOURCES,
                        ),
                        headers=headers,
                    )
                    final_answer = proto_to_answer(synth.answer, has_answer=synth.has_answer)
                    if final_answer:
                        yield {"event": "answer", "data": json.dumps(final_answer)}
                except Exception as exc:
                    logger.warning("gateway_stream_synth_failed", request_id=req_id, error=str(exc))
                synth_ms = round((time.perf_counter() - synth_t0) * 1000)

        final_docs = [proto_to_doc(d, include_full_text=False) for d in collected_proto]
        if final_docs:
            _search_cache.set(
                stream_cache_key,
                {"results": final_docs, "answer": final_answer},
            )

        total_ms = round((time.perf_counter() - total_t0) * 1000)
        yield {
            "event": "done",
            "data": json.dumps(
                {
                    "completed": True,
                    "cache_hit": False,
                    "request_id": req_id,
                    "timings": {
                        "index_ms": index_ms,
                        "crawl_ms": crawl_ms,
                        "synth_ms": synth_ms,
                        "total_ms": total_ms,
                    },
                }
            ),
        }

    return EventSourceResponse(event_generator())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=settings.PORT)

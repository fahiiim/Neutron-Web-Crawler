"""Neutron Search & Synthesis ConnectRPC/gRPC Microservice (FastAPI + ConnectASGI)."""

from __future__ import annotations

from contextlib import asynccontextmanager
import time
from typing import Any, AsyncGenerator, Dict, List

from connectrpc.code import Code
from connectrpc.errors import ConnectError
from connectrpc.request import RequestContext
from fastapi import FastAPI

from neutron_rpc.neutron.v1 import neutron_connect, neutron_pb
from services.common.config import SearchServiceSettings
from services.common.rpc import (
    InternalAuthInterceptor,
    answer_to_proto,
    configure_cors,
    doc_to_proto,
    mount_connect_service,
    proto_to_doc,
)
from spaces.crawler.compression import decompress_text
from spaces.crawler.db_turso import turso_crawler_client
from spaces.crawler.dedup import hash_url
from spaces.crawler.logging_utils import get_logger
from spaces.crawler.middleware import configure_middleware
from spaces.crawler.synthesis import (
    attach_synthesis_and_excerpts,
    extract_query_highlights,
    filter_hits_by_mode,
    sort_hits_by_relevance,
)

settings = SearchServiceSettings()
logger = get_logger("neutron.service.search")
_START_TIME = time.time()


class SearchServiceImpl:
    """ConnectRPC/gRPC implementation for indexed search, synthesis, and reader lookup."""

    async def query_index(
        self,
        request: neutron_pb.QueryIndexRequest,
        ctx: RequestContext,
        /,
    ) -> neutron_pb.QueryIndexResponse:
        clean_query = (request.query or "").strip()
        if not clean_query:
            return neutron_pb.QueryIndexResponse()

        limit = max(1, min(int(request.limit or 15), 50))
        mode = (request.mode or "all").strip().lower()
        t0 = time.perf_counter()

        # Fetch a wider FTS pool so mode filtering and concept re-ranking retain strong hits
        fetch_limit = min(50, max(limit * 3, 30) if mode != "all" else max(limit * 2, 25))
        include_domains = list(request.include_domains or [])
        exclude_domains = list(request.exclude_domains or [])
        raw_hits = await turso_crawler_client.search(
            clean_query,
            limit=fetch_limit,
            include_domains=include_domains if include_domains else None,
            exclude_domains=exclude_domains if exclude_domains else None,
        )
        filtered_hits = filter_hits_by_mode(raw_hits, mode)
        reranked_hits = sort_hits_by_relevance(clean_query, filtered_hits, mode=mode)[:limit]
        formatted, answer = await attach_synthesis_and_excerpts(
            clean_query,
            reranked_hits,
            include_markdown=bool(request.include_markdown),
            max_sources=settings.SYNTHESIS_MAX_SOURCES,
            get_payloads_map=turso_crawler_client.get_payloads_map,
            decompress_fn=decompress_text,
            gemini_api_key=settings.GEMINI_API_KEY,
            gemini_model=settings.GEMINI_MODEL,
            gemini_timeout_seconds=settings.GEMINI_TIMEOUT_SECONDS,
        )
        duration_ms = round((time.perf_counter() - t0) * 1000)

        proto_answer, has_answer = answer_to_proto(answer)
        return neutron_pb.QueryIndexResponse(
            results=[doc_to_proto(d, include_full_text=False) for d in formatted],
            answer=proto_answer,
            has_answer=has_answer,
            duration_ms=duration_ms,
        )

    async def synthesize_answer(
        self,
        request: neutron_pb.SynthesizeAnswerRequest,
        ctx: RequestContext,
        /,
    ) -> neutron_pb.SynthesizeAnswerResponse:
        clean_query = (request.query or "").strip()
        docs: List[Dict[str, Any]] = [
            proto_to_doc(d, include_full_text=True) for d in request.documents
        ]
        if not clean_query or not docs:
            return neutron_pb.SynthesizeAnswerResponse(
                results=[doc_to_proto(d) for d in docs]
            )

        max_sources = max(1, min(int(request.max_sentences or settings.SYNTHESIS_MAX_SOURCES), 10))
        docs = sort_hits_by_relevance(clean_query, docs)
        formatted, answer = await attach_synthesis_and_excerpts(
            clean_query,
            docs,
            include_markdown=bool(request.include_markdown),
            max_sources=max_sources,
            get_payloads_map=turso_crawler_client.get_payloads_map,
            decompress_fn=decompress_text,
            gemini_api_key=settings.GEMINI_API_KEY,
            gemini_model=settings.GEMINI_MODEL,
            gemini_timeout_seconds=settings.GEMINI_TIMEOUT_SECONDS,
        )
        proto_answer, has_answer = answer_to_proto(answer)
        return neutron_pb.SynthesizeAnswerResponse(
            results=[doc_to_proto(d, include_full_text=False) for d in formatted],
            answer=proto_answer,
            has_answer=has_answer,
        )

    async def get_document(
        self,
        request: neutron_pb.GetDocumentRequest,
        ctx: RequestContext,
        /,
    ) -> neutron_pb.GetDocumentResponse:
        try:
            url_hash = int(str(request.url_hash).strip())
        except (TypeError, ValueError) as exc:
            raise ConnectError(Code.INVALID_ARGUMENT, "Invalid 64-bit url_hash") from exc

        if url_hash < -(1 << 63) or url_hash >= (1 << 63):
            raise ConnectError(Code.INVALID_ARGUMENT, "url_hash out of signed 64-bit range")

        meta = await turso_crawler_client.get_document_metadata(url_hash)
        payload_bytes = await turso_crawler_client.get_document_payload(url_hash)
        if payload_bytes:
            full_markdown = decompress_text(payload_bytes)
            if full_markdown:
                return neutron_pb.GetDocumentResponse(
                    found=True,
                    url_hash=str(url_hash),
                    url=str(meta.get("url") or "") if meta else "",
                    title=str(meta.get("title") or "") if meta else "",
                    crawled_at=str(meta.get("crawled_at") or "") if meta else "",
                    full_markdown=full_markdown,
                    source="turso_blob",
                )

        if not meta:
            return neutron_pb.GetDocumentResponse(found=False, url_hash=str(url_hash))

        return neutron_pb.GetDocumentResponse(
            found=True,
            url_hash=str(url_hash),
            url=str(meta.get("url") or ""),
            title=str(meta.get("title") or ""),
            crawled_at=str(meta.get("crawled_at") or ""),
            full_markdown=str(meta.get("snippet") or ""),
            source="snippet_fallback",
        )

    async def batch_get_documents(
        self,
        request: neutron_pb.BatchGetDocumentsRequest,
        ctx: RequestContext,
        /,
    ) -> neutron_pb.BatchGetDocumentsResponse:
        """Batch-retrieve clean markdown contents and highlights for a list of URLs/hashes."""
        urls = list(request.urls or [])
        raw_hashes = list(request.url_hashes or [])
        target_hashes: List[int] = []

        url_to_hash: Dict[str, int] = {}
        for u in urls:
            cleaned_u = str(u).strip()
            if cleaned_u:
                h = hash_url(cleaned_u)
                target_hashes.append(h)
                url_to_hash[cleaned_u] = h

        for rh in raw_hashes:
            try:
                target_hashes.append(int(rh))
            except (TypeError, ValueError):
                continue

        unique_hashes = list(dict.fromkeys(target_hashes))[:20]
        if not unique_hashes:
            return neutron_pb.BatchGetDocumentsResponse(documents=[])

        payloads = await turso_crawler_client.get_payloads_map(unique_hashes)
        hl_query = (request.highlight_query or "").strip()
        max_chars = int(request.max_characters or 3000)

        docs: List[neutron_pb.SearchDocument] = []
        for h in unique_hashes:
            meta = await turso_crawler_client.get_document_metadata(h)
            raw_bytes = payloads.get(h)
            full_md = decompress_text(raw_bytes) if raw_bytes else ""
            if not full_md and meta:
                full_md = str(meta.get("snippet") or "")

            if not meta and not full_md:
                continue

            truncated_md = full_md[:max_chars] if full_md else ""
            highlights = (
                extract_query_highlights(hl_query, full_md, num_highlights=2)
                if hl_query and full_md
                else []
            )

            docs.append(
                neutron_pb.SearchDocument(
                    url_hash=str(h),
                    url=str(meta.get("url") or "") if meta else "",
                    title=str(meta.get("title") or "") if meta else "",
                    snippet=str(meta.get("snippet") or "") if meta else "",
                    crawled_at=str(meta.get("crawled_at") or "") if meta else "",
                    full_markdown=truncated_md,
                    highlights=highlights,
                )
            )

        return neutron_pb.BatchGetDocumentsResponse(documents=docs)

    async def find_similar(
        self,
        request: neutron_pb.FindSimilarRequest,
        ctx: RequestContext,
        /,
    ) -> neutron_pb.FindSimilarResponse:
        """Find related documents based on seed URL topic and SimHash."""
        seed_url = (request.url or "").strip()
        limit = max(1, min(int(request.limit or 5), 20))
        hits = await turso_crawler_client.find_similar_documents(
            seed_url,
            limit=limit,
            exclude_source_domain=bool(request.exclude_source_domain),
        )
        return neutron_pb.FindSimilarResponse(
            results=[doc_to_proto(h) for h in hits]
        )

    async def suggest(
        self,
        request: neutron_pb.SuggestRequest,
        ctx: RequestContext,
        /,
    ) -> neutron_pb.SuggestResponse:
        clean_q = (request.query or "").strip()
        if len(clean_q) < 2:
            return neutron_pb.SuggestResponse(query=clean_q, suggestions=[])
        limit = max(1, min(int(request.limit or 6), 20))
        items = await turso_crawler_client.get_autocomplete_suggestions(clean_q, limit=limit)
        return neutron_pb.SuggestResponse(query=clean_q, suggestions=items)

    async def get_trending(
        self,
        request: neutron_pb.GetTrendingRequest,
        ctx: RequestContext,
        /,
    ) -> neutron_pb.GetTrendingResponse:
        limit = max(1, min(int(request.limit or 8), 25))
        rows = await turso_crawler_client.get_trending_topics(limit=limit)
        return neutron_pb.GetTrendingResponse(
            trending=[
                neutron_pb.TrendingTopic(
                    topic=str(r.get("topic") or r.get("term") or ""),
                    hits=int(r.get("hits") or r.get("count") or 0),
                )
                for r in rows
            ]
        )

    async def get_stats(
        self,
        request: neutron_pb.GetStatsRequest,
        ctx: RequestContext,
        /,
    ) -> neutron_pb.GetStatsResponse:
        stats = await turso_crawler_client.get_stats()
        return neutron_pb.GetStatsResponse(
            stats=neutron_pb.StatsSnapshot(
                pages_indexed=int(stats.get("pages_indexed") or 0),
                domains_covered=int(stats.get("domains_covered") or 0),
                frontier_pending=int(stats.get("frontier_pending") or 0),
                payloads_stored=int(stats.get("payloads_stored") or 0),
                connected=bool(stats.get("connected")),
            )
        )

    async def record_hot_topic(
        self,
        request: neutron_pb.RecordHotTopicRequest,
        ctx: RequestContext,
        /,
    ) -> neutron_pb.RecordHotTopicResponse:
        clean_q = (request.query or "").strip()
        if clean_q:
            await turso_crawler_client.record_hot_topic(clean_q)
        return neutron_pb.RecordHotTopicResponse(ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Connect and close Turso client cleanly across serverless/server lifecycle."""
    if settings.REQUIRE_INTERNAL_API_KEY and not settings.INTERNAL_API_KEY:
        raise RuntimeError("REQUIRE_INTERNAL_API_KEY is true, but INTERNAL_API_KEY is missing.")
    try:
        if turso_crawler_client.is_configured():
            await turso_crawler_client.connect()
            logger.info("search_service_turso_connected")
    except Exception as exc:
        logger.warning("search_service_turso_warning", error=str(exc))
    yield
    await turso_crawler_client.close()


app = FastAPI(
    title="Neutron Search & Synthesis Service",
    version="3.0.0",
    lifespan=lifespan,
)
configure_cors(app, settings.cors_origins_list())
configure_middleware(app)

_auth_interceptor = InternalAuthInterceptor(
    settings.INTERNAL_API_KEY,
    require_key=settings.REQUIRE_INTERNAL_API_KEY,
)
_rpc_app = neutron_connect.SearchServiceASGIApplication(
    SearchServiceImpl(),
    interceptors=[_auth_interceptor],
)
mount_connect_service(app, _rpc_app)


@app.get("/health")
@app.get("/kaithhealth")
async def health_check() -> Dict[str, Any]:
    """Health endpoint for Render/Leapcell and container readiness checks."""
    return {
        "status": "ok",
        "service": "neutron-search",
        "version": "3.0.0",
        "turso_configured": turso_crawler_client.is_configured(),
        "uptime_seconds": int(time.time() - _START_TIME),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=settings.PORT)

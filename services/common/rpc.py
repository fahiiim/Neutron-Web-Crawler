"""ConnectRPC/gRPC FastAPI mount helpers, auth interceptor, and protobuf mappers."""

from __future__ import annotations

import hmac
from typing import Any, Dict, Iterable, Optional, Tuple, TypeVar

from connectrpc.code import Code
from connectrpc.errors import ConnectError
from connectrpc.interceptor import MetadataInterceptor
from connectrpc.protocol import ProtocolType
from connectrpc.request import RequestContext
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from neutron_rpc.neutron.v1 import neutron_pb

REQ = TypeVar("REQ")
RES = TypeVar("RES")


class PrefixPreservingASGI:
    """ASGI wrapper preserving Connect service prefix when mounted in Starlette/FastAPI."""

    def __init__(self, prefix: str, app: Any) -> None:
        self._prefix = prefix.rstrip("/")
        self._app = app

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "http":
            path = str(scope.get("path") or "")
            if not path.startswith(self._prefix):
                updated = dict(scope)
                updated["path"] = f"{self._prefix}{path}"
                updated["root_path"] = ""
                scope = updated
        await self._app(scope, receive, send)


def mount_connect_service(app: FastAPI, rpc_app: Any) -> None:
    """Mount a generated ConnectASGIApplication onto FastAPI keeping CORSMiddleware active."""
    prefix = rpc_app.path.rstrip("/")
    app.mount(prefix, PrefixPreservingASGI(prefix, rpc_app))


def configure_cors(app: FastAPI, origins: Iterable[str]) -> None:
    """Configure public CORS headers compatible with GitHub Pages and Connect/gRPC-Web."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=[
            "Content-Type",
            "Connect-Protocol-Version",
            "Connect-Timeout-Ms",
            "Grpc-Status",
            "Grpc-Message",
        ],
    )


class InternalAuthInterceptor(MetadataInterceptor[None]):
    """Enforce Bearer / x-internal-key verification across unary and streaming RPCs."""

    def __init__(self, expected_key: str, *, require_key: bool = False) -> None:
        self._expected_key = (expected_key or "").strip()
        self._require_key = require_key

    async def on_start(self, ctx: RequestContext) -> None:
        if not self._expected_key:
            if self._require_key:
                raise ConnectError(
                    Code.UNAVAILABLE,
                    "Internal RPC authentication key is not configured.",
                )
            return None

        auth_header = ctx.request_headers.get("authorization") or ""
        alt_header = ctx.request_headers.get("x-internal-key") or ""
        token = ""
        if auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1].strip()
        elif alt_header:
            token = alt_header.strip()

        if not token:
            raise ConnectError(Code.UNAUTHENTICATED, "Missing internal authorization header")
        if not hmac.compare_digest(token.encode("utf-8"), self._expected_key.encode("utf-8")):
            raise ConnectError(Code.PERMISSION_DENIED, "Invalid internal API key")
        return None

    async def on_end(
        self,
        token: None,
        ctx: RequestContext,
        error: Exception | None,
        /,
    ) -> None:
        return None


def resolve_protocol(name: str) -> ProtocolType:
    """Map string setting to ConnectRPC ProtocolType."""
    clean = (name or "connect").strip().lower()
    if clean in ("grpc", "grpc_http2"):
        return ProtocolType.GRPC
    if clean in ("grpc_web", "grpc-web"):
        return ProtocolType.GRPC_WEB
    return ProtocolType.CONNECT


def internal_auth_headers(
    api_key: str, *, request_id: Optional[str] = None
) -> Dict[str, str]:
    """Build internal authorization and request-tracing headers for downstream RPCs."""
    headers: Dict[str, str] = {}
    cleaned = (api_key or "").strip()
    if cleaned:
        headers["Authorization"] = f"Bearer {cleaned}"
    clean_req_id = (request_id or "").strip()
    if clean_req_id:
        headers["x-request-id"] = clean_req_id
    return headers


def doc_to_proto(
    doc: Dict[str, Any], *, include_full_text: bool = False
) -> neutron_pb.SearchDocument:
    """Convert a search result dict into a Protobuf SearchDocument."""
    full_text = str(doc.get("_full_text") or doc.get("full_text") or "") if include_full_text else ""
    highlights = [str(h) for h in (doc.get("highlights") or []) if h]
    subpage_protos = [
        neutron_pb.SubpageDocument(
            id=str(sp.get("id") or sp.get("url_hash") or ""),
            url=str(sp.get("url") or ""),
            title=str(sp.get("title") or ""),
            text=str(sp.get("text") or sp.get("full_markdown") or sp.get("snippet") or ""),
        )
        for sp in (doc.get("subpages") or [])
        if isinstance(sp, dict) and sp.get("url")
    ]
    return neutron_pb.SearchDocument(
        url_hash=str(doc.get("url_hash") or ""),
        url=str(doc.get("url") or ""),
        title=str(doc.get("title") or ""),
        snippet=str(doc.get("snippet") or ""),
        score=float(doc.get("score") or 0.0),
        crawled_at=str(doc.get("crawled_at") or ""),
        full_markdown=str(doc.get("full_markdown") or ""),
        full_text=full_text,
        highlights=highlights,
        subpages=subpage_protos,
    )


def proto_to_doc(
    msg: neutron_pb.SearchDocument, *, include_full_text: bool = True
) -> Dict[str, Any]:
    """Convert a Protobuf SearchDocument back into a plain dict."""
    out: Dict[str, Any] = {
        "url_hash": str(msg.url_hash or ""),
        "url": str(msg.url or ""),
        "title": str(msg.title or ""),
        "snippet": str(msg.snippet or ""),
        "score": float(msg.score or 0.0),
        "crawled_at": str(msg.crawled_at or ""),
        "highlights": list(msg.highlights or []),
        "subpages": [
            {
                "id": str(sp.id or ""),
                "url": str(sp.url or ""),
                "title": str(sp.title or ""),
                "text": str(sp.text or ""),
            }
            for sp in (msg.subpages or [])
        ],
    }
    if msg.full_markdown:
        out["full_markdown"] = str(msg.full_markdown)
    if include_full_text and msg.full_text:
        out["_full_text"] = str(msg.full_text)
    return out


def evaluation_to_proto(
    eval_dict: Optional[Dict[str, Any]],
) -> Optional[neutron_pb.EvaluationMetrics]:
    """Convert an evaluation metrics dict into a Protobuf message."""
    if not eval_dict:
        return None
    return neutron_pb.EvaluationMetrics(
        confidence_score=float(eval_dict.get("confidence_score") or 0.0),
        query_coverage=float(eval_dict.get("query_coverage") or 0.0),
        grounding_faithfulness=float(eval_dict.get("grounding_faithfulness") or 0.0),
        relevance_grade=str(eval_dict.get("relevance_grade") or ""),
        matched_concepts=[str(c) for c in (eval_dict.get("matched_concepts") or [])],
        missing_concepts=[str(c) for c in (eval_dict.get("missing_concepts") or [])],
        evaluation_summary=str(eval_dict.get("evaluation_summary") or ""),
    )


def proto_to_evaluation(
    msg: Optional[neutron_pb.EvaluationMetrics],
) -> Optional[Dict[str, Any]]:
    """Convert a Protobuf EvaluationMetrics message back into a plain dict."""
    if msg is None or not (msg.confidence_score or msg.relevance_grade or msg.evaluation_summary):
        return None
    return {
        "confidence_score": round(float(msg.confidence_score), 3),
        "confidence_percent": int(round(float(msg.confidence_score) * 100)),
        "query_coverage": round(float(msg.query_coverage), 3),
        "grounding_faithfulness": round(float(msg.grounding_faithfulness), 3),
        "relevance_grade": str(msg.relevance_grade or "Moderate"),
        "matched_concepts": list(msg.matched_concepts or []),
        "missing_concepts": list(msg.missing_concepts or []),
        "evaluation_summary": str(msg.evaluation_summary or ""),
    }


def answer_to_proto(
    answer: Optional[Dict[str, Any]],
) -> Tuple[neutron_pb.GroundedAnswer, bool]:
    """Convert a synthesized grounded answer dict into Protobuf message + presence flag."""
    if not answer or not answer.get("summary"):
        return neutron_pb.GroundedAnswer(), False

    citations = [
        neutron_pb.Citation(
            index=int(c.get("index") or 0),
            url=str(c.get("url") or ""),
            url_hash=str(c.get("url_hash") or ""),
            title=str(c.get("title") or ""),
            domain=str(c.get("domain") or ""),
        )
        for c in (answer.get("citations") or [])
    ]
    eval_proto = evaluation_to_proto(answer.get("evaluation"))
    return (
        neutron_pb.GroundedAnswer(
            summary=str(answer["summary"]),
            citations=citations,
            mode=str(answer.get("mode") or "extractive_grounded"),
            evaluation=eval_proto,
        ),
        True,
    )


def proto_to_answer(
    msg: Optional[neutron_pb.GroundedAnswer], *, has_answer: bool = True
) -> Optional[Dict[str, Any]]:
    """Convert a Protobuf GroundedAnswer back into a plain dict."""
    if not has_answer or msg is None or not msg.summary:
        return None
    out: Dict[str, Any] = {
        "summary": str(msg.summary),
        "citations": [
            {
                "index": int(c.index),
                "url": str(c.url),
                "url_hash": str(c.url_hash),
                "title": str(c.title),
                "domain": str(c.domain),
            }
            for c in msg.citations
        ],
        "mode": str(msg.mode or "extractive_grounded"),
    }
    if msg.evaluation is not None and (msg.evaluation.confidence_score or msg.evaluation.relevance_grade):
        out["evaluation"] = proto_to_evaluation(msg.evaluation)
    return out


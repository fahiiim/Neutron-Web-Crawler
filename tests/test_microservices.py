"""End-to-end tests for the 3 ConnectRPC/gRPC Leapcell microservices."""

from __future__ import annotations

import os
import socket
import threading
import time
import unittest
from unittest.mock import AsyncMock, patch

from connectrpc.code import Code
from connectrpc.errors import ConnectError
from connectrpc.protocol import ProtocolType
import httpx
import uvicorn

from neutron_rpc.neutron.v1 import neutron_connect, neutron_pb
from services.crawler import app as crawler_svc_mod
from services.gateway import app as gateway_svc_mod
from services.search import app as search_svc_mod


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _LiveUvicornServer:
    """Launch an ASGI app on a loopback ephemeral port for real HTTP/ConnectRPC tests."""

    def __init__(self, asgi_app, port: int) -> None:
        self.port = port
        self._config = uvicorn.Config(
            asgi_app, host="127.0.0.1", port=port, log_level="error", http="h11"
        )
        self._server = uvicorn.Server(self._config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def __enter__(self) -> str:
        self._thread.start()
        deadline = time.monotonic() + 5.0
        while not self._server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        return f"http://127.0.0.1:{self.port}"

    def __exit__(self, *args) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=3.0)


class TestLeapcellConnectMicroservices(unittest.IsolatedAsyncioTestCase):
    """Verify Search, Crawler, and Gateway services talk cleanly over ConnectRPC & REST/SSE."""

    async def test_crawler_service_defaults_serverless_safe(self):
        self.assertFalse(crawler_svc_mod.settings.BACKGROUND_CRAWLER_ENABLED)
        self.assertEqual(crawler_svc_mod.settings.PORT, 8080)
        self.assertEqual(search_svc_mod.settings.PORT, 8080)
        self.assertEqual(gateway_svc_mod.settings.PORT, 8080)

        with patch.dict(
            os.environ,
            {"RENDER": "true", "SEARCH_SERVICE_URL": "", "CRAWLER_SERVICE_URL": ""},
            clear=False,
        ):
            cfg = gateway_svc_mod.GatewayServiceSettings(_env_file=None)
            self.assertEqual(cfg.SEARCH_SERVICE_URL, "https://neutron-search.onrender.com")
            self.assertEqual(cfg.CRAWLER_SERVICE_URL, "https://neutron-crawler.onrender.com")

        self.assertIsNotNone(gateway_svc_mod._load_tls_ca_cert())

    async def test_end_to_end_gateway_search_crawler_rpc_and_sse(self):
        secret = "test-leapcell-shared-secret"
        orig_search_key = search_svc_mod.settings.INTERNAL_API_KEY
        orig_crawler_key = crawler_svc_mod.settings.INTERNAL_API_KEY
        orig_gw_key = gateway_svc_mod.settings.INTERNAL_API_KEY
        orig_gw_search_url = gateway_svc_mod.settings.SEARCH_SERVICE_URL
        orig_gw_crawler_url = gateway_svc_mod.settings.CRAWLER_SERVICE_URL
        orig_gw_threshold = gateway_svc_mod.settings.JIT_CACHE_THRESHOLD

        # Configure mock DB + live discovery/fetch adapters so test runs offline fast
        fake_db = AsyncMock()
        fake_db.is_configured = lambda: False
        fake_db.search = AsyncMock(
            return_value=[
                {
                    "url_hash": "9001",
                    "url": "https://docs.python.org/3/library/asyncio.html",
                    "title": "asyncio — Asynchronous I/O",
                    "snippet": "asyncio is a library to write concurrent code using the async/await syntax.",
                    "score": 4.2,
                    "crawled_at": "2026-11-12 00:00:00",
                }
            ]
        )
        fake_db.get_payloads_map = AsyncMock(return_value={})
        fake_db.get_document_metadata = AsyncMock(
            return_value={
                "url": "https://docs.python.org/3/library/asyncio.html",
                "title": "asyncio — Asynchronous I/O",
                "crawled_at": "2026-11-12 00:00:00",
                "snippet": "Cached snippet",
            }
        )
        fake_db.get_document_payload = AsyncMock(return_value=None)
        fake_db.get_autocomplete_suggestions = AsyncMock(
            return_value=["asyncio python", "asyncio gather"]
        )
        fake_db.get_trending_topics = AsyncMock(
            return_value=[{"topic": "asyncio python", "hits": 5}]
        )
        fake_db.get_stats = AsyncMock(
            return_value={
                "pages_indexed": 42,
                "domains_covered": 12,
                "frontier_pending": 5,
                "payloads_stored": 40,
                "connected": True,
            }
        )
        fake_db.record_hot_topic = AsyncMock(return_value=None)

        search_svc_mod._auth_interceptor._expected_key = secret
        crawler_svc_mod._auth_interceptor._expected_key = secret
        gateway_svc_mod.settings.INTERNAL_API_KEY = secret
        gateway_svc_mod.settings.JIT_CACHE_THRESHOLD = 3

        search_port = _free_port()
        crawler_port = _free_port()
        gw_port = _free_port()

        try:
            with (
                patch.object(search_svc_mod, "turso_crawler_client", fake_db),
                patch.object(crawler_svc_mod, "turso_crawler_client", fake_db),
                patch.object(
                    crawler_svc_mod,
                    "discover_seed_urls_detailed",
                    AsyncMock(
                        return_value=(
                            ["https://example.org/crispr"],
                            [
                                {
                                    "source": "wikipedia",
                                    "urls_found": 1,
                                    "duration_ms": 15,
                                    "status": "ok",
                                }
                            ],
                        )
                    ),
                ),
                patch.object(
                    crawler_svc_mod.robots_manager,
                    "is_allowed",
                    AsyncMock(return_value=True),
                ),
                patch.object(
                    crawler_svc_mod.legacy_crawler,
                    "fetch_and_index_document",
                    AsyncMock(
                        return_value={
                            "url_hash": "9002",
                            "url": "https://example.org/crispr",
                            "title": "CRISPR Gene Editing Guide",
                            "snippet": "CRISPR uses Cas9 enzymes to edit target DNA.",
                            "score": 0.9,
                            "crawled_at": "2026-11-12 00:00:01",
                            "_full_text": "CRISPR uses RNA-guided Cas9 enzymes for targeted genome editing in cells.",
                        }
                    ),
                ),
            ):
                gateway_svc_mod.settings.SEARCH_SERVICE_URL = f"http://127.0.0.1:{search_port}"
                gateway_svc_mod.settings.CRAWLER_SERVICE_URL = f"http://127.0.0.1:{crawler_port}"

                with (
                    _LiveUvicornServer(search_svc_mod.app, search_port) as search_url,
                    _LiveUvicornServer(crawler_svc_mod.app, crawler_port) as crawler_url,
                    _LiveUvicornServer(gateway_svc_mod.app, gw_port) as gw_url,
                ):
                    async with httpx.AsyncClient(timeout=5.0) as probe:
                        for base_u in (search_url, crawler_url, gw_url):
                            kh = await probe.get(f"{base_u}/kaithhealth")
                            self.assertEqual(kh.status_code, 200)
                    # 1. Internal auth interceptor must block unauthenticated SearchService calls
                    async with neutron_connect.SearchServiceClient(search_url) as unauth_client:
                        with self.assertRaises(ConnectError) as ctx_err:
                            await unauth_client.get_stats(neutron_pb.GetStatsRequest())
                        self.assertEqual(ctx_err.exception.code, Code.UNAUTHENTICATED)

                    # 2. GatewayService ConnectRPC works with both Connect and gRPC-Web protocols
                    for proto in (ProtocolType.CONNECT, ProtocolType.GRPC_WEB):
                        async with neutron_connect.GatewayServiceClient(
                            gw_url, protocol=proto, send_compression=None
                        ) as gw_client:
                            stats_res = await gw_client.get_stats(neutron_pb.GetStatsRequest())
                            self.assertEqual(stats_res.stats.pages_indexed, 42)
                            rpc_search = await gw_client.search(
                                neutron_pb.GatewaySearchRequest(
                                    query="crispr cas9", limit=5, mode="all"
                                )
                            )
                            self.assertEqual(rpc_search.source, "hybrid_jit")
                            self.assertTrue(rpc_search.has_answer)
                            self.assertIn("CRISPR", rpc_search.answer.summary)

                    # 3. GitHub Pages CORS preflight & HTTP JSON endpoints + /doc + SSE /search/stream
                    async with httpx.AsyncClient(timeout=10.0) as http:
                        cors_resp = await http.options(
                            f"{gw_url}/search",
                            headers={
                                "Origin": "https://fahiiim.github.io",
                                "Access-Control-Request-Method": "GET",
                            },
                        )
                        self.assertEqual(cors_resp.status_code, 200)
                        self.assertIn(
                            cors_resp.headers.get("access-control-allow-origin"),
                            ("*", "https://fahiiim.github.io"),
                        )

                        search_resp = await http.get(
                            f"{gw_url}/search",
                            params={"q": "crispr cas9", "limit": 5},
                            headers={"Origin": "https://fahiiim.github.io"},
                        )
                        self.assertEqual(search_resp.status_code, 200)
                        payload = search_resp.json()
                        self.assertEqual(payload["source"], "hybrid_jit")
                        self.assertIsNotNone(payload["answer"])
                        self.assertEqual(len(payload["results"]), 2)

                        doc_resp = await http.get(f"{gw_url}/doc/9001")
                        self.assertEqual(doc_resp.status_code, 200)
                        self.assertEqual(doc_resp.json()["url_hash"], "9001")

                        suggest_resp = await http.get(f"{gw_url}/suggest", params={"q": "asyn"})
                        self.assertEqual(suggest_resp.status_code, 200)
                        self.assertIn("asyncio python", suggest_resp.json()["suggestions"])

                        stream_resp = await http.get(
                            f"{gw_url}/search/stream",
                            params={"q": "crispr cas9"},
                        )
                        self.assertEqual(stream_resp.status_code, 200)
                        raw_sse = stream_resp.text
                        self.assertIn("event: cached_results", raw_sse)
                        self.assertIn("event: live_result", raw_sse)
                        self.assertIn("event: answer", raw_sse)
                        self.assertIn("event: done", raw_sse)
        finally:
            search_svc_mod._auth_interceptor._expected_key = orig_search_key
            crawler_svc_mod._auth_interceptor._expected_key = orig_crawler_key
            gateway_svc_mod.settings.INTERNAL_API_KEY = orig_gw_key
            gateway_svc_mod.settings.SEARCH_SERVICE_URL = orig_gw_search_url
            gateway_svc_mod.settings.CRAWLER_SERVICE_URL = orig_gw_crawler_url
            gateway_svc_mod.settings.JIT_CACHE_THRESHOLD = orig_gw_threshold

    async def test_gateway_preserves_cors_when_downstream_unavailable(self):
        orig_search_url = gateway_svc_mod.settings.SEARCH_SERVICE_URL
        orig_crawler_url = gateway_svc_mod.settings.CRAWLER_SERVICE_URL
        dead_port_1 = _free_port()
        dead_port_2 = _free_port()
        gw_port = _free_port()
        try:
            gateway_svc_mod.settings.SEARCH_SERVICE_URL = f"http://127.0.0.1:{dead_port_1}"
            gateway_svc_mod.settings.CRAWLER_SERVICE_URL = f"http://127.0.0.1:{dead_port_2}"
            with _LiveUvicornServer(gateway_svc_mod.app, gw_port) as gw_url:
                async with httpx.AsyncClient(timeout=10.0) as http:
                    r = await http.get(
                        f"{gw_url}/search",
                        params={"q": "sql join"},
                        headers={"Origin": "https://fahiiim.github.io"},
                    )
                    self.assertEqual(r.status_code, 503)
                    self.assertIn(
                        r.headers.get("access-control-allow-origin"),
                        ("*", "https://fahiiim.github.io"),
                    )
                    s = await http.get(
                        f"{gw_url}/suggest",
                        params={"q": "sql"},
                        headers={"Origin": "https://fahiiim.github.io"},
                    )
                    self.assertEqual(s.status_code, 200)
                    self.assertEqual(s.json()["suggestions"], [])
        finally:
            gateway_svc_mod.settings.SEARCH_SERVICE_URL = orig_search_url
            gateway_svc_mod.settings.CRAWLER_SERVICE_URL = orig_crawler_url

    async def test_stream_crawl_ttl_cache_refresh_and_request_tracing(self):
        secret = "test-stream-trace-secret"
        orig_search_key = search_svc_mod.settings.INTERNAL_API_KEY
        orig_crawler_key = crawler_svc_mod.settings.INTERNAL_API_KEY
        orig_gw_key = gateway_svc_mod.settings.INTERNAL_API_KEY
        orig_gw_search_url = gateway_svc_mod.settings.SEARCH_SERVICE_URL
        orig_gw_crawler_url = gateway_svc_mod.settings.CRAWLER_SERVICE_URL
        orig_gw_threshold = gateway_svc_mod.settings.JIT_CACHE_THRESHOLD

        fake_db = AsyncMock()
        fake_db.is_configured = lambda: False
        fake_db.search = AsyncMock(
            return_value=[
                {
                    "url_hash": str(100 + i),
                    "url": f"https://docs.example.org/join-{i}",
                    "title": f"SQL JOIN Part {i}",
                    "snippet": "Joins combine rows from related tables using common columns.",
                    "score": 5.0 - i,
                    "crawled_at": "2026-11-12 00:00:00",
                }
                for i in range(5)
            ]
        )
        fake_db.get_payloads_map = AsyncMock(return_value={})
        fake_db.record_hot_topic = AsyncMock(return_value=None)

        search_svc_mod._auth_interceptor._expected_key = secret
        crawler_svc_mod._auth_interceptor._expected_key = secret
        gateway_svc_mod.settings.INTERNAL_API_KEY = secret
        gateway_svc_mod.settings.JIT_CACHE_THRESHOLD = 5

        search_port = _free_port()
        crawler_port = _free_port()
        gw_port = _free_port()

        try:
            with (
                patch.object(search_svc_mod, "turso_crawler_client", fake_db),
                patch.object(crawler_svc_mod, "turso_crawler_client", fake_db),
                patch.object(
                    crawler_svc_mod,
                    "discover_seed_urls_detailed",
                    AsyncMock(
                        return_value=(
                            ["https://example.org/sql-joins"],
                            [{"source": "wikipedia", "urls_found": 1, "duration_ms": 10, "status": "ok"}],
                        )
                    ),
                ),
                patch.object(
                    crawler_svc_mod.robots_manager,
                    "is_allowed",
                    AsyncMock(return_value=True),
                ),
                patch.object(
                    crawler_svc_mod.legacy_crawler,
                    "fetch_and_index_document",
                    AsyncMock(
                        return_value={
                            "url_hash": "8801",
                            "url": "https://example.org/sql-joins",
                            "title": "SQL Join Guide",
                            "snippet": "JOIN combines rows across relational database tables.",
                            "score": 2.0,
                            "crawled_at": "2026-11-12 00:00:00",
                            "_full_text": "JOIN combines rows across relational database tables cleanly.",
                        }
                    ),
                ),
            ):
                with (
                    _LiveUvicornServer(search_svc_mod.app, search_port) as search_url,
                    _LiveUvicornServer(crawler_svc_mod.app, crawler_port) as crawler_url,
                ):
                    gateway_svc_mod.settings.SEARCH_SERVICE_URL = search_url
                    gateway_svc_mod.settings.CRAWLER_SERVICE_URL = crawler_url

                    # Verify StreamCrawl server-streaming RPC enforces auth & streams events
                    async with neutron_connect.CrawlerServiceClient(
                        crawler_url, protocol=ProtocolType.CONNECT
                    ) as c_client:
                        with self.assertRaises(ConnectError) as unauth_ctx:
                            async for _ in c_client.stream_crawl(
                                neutron_pb.StreamCrawlRequest(query="sql join", max_pages=3)
                            ):
                                pass
                        self.assertEqual(unauth_ctx.exception.code, Code.UNAUTHENTICATED)

                        streamed_types = []
                        async for evt in c_client.stream_crawl(
                            neutron_pb.StreamCrawlRequest(query="sql join", max_pages=3),
                            headers={"Authorization": f"Bearer {secret}"},
                        ):
                            streamed_types.append(evt.event_type)
                        self.assertIn("discovery_result", streamed_types)
                        self.assertIn("crawl_success", streamed_types)

                    with _LiveUvicornServer(gateway_svc_mod.app, gw_port) as gw_url:
                        async with httpx.AsyncClient(timeout=10.0) as http:
                            r1 = await http.get(
                                f"{gw_url}/search",
                                params={"q": "sql join"},
                                headers={"x-request-id": "trace-abc-123"},
                            )
                            self.assertEqual(r1.status_code, 200)
                            self.assertEqual(r1.headers.get("x-request-id"), "trace-abc-123")
                            d1 = r1.json()
                            self.assertFalse(d1["cache_hit"])
                            self.assertIn("timings", d1)
                            calls_after_r1 = fake_db.search.await_count

                            # Repeat call hits Gateway TTLCache without calling SearchService
                            r2 = await http.get(f"{gw_url}/search", params={"q": "sql join"})
                            self.assertEqual(r2.status_code, 200)
                            self.assertTrue(r2.json()["cache_hit"])
                            self.assertEqual(fake_db.search.await_count, calls_after_r1)

                            # refresh=true bypasses Gateway TTLCache
                            r3 = await http.get(
                                f"{gw_url}/search",
                                params={"q": "sql join", "refresh": "true"},
                            )
                            self.assertEqual(r3.status_code, 200)
                            self.assertFalse(r3.json()["cache_hit"])
                            self.assertGreater(fake_db.search.await_count, calls_after_r1)
        finally:
            search_svc_mod._auth_interceptor._expected_key = orig_search_key
            crawler_svc_mod._auth_interceptor._expected_key = orig_crawler_key
            gateway_svc_mod.settings.INTERNAL_API_KEY = orig_gw_key
            gateway_svc_mod.settings.SEARCH_SERVICE_URL = orig_gw_search_url
            gateway_svc_mod.settings.CRAWLER_SERVICE_URL = orig_gw_crawler_url
            gateway_svc_mod.settings.JIT_CACHE_THRESHOLD = orig_gw_threshold


if __name__ == "__main__":
    unittest.main()

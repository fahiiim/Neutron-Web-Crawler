"""Comprehensive unit and integration test suite for Neutron Web Crawler v3.0."""

import gzip
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from scripts.init_turso import split_sql_statements
from spaces.crawler import app as crawler_app_module
from spaces.crawler.bloom import URLBloomFilter
from spaces.crawler.compression import compress_text, decompress_text
from spaces.crawler.config import CrawlerSettings
from spaces.crawler.db_turso import TursoCrawlerClient, sanitize_fts_terms
from spaces.crawler.dedup import (
    canonicalize_url,
    compute_simhash,
    extract_domain_host,
    hamming_distance,
    hash_domain,
    hash_url,
)
from spaces.crawler.discovery import _strip_question_framing, discover_seed_urls_detailed
from spaces.crawler.parser import (
    extract_outbound_links,
    is_waf_or_empty_page,
    parse_page_content,
)
from spaces.crawler.robots import RobotsTxtManager
from spaces.crawler.sitemap import discover_sitemap_urls
from spaces.crawler.synthesis import (
    extract_query_focused_snippet,
    synthesize_grounded_answer,
)
from spaces.gateway import app as gateway_app_module
from spaces.gateway.config import GatewaySettings

try:
    from selectolax.lexbor import LexborHTMLParser as HTMLParser
except ImportError:
    from selectolax.parser import HTMLParser


class TestDedupAndCompression(unittest.TestCase):
    """Tests for URL normalization, hashing, SimHash, Bloom filter, and Zstd."""

    def test_canonicalize_url_strips_tracking_and_fragments(self):
        raw = "https://example.com/blog/article/?utm_source=twitter&msclkid=123&ref=nl#comments"
        self.assertEqual(canonicalize_url(raw), "https://example.com/blog/article")

    def test_canonicalize_url_normalizes_ports_and_percent_encoding(self):
        raw = "http://EXAMPLE.COM:80/user/%7Ealice/"
        self.assertEqual(canonicalize_url(raw), "http://example.com/user/~alice")

    def test_canonicalize_url_optional_strip_www(self):
        raw = "https://www.example.com/docs/"
        self.assertEqual(canonicalize_url(raw, strip_www=False), "https://www.example.com/docs")
        self.assertEqual(canonicalize_url(raw, strip_www=True), "https://example.com/docs")

    def test_canonicalize_url_rejects_non_http(self):
        self.assertEqual(canonicalize_url("javascript:alert(1)"), "")
        self.assertEqual(canonicalize_url("mailto:test@example.com"), "")

    def test_extract_domain_host_strips_www_and_port(self):
        self.assertEqual(extract_domain_host("https://www.News.Example.com:8443/a"), "news.example.com")
        self.assertEqual(hash_domain("www.example.com"), hash_domain("example.com"))

    def test_hash_url_is_signed_64bit(self):
        h = hash_url("https://en.wikipedia.org/wiki/Neutron_star")
        self.assertIsInstance(h, int)
        self.assertGreaterEqual(h, -(1 << 63))
        self.assertLess(h, (1 << 63))

    def test_zstd_compression_roundtrip_and_invalid_bytes(self):
        original = "# Neutron Star\n\nHigh-density pulsar magnetosphere observations."
        compressed = compress_text(original)
        self.assertIsInstance(compressed, bytes)
        self.assertEqual(decompress_text(compressed), original)
        self.assertEqual(decompress_text(b""), "")
        self.assertEqual(decompress_text(b"not-valid-zstd"), "")

    def test_simhash_and_hamming_distance(self):
        text_a = "High performance web crawler with asynchronous IO and parallel fetching across domains."
        text_b = "High performance web crawler with asynchronous IO and concurrent fetching across domains."
        text_c = "Chocolate cake baking instructions with butter, flour, vanilla extract, and sugar."
        h_a = compute_simhash(text_a)
        h_b = compute_simhash(text_b)
        h_c = compute_simhash(text_c)
        self.assertLess(hamming_distance(h_a, h_b), hamming_distance(h_a, h_c))
        self.assertEqual(hamming_distance(-1, -1), 0)
        self.assertEqual(hamming_distance(0, -1), 64)

    def test_bloom_filter_operations(self):
        bloom = URLBloomFilter(capacity=5000, fp_rate=0.001)
        bloom.add("https://www.example.com/page-1/")
        self.assertTrue(bloom.might_contain("https://example.com/page-1"))
        self.assertFalse(bloom.might_contain("https://example.com/never-seen"))
        self.assertEqual(len(bloom), 1)
        bloom.add_many(["https://a.test/1", "https://b.test/2"])
        self.assertEqual(len(bloom), 3)
        bloom.clear()
        self.assertFalse(bloom.might_contain("https://example.com/page-1"))
        self.assertEqual(len(bloom), 0)


class TestParserAndSecurity(unittest.TestCase):
    """Tests for HTML/SSR/JSON-LD parsing, link filtering, SQL split, and config security."""

    def test_parse_markdown_and_main_article_focus(self):
        html = """
        <html lang="en">
        <head>
            <title>Pulsar Physics</title>
            <meta name="description" content="Rotating magnetized neutron star beams.">
            <script type="application/ld+json">
                {"@type": "Article", "author": {"name": "Dr. Vera Rubin"}, "datePublished": "2026-11-01"}
            </script>
        </head>
        <body>
            <nav><a href="/home">Home navigation menu text that should be decomposed</a></nav>
            <article>
                <h1>Understanding Neutron Stars</h1>
                <p>A neutron star is the collapsed core of a massive supergiant star with extreme density.</p>
                <h2>Magnetic Fields</h2>
                <ul><li>Dipole field lines radiate from magnetic poles at relativistic velocities.</li></ul>
                <blockquote>Pulsars act as cosmic lighthouses sweeping beams across space.</blockquote>
                <pre>spin_rate = 716  # Hz</pre>
            </article>
            <footer>Copyright footer noise that should be skipped entirely.</footer>
        </body>
        </html>
        """
        parsed = parse_page_content(html, "https://astro.example.org/pulsars")
        self.assertEqual(parsed["title"], "Pulsar Physics")
        self.assertEqual(parsed["language"], "en")
        self.assertEqual(parsed["author"], "Dr. Vera Rubin")
        self.assertEqual(parsed["published_at"], "2026-11-01")
        self.assertFalse(parsed["is_spa_empty"])
        self.assertIn("# Understanding Neutron Stars", parsed["text"])
        self.assertIn("## Magnetic Fields", parsed["text"])
        self.assertIn("> Pulsars act as cosmic lighthouses", parsed["text"])
        self.assertNotIn("Copyright footer noise", parsed["text"])

    def test_parse_next_data_ssr_and_spa_empty(self):
        ssr_html = """
        <html><body>
        <script id="__NEXT_DATA__" type="application/json">
        {"props":{"pageProps":{"title":"Next SSR Doc","description":"Instant server state extraction"}}}
        </script>
        </body></html>
        """
        ssr_parsed = parse_page_content(ssr_html, "https://nextjs.example.com/post")
        self.assertEqual(ssr_parsed["title"], "Next SSR Doc")
        self.assertFalse(ssr_parsed["is_spa_empty"])

        spa_html = '<html><head><title>App</title></head><body><div id="__next"></div></body></html>'
        spa_parsed = parse_page_content(spa_html, "https://spa.example.com")
        self.assertTrue(spa_parsed["is_spa_empty"])

    def test_extract_outbound_links_respects_nofollow_and_keeps_noopener(self):
        html = """
        <html><body>
            <a href="https://good.example.com/guide" rel="noopener noreferrer">Follow Me</a>
            <a href="https://spam.example.com/ad" rel="nofollow">Skip Nofollow</a>
            <a href="https://promo.example.com/deal" rel="sponsored">Skip Sponsored</a>
            <a href="https://forum.example.com/c" rel="ugc">Skip UGC</a>
            <a href="/assets/logo.png">Skip Image</a>
            <a href="#section">Skip Anchor</a>
        </body></html>
        """
        tree = HTMLParser(html)
        links = extract_outbound_links(tree, "https://origin.example.com/index.html")
        urls = [item["url"] for item in links]
        self.assertEqual(urls, ["https://good.example.com/guide"])

    def test_fts_query_sanitization(self):
        self.assertEqual(
            sanitize_fts_terms('quantum "computing"* OR NOT NEAR -- test!'),
            ["quantum", "computing", "test"],
        )
        self.assertEqual(
            sanitize_fts_terms("what is the name of elit us army force"),
            ["elit", "us", "army", "force"],
        )
        self.assertEqual(
            sanitize_fts_terms("how does crispr gene editing work"),
            ["crispr", "gene", "editing"],
        )
        self.assertEqual(
            sanitize_fts_terms("what to do to make me safe from being volcanized"),
            ["safe", "volcanized"],
        )
        self.assertEqual(
            sanitize_fts_terms("domain name system"),
            ["domain", "name", "system"],
        )
        self.assertEqual(sanitize_fts_terms("   ???   "), [])

    def test_wikipedia_nav_and_lead_prose_snippet(self):
        wiki_html = """
        <html><head><title>J. K. Rowling - Wikipedia</title></head>
        <body>
            <a class="mw-jump-link" href="#bodyContent">Jump to content</a>
            <main>
                <div id="p-lang-btn"><ul><li>Arabiya</li><li>Deutsch</li></ul></div>
                <div id="mw-content-text"><div class="mw-parser-output">
                    <h1>J. K. Rowling</h1>
                    <ul><li>Born 31 July 1965</li></ul>
                    <p>Joanne Rowling, known by her pen name J. K. Rowling, is a British author who wrote the Harry Potter fantasy series.</p>
                </div></div>
            </main>
        </body></html>
        """
        parsed = parse_page_content(wiki_html, "https://en.wikipedia.org/wiki/J._K._Rowling")
        self.assertNotIn("Jump to content", parsed["snippet"])
        self.assertNotIn("Deutsch", parsed["text"])
        self.assertIn("Harry Potter fantasy series", parsed["snippet"])

    def test_waf_interstitial_detection_and_h1_title_fallback(self):
        self.assertTrue(
            is_waf_or_empty_page(
                "Just a moment...",
                "Performing security verification. Enable JavaScript and cookies to continue.",
            )
        )
        self.assertTrue(
            is_waf_or_empty_page(
                "Access Denied",
                "You don't have permission to access this resource on this server.",
            )
        )
        self.assertTrue(is_waf_or_empty_page("Untitled Document", "Too short"))
        self.assertFalse(
            is_waf_or_empty_page(
                "How Cloudflare Workers Handle HTTP 403 Edges",
                "Cloudflare Workers run V8 isolates at network edge locations. " * 10,
            )
        )

        no_title_html = (
            "<html><body><main><h1>Fallback Heading Title</h1>"
            "<p>Substantial article body paragraph discussing distributed systems in detail.</p>"
            "</main></body></html>"
        )
        parsed = parse_page_content(no_title_html, "https://docs.example.org/h1")
        self.assertEqual(parsed["title"], "Fallback Heading Title")
        self.assertFalse(parsed["is_waf_blocked"])

    def test_waf_domain_cooldown_and_vertical_mode_filtering(self):
        async def _run():
            seen_urls_called = []

            async def fake_get(url, **kwargs):
                seen_urls_called.append(url)
                resp = MagicMock()
                resp.status_code = 200
                resp.headers = {}
                if "export.arxiv.org" in url:
                    resp.text = (
                        "<feed xmlns='http://www.w3.org/2005/Atom'>"
                        "<entry><id>https://arxiv.org/abs/2611.9999</id></entry></feed>"
                    )
                elif "wikipedia.org" in url:
                    resp.json = lambda: {"query": {"search": []}}
                else:
                    resp.text = '<a href="/l/?uddg=https%3A%2F%2Fblocked.example%2Fpaper">Blocked</a>'
                return resp

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=fake_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)

            with patch("spaces.crawler.discovery.httpx.AsyncClient", return_value=mock_client):
                urls, metrics = await discover_seed_urls_detailed(
                    "quantum paper",
                    max_urls=8,
                    mode="papers",
                    skip_domains={"blocked.example"},
                )

            sources = {m["source"] for m in metrics}
            self.assertEqual(sources, {"arxiv", "wikipedia", "duckduckgo"})
            self.assertEqual(urls, ["https://arxiv.org/abs/2611.9999"])
            self.assertFalse(any("api.github.com" in u or "reddit.com" in u for u in seen_urls_called))

        import asyncio
        asyncio.run(_run())

    def test_synthesis_and_focused_excerpt(self):
        long_text = (
            "Introduction to modern software engineering practices and server setup. "
            "Many web frameworks handle routing efficiently across workers. "
            "FastAPI middleware intercepts every incoming HTTP request before your path operation runs, enabling custom logging and security headers. "
            "This concludes our overview."
        )
        excerpt = extract_query_focused_snippet("fastapi middleware logging", long_text, max_len=160)
        self.assertIn("FastAPI middleware intercepts", excerpt)

        docs = [
            {
                "url_hash": "101",
                "url": "https://en.wikipedia.org/wiki/J._K._Rowling",
                "title": "J. K. Rowling - Wikipedia",
                "full_text": "Joanne Rowling, known as J. K. Rowling, is a British author who wrote the Harry Potter fantasy series.",
            },
            {
                "url_hash": "102",
                "url": "https://www.britannica.com/biography/J-K-Rowling",
                "title": "J.K. Rowling | Britannica",
                "full_text": "J.K. Rowling created the boy wizard Harry Potter and published seven novels between 1997 and 2007.",
            },
        ]
        ans = synthesize_grounded_answer("Who wrote Harry Potter?", docs)
        self.assertIsNotNone(ans)
        self.assertIn("[1]", ans["summary"])
        self.assertIn("Joanne Rowling", ans["summary"])
        self.assertEqual(ans["citations"][0]["url_hash"], "101")

        noisy_docs = [
            {
                "url_hash": "201",
                "url": "https://www.thoughtco.com/j-k-rowling-biography",
                "title": "J.K. Rowling Biography",
                "full_text": (
                    "Author of the Harry Potter Series Evan Agostini/Getty Images "
                    "Joanne Rowling wrote the Harry Potter fantasy series [9] [10]. "
                    "Her Harry Potter books became a global phenomenon [citation needed]."
                ),
            },
            {
                "url_hash": "202",
                "url": "https://en.wikipedia.org/wiki/CRISPR",
                "title": "CRISPR - Wikipedia",
                "full_text": (
                    "CRISPR (/ ˈ k r ɪ s p ə r /; (an acronym for clustered regularly interspaced short palindromic repeats) "
                    "is a family of DNA sequences found in the genomes of prokaryotic organisms [1][2]. "
                    "View image online (https://example.org/img.png)"
                ),
            },
        ]
        snippet_clean = extract_query_focused_snippet("joanne rowling", noisy_docs[0]["full_text"], max_len=240)
        self.assertNotIn("Getty Images", snippet_clean)
        self.assertNotIn("[9]", snippet_clean)
        self.assertIn("Joanne Rowling", snippet_clean)

        hp_clean = synthesize_grounded_answer("who wrote harry potter", noisy_docs[:1])
        self.assertIsNotNone(hp_clean)
        self.assertNotIn("Getty Images", hp_clean["summary"])
        self.assertNotIn("[9]", hp_clean["summary"])
        self.assertNotIn("citation needed", hp_clean["summary"])
        self.assertIn("Joanne Rowling", hp_clean["summary"])

        crispr_clean = synthesize_grounded_answer("how does crispr work", noisy_docs[1:])
        self.assertIsNotNone(crispr_clean)
        self.assertNotIn("ˈ k r ɪ s p ə r", crispr_clean["summary"])
        self.assertNotIn("((", crispr_clean["summary"])
        self.assertNotIn("View image online", crispr_clean["summary"])
        self.assertNotIn("[2]", crispr_clean["summary"])
        self.assertIn("CRISPR (an acronym", crispr_clean["summary"])

    def test_config_rejects_hardcoded_placeholder_keys(self):
        with self.assertRaises(ValidationError):
            CrawlerSettings(INTERNAL_API_KEY="neutron-secret-internal-key")
        with self.assertRaises(ValidationError):
            GatewaySettings(INTERNAL_API_KEY="change_me_to_a_random_secret")

    def test_strip_question_framing(self):
        self.assertEqual(_strip_question_framing("What is the name of neutron star"), "neutron star")
        self.assertEqual(_strip_question_framing("How to build a crawler"), "build a crawler")
        self.assertEqual(_strip_question_framing("How does CRISPR gene editing work?"), "CRISPR gene editing")

    def test_compute_opic_authority_ranges(self):
        low = crawler_app_module.compute_opic_authority("http://random.site/a/b/c/d", {"text": "short"})
        high = crawler_app_module.compute_opic_authority(
            "https://arxiv.org/abs/2611.0001",
            {"text": "x" * 2000, "author": "Alice", "published_at": "2026-11-01"},
        )
        self.assertGreater(high, low)
        self.assertGreaterEqual(low, 0.1)
        self.assertLessEqual(high, 0.95)

    def test_sql_migration_splitter_preserves_triggers(self):
        sample = """
        CREATE TABLE t (id INTEGER PRIMARY KEY);
        CREATE TRIGGER tr AFTER INSERT ON t BEGIN
          INSERT INTO log(val) VALUES (new.id);
        END;
        CREATE INDEX idx ON t (id);
        """
        stmts = split_sql_statements(sample)
        self.assertEqual(len(stmts), 3)
        self.assertIn("END;", stmts[1])


class TestAsyncCrawlerModules(unittest.IsolatedAsyncioTestCase):
    """Async tests for robots, sitemap, discovery, retry, and Turso DB integration."""

    async def test_robots_manager_allows_disallows_and_float_delay(self):
        manager = RobotsTxtManager()
        robots_body = (
            "User-agent: *\n"
            "Crawl-delay: 2.5\n"
            "Disallow: /private/\n"
            "Sitemap: https://example.org/sitemap.xml\n"
        )
        mock_resp = MagicMock(status_code=200, text=robots_body)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("spaces.crawler.robots.httpx.AsyncClient", return_value=mock_client):
            self.assertTrue(await manager.is_allowed("https://example.org/public/post"))
            self.assertFalse(await manager.is_allowed("https://example.org/private/secret"))
            self.assertEqual(await manager.get_crawl_delay("https://example.org/"), 2.5)
            self.assertEqual(
                await manager.get_sitemaps("https://example.org/"),
                ["https://example.org/sitemap.xml"],
            )

    async def test_robots_manager_403_disallows_all(self):
        manager = RobotsTxtManager()
        mock_resp = MagicMock(status_code=403, text="Forbidden")
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("spaces.crawler.robots.httpx.AsyncClient", return_value=mock_client):
            self.assertFalse(await manager.is_allowed("https://locked.example.org/page"))

    async def test_sitemap_index_and_gzip_parsing(self):
        index_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<sitemap><loc>https://docs.example.org/child.xml.gz</loc></sitemap>"
            "</sitemapindex>"
        ).encode("utf-8")
        child_xml = gzip.compress(
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                "<url><loc>https://docs.example.org/guide/?utm_source=map</loc></url>"
                "<url><loc>https://docs.example.org/banner.png</loc></url>"
                "</urlset>"
            ).encode("utf-8")
        )

        async def fake_get(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            if url.endswith("sitemap.xml"):
                resp.content = index_xml
                resp.headers = {"content-type": "application/xml"}
            else:
                resp.content = child_xml
                resp.headers = {"content-type": "application/x-gzip"}
            return resp

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=fake_get)
        discovered = await discover_sitemap_urls(mock_client, "docs.example.org", max_urls=10)
        self.assertEqual(discovered, ["https://docs.example.org/guide"])

    async def test_fetch_with_retry_recovers_after_503(self):
        resp_503 = MagicMock(status_code=503)
        resp_200 = MagicMock(status_code=200, text="<html>ok</html>")
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(side_effect=[resp_503, resp_200])

        with patch("spaces.crawler.app.asyncio.sleep", AsyncMock()):
            result = await crawler_app_module.fetch_with_retry(
                mock_session, "https://retry.example.org", max_retries=3
            )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(mock_session.get.await_count, 2)

    async def test_fetch_and_index_skips_simhash_near_duplicate(self):
        html = (
            "<html><head><title>Clone</title></head><body><article>"
            "<h1>Neutron Star</h1><p>Extreme density spinning pulsar object in deep space.</p>"
            "</article></body></html>"
        )
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(
            return_value=MagicMock(
                status_code=200,
                headers={"content-type": "text/html; charset=utf-8"},
                text=html,
            )
        )
        with patch.object(crawler_app_module.robots_manager, "is_allowed", AsyncMock(return_value=True)), \
             patch.object(crawler_app_module.turso_crawler_client, "is_near_duplicate", AsyncMock(return_value=True)), \
             patch.object(crawler_app_module.turso_crawler_client, "insert_search_index", AsyncMock()) as mock_insert:
            doc = await crawler_app_module.fetch_and_index_document(
                mock_session, "https://dup.example.org/clone", check_robots=True
            )
        self.assertIsNone(doc)
        mock_insert.assert_not_awaited()

    async def test_fetch_and_index_skips_waf_interstitial(self):
        waf_html = (
            "<html><head><title>Just a moment...</title></head><body>"
            "<p>Performing security verification. Enable JavaScript and cookies to continue.</p>"
            "</body></html>"
        )
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(
            return_value=MagicMock(
                status_code=200,
                headers={"content-type": "text/html"},
                text=waf_html,
            )
        )
        with patch.object(crawler_app_module.settings, "RENDERER_SERVICE_URL", ""), \
             patch.object(crawler_app_module.turso_crawler_client, "insert_search_index", AsyncMock()) as mock_insert:
            doc = await crawler_app_module.fetch_and_index_document(
                mock_session, "https://waf.example.org/blocked", check_robots=False
            )
        self.assertIsNone(doc)
        mock_insert.assert_not_awaited()

    async def test_fetch_and_index_skips_off_topic_live_query_hit(self):
        unrelated_html = (
            "<html><head><title>Tutorials for GitHub Copilot</title></head><body><article>"
            "<p>Learn how to write prompts and autocomplete workflows inside Visual Studio Code extensions.</p>"
            "</article></body></html>"
        )
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(
            return_value=MagicMock(
                status_code=200,
                headers={"content-type": "text/html"},
                text=unrelated_html,
            )
        )
        with patch.object(crawler_app_module.turso_crawler_client, "insert_search_index", AsyncMock()) as mock_insert:
            doc = await crawler_app_module.fetch_and_index_document(
                mock_session,
                "https://docs.example.org/copilot",
                check_robots=False,
                query="how does crispr gene editing work",
            )
        self.assertIsNone(doc)
        mock_insert.assert_not_awaited()

    async def test_fetch_and_index_skips_bloom_seen_when_enabled(self):
        test_url = "https://seen.example.org/article"
        crawler_app_module.url_bloom.add(test_url)
        mock_session = AsyncMock()
        doc = await crawler_app_module.fetch_and_index_document(
            mock_session, test_url, check_robots=False, skip_if_seen=True
        )
        self.assertIsNone(doc)
        mock_session.get.assert_not_called()
        crawler_app_module.url_bloom.clear()

    async def test_discovery_multi_source_domain_diversity(self):
        async def fake_get(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {}
            if "duckduckgo.com" in url:
                resp.text = (
                    '<a href="/l/?uddg=https%3A%2F%2Fwww.rust-lang.org%2F">Rust</a>'
                    '<a href="/l/?uddg=https%3A%2F%2Frust-lang.org%2Flearn">Rust Learn</a>'
                    '<a href="/l/?uddg=https%3A%2F%2Ffiles.example.org%2Fpaper.pdf">PDF</a>'
                )
            elif "wikipedia.org" in url:
                resp.json = lambda: {"query": {"search": [{"title": "Rust (programming language)"}]}}
            elif "hn.algolia.com" in url:
                resp.json = lambda: {"hits": [{"url": "https://blog.rust.dev/async"}]}
            elif "reddit.com" in url:
                resp.json = lambda: {"data": {"children": []}}
            elif "arxiv.org" in url:
                resp.text = "<feed xmlns='http://www.w3.org/2005/Atom'></feed>"
            elif "api.github.com" in url:
                resp.json = lambda: {"items": [{"html_url": "https://github.com/rust-lang/rust"}]}
            return resp

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=fake_get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        seen_events = []

        async def on_src(metric):
            seen_events.append(metric["source"])

        with patch("spaces.crawler.discovery.httpx.AsyncClient", return_value=mock_client):
            urls, metrics = await discover_seed_urls_detailed(
                "rust language", max_urls=10, on_source_complete=on_src
            )

        self.assertGreaterEqual(len(metrics), 6)
        self.assertEqual(len(seen_events), len(metrics))
        rust_count = sum(1 for u in urls if "rust-lang.org" in u)
        self.assertEqual(rust_count, 1)
        self.assertFalse(any(u.endswith(".pdf") for u in urls))
        self.assertIn("https://en.wikipedia.org/wiki/Rust_(programming_language)", urls)

    async def test_turso_sqlite_end_to_end_database_operations(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        file_uri = f"file:///{db_path.replace(os.sep, '/')}"

        try:
            client = TursoCrawlerClient()
            schema_path = os.path.join(
                os.path.dirname(__file__), "..", "migrations", "03_turso_fts5_schema.sql"
            )
            from spaces.crawler import db_turso as db_mod
            with patch.object(db_mod.settings, "TURSO_DATABASE_URL", file_uri), \
                 patch.object(db_mod.settings, "TURSO_AUTH_TOKEN", "local-test-token"):
                await client.connect()
                await client._client.execute("PRAGMA foreign_keys = ON;")
                with open(schema_path, "r", encoding="utf-8") as f:
                    for stmt in split_sql_statements(f.read()):
                        await client._client.execute(stmt)

                doc_text = "# Neutron Pulsar\n\nFast asynchronous Rust crawler indexing open web articles."
                u_url = "https://astro.test/pulsar"
                u_hash = hash_url(u_url)
                d_hash = hash_domain("astro.test")
                sh = compute_simhash(doc_text)

                ok = await client.insert_search_index(
                    url_hash=u_hash,
                    domain_hash=d_hash,
                    canonical_url=u_url,
                    title="Neutron Pulsar Guide",
                    snippet="Fast asynchronous Rust crawler",
                    opic_authority=0.75,
                    simhash=sh,
                    compressed_text=compress_text(doc_text),
                )
                self.assertTrue(ok)

                hits = await client.search("pulsar crawler", limit=5)
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0]["url"], u_url)
                self.assertEqual(hits[0]["url_hash"], str(u_hash))
                self.assertIsNotNone(hits[0]["crawled_at"])

                # Multi-word search must NOT return irrelevant 1-word matches (e.g., "fastapi" missing)
                self.assertEqual(
                    await client.search("fastapi middleware crawler", limit=5),
                    [],
                )
                # Two-word search must NOT dilute to single-word hits
                self.assertEqual(
                    await client.search("quantum crawler", limit=5),
                    [],
                )
                # 3-of-4 quorum matches genuinely overlapping 4-term concepts (1 word missing/typo)
                self.assertEqual(
                    len(await client.search("neutron pulsar rust guidebook", limit=5)),
                    1,
                )

                payload = await client.get_document_payload(u_hash)
                self.assertEqual(decompress_text(payload), doc_text)
                meta = await client.get_document_metadata(u_hash)
                self.assertEqual(meta["title"], "Neutron Pulsar Guide")
                self.assertEqual(meta["url_hash"], str(u_hash))

                self.assertFalse(
                    await client.is_near_duplicate(sh, d_hash, threshold=3, exclude_url_hash=u_hash)
                )
                self.assertTrue(
                    await client.is_near_duplicate(sh, d_hash, threshold=3, exclude_url_hash=u_hash + 1)
                )

                # Unseen domain should auto-seed domains table to satisfy FK constraint
                fq_url = "https://unseen.example.net/next"
                fq_domain_hash = hash_domain("unseen.example.net")
                enqueued = await client.enqueue_frontier_urls(
                    [
                        {
                            "url_hash": hash_url(fq_url),
                            "domain_hash": fq_domain_hash,
                            "url": fq_url,
                            "priority": 0.9,
                        }
                    ]
                )
                self.assertEqual(enqueued, 1)

                leased = await client.lease_next_frontier_url()
                self.assertIsNotNone(leased)
                self.assertEqual(leased["url"], fq_url)
                self.assertIsNone(await client.lease_next_frontier_url())

                await client.update_frontier_status(leased["url_hash"], 2)

                # Test expired lease recovery
                stale_url = "https://astro.test/stale"
                stale_hash = hash_url(stale_url)
                await client._client.execute(
                    """
                    INSERT INTO frontier_queue (url_hash, domain_hash, url, priority_score, status, lease_expires_at)
                    VALUES (?, ?, ?, 0.8, 1, DATETIME('now', '-10 minutes'));
                    """,
                    [stale_hash, d_hash, stale_url],
                )
                await client.recover_expired_leases()
                recovered = await client.lease_next_frontier_url()
                self.assertIsNotNone(recovered)
                self.assertEqual(recovered["url"], stale_url)

                await client.record_hot_topic("neutron pulsar")
                trending = await client.get_trending_topics()
                self.assertEqual(trending[0]["term"], "neutron pulsar")
                suggestions = await client.get_autocomplete_suggestions("neut")
                self.assertIn("neutron pulsar", suggestions)
                stats = await client.get_stats()
                self.assertEqual(stats["pages_indexed"], 1)
                self.assertEqual(stats["payloads_stored"], 1)

                indexed_urls = await client.get_indexed_urls(limit=10)
                self.assertEqual(indexed_urls, [u_url])

                await client.close()
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)


class TestFastAPIEndpoints(unittest.TestCase):
    """Integration tests for FastAPI routes, SSE streaming, gateway, and internal auth."""

    def test_public_endpoints_and_security_headers(self):
        with TestClient(crawler_app_module.app) as client:
            health = client.get("/health")
            self.assertEqual(health.status_code, 200)
            self.assertEqual(health.json()["status"], "ok")
            self.assertEqual(health.headers.get("X-Content-Type-Options"), "nosniff")
            self.assertEqual(health.headers.get("Referrer-Policy"), "no-referrer")

            home = client.get("/")
            self.assertEqual(home.status_code, 200)
            self.assertIn("no-store", home.headers.get("Cache-Control", ""))
            self.assertIn('<div id="root"></div>', home.text)
            self.assertIn('/ui-assets/', home.text)
            import re
            asset_match = re.search(r'(/ui-assets/[^"\']+\.js)', home.text)
            self.assertIsNotNone(asset_match)
            js_resp = client.get(asset_match.group(1))
            self.assertEqual(js_resp.status_code, 200)

            privacy = client.get("/privacy")
            self.assertEqual(privacy.status_code, 200)
            self.assertIn("Zero Tracking", privacy.text)

            trending = client.get("/trending")
            self.assertEqual(trending.status_code, 200)

            stats = client.get("/stats")
            self.assertEqual(stats.status_code, 200)
            self.assertIn("pages_indexed", stats.json())

            bad_doc = client.get(f"/doc/{1 << 64}")
            self.assertEqual(bad_doc.status_code, 400)

    def test_gateway_health_and_ui_routes(self):
        with TestClient(gateway_app_module.app) as client:
            res = client.get("/health")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["service"], "neutron-gateway")
            home = client.get("/")
            self.assertEqual(home.status_code, 200)
            self.assertIn("no-store", home.headers.get("Cache-Control", ""))
            self.assertIn('<div id="root"></div>', home.text)
            self.assertIn('/ui-assets/', home.text)
            import re
            asset_match = re.search(r'(/ui-assets/[^"\']+\.js)', home.text)
            self.assertIsNotNone(asset_match)
            js_resp = client.get(asset_match.group(1))
            self.assertEqual(js_resp.status_code, 200)

    def test_crawler_search_endpoint_cached_and_hybrid(self):
        cached = [
            {
                "url_hash": str(i),
                "url": f"https://example.org/doc-{i}",
                "title": f"Doc {i} neutron",
                "snippet": "Neutron sample cached hit discussing search architecture.",
                "score": 1.0,
                "crawled_at": "2026-11-10 12:00:00",
            }
            for i in range(5)
        ]
        with patch.object(crawler_app_module.turso_crawler_client, "search", AsyncMock(return_value=cached)), \
             patch.object(crawler_app_module.turso_crawler_client, "get_payloads_map", AsyncMock(return_value={})), \
             patch.object(crawler_app_module.turso_crawler_client, "record_hot_topic", AsyncMock()):
            with TestClient(crawler_app_module.app) as client:
                res = client.get("/search?q=neutron")
                self.assertEqual(res.status_code, 200)
                data = res.json()
                self.assertEqual(data["source"], "index_cache")
                self.assertEqual(data["total"], 5)
                self.assertIsNotNone(data.get("answer"))

                res_api = client.get("/api/research?q=neutron&max_results=3&include_markdown=true")
                self.assertEqual(res_api.status_code, 200)
                api_data = res_api.json()
                self.assertEqual(len(api_data["sources"]), 3)
                self.assertIn("full_markdown", api_data["sources"][0])
                self.assertIsNotNone(api_data.get("answer"))

    def test_internal_auth_enforcement(self):
        with TestClient(crawler_app_module.app) as client:
            with patch.object(crawler_app_module.settings, "INTERNAL_API_KEY", ""):
                res_unconfigured = client.post("/crawl/jit", json={"query": "test"})
                self.assertEqual(res_unconfigured.status_code, 503)

            with patch.object(crawler_app_module.settings, "INTERNAL_API_KEY", "super-secret-random-key-123"):
                res_no_header = client.post("/crawl/jit", json={"query": "test"})
                self.assertEqual(res_no_header.status_code, 401)

                res_wrong = client.post(
                    "/crawl/jit",
                    json={"query": "test"},
                    headers={"Authorization": "Bearer wrong-key"},
                )
                self.assertEqual(res_wrong.status_code, 403)

    def test_search_stream_emits_transparent_events(self):
        fake_hit = {
            "url_hash": "12345",
            "url": "https://example.org/quantum",
            "title": "Quantum Guide",
            "snippet": "Quantum error correction protects encoded quantum states from decoherence.",
            "_full_text": "Quantum error correction protects encoded quantum states from decoherence using stabilizer codes.",
            "score": 0.85,
            "crawled_at": "2026-11-10 12:00:00",
        }

        async def fake_discovery(query, max_urls=8, on_source_complete=None, **kwargs):
            if on_source_complete:
                await on_source_complete({"source": "wikipedia", "url_count": 1, "duration_ms": 12})
            return ["https://example.org/quantum"], [{"source": "wikipedia", "url_count": 1, "duration_ms": 12}]

        with patch.object(crawler_app_module.turso_crawler_client, "search", AsyncMock(return_value=[])), \
             patch.object(crawler_app_module.turso_crawler_client, "record_hot_topic", AsyncMock()), \
             patch.object(crawler_app_module, "discover_seed_urls_detailed", side_effect=fake_discovery), \
             patch.object(crawler_app_module.robots_manager, "is_allowed", AsyncMock(return_value=True)), \
             patch.object(crawler_app_module, "fetch_and_index_document", AsyncMock(return_value=fake_hit)):
            with TestClient(crawler_app_module.app) as client:
                resp = client.get("/search/stream?q=quantum")
                self.assertEqual(resp.status_code, 200)
                body = resp.text
                self.assertIn("event: cached_results", body)
                self.assertIn("event: discovery_start", body)
                self.assertIn("event: discovery_result", body)
                self.assertIn("event: crawl_success", body)
                self.assertIn("event: live_result", body)
                self.assertIn("event: answer", body)
                self.assertIn("event: done", body)

    def test_large_64bit_url_hash_roundtrips_as_exact_string(self):
        large_hash = -8197675117857346549
        cached = [
            {
                "url_hash": str(large_hash),
                "url": "https://example.org/large-hash",
                "title": "64-bit Precision Check",
                "snippet": "Verify exact decimal serialization past Number.MAX_SAFE_INTEGER.",
                "score": 1.0,
                "crawled_at": "2026-11-11 00:00:00",
            }
            for _ in range(5)
        ]
        meta_row = {
            "url_hash": str(large_hash),
            "url": "https://example.org/large-hash",
            "title": "64-bit Precision Check",
            "snippet": "Fallback snippet",
            "crawled_at": "2026-11-11 00:00:00",
        }
        with patch.object(crawler_app_module.turso_crawler_client, "search", AsyncMock(return_value=cached)), \
             patch.object(crawler_app_module.turso_crawler_client, "get_payloads_map", AsyncMock(return_value={})), \
             patch.object(crawler_app_module.turso_crawler_client, "record_hot_topic", AsyncMock()), \
             patch.object(crawler_app_module.turso_crawler_client, "get_document_metadata", AsyncMock(return_value=meta_row)), \
             patch.object(crawler_app_module.turso_crawler_client, "get_document_payload", AsyncMock(return_value=compress_text("# Precision OK"))):
            with TestClient(crawler_app_module.app) as client:
                s_res = client.get("/search?q=precision")
                self.assertEqual(s_res.status_code, 200)
                self.assertEqual(s_res.json()["results"][0]["url_hash"], "-8197675117857346549")

                d_res = client.get(f"/doc/{large_hash}")
                self.assertEqual(d_res.status_code, 200)
                self.assertEqual(d_res.json()["url_hash"], "-8197675117857346549")
                self.assertEqual(d_res.json()["full_markdown"], "# Precision OK")


if __name__ == "__main__":
    unittest.main()

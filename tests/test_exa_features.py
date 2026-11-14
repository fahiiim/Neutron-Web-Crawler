"""Unit tests for Exa-style features adopted into Neutron.

Validates:
- Query-conditioned sentence highlights extraction.
- Exa-style link query augmentation.
- Domain inclusion/exclusion in search and discovery.
- Batch contents extraction endpoint (/contents).
- Seed similarity search endpoint (/find_similar).
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from neutron_rpc.neutron.v1 import neutron_pb
from services.gateway.app import app
from spaces.crawler.discovery import augment_link_query
from spaces.crawler.synthesis import extract_query_highlights


class TestExaAdoptedFeatures(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_extract_query_highlights_salience(self):
        text = (
            "# Vector Search Overview\n\n"
            "A vector database indexes high-dimensional vectors for fast approximate nearest neighbor search. "
            "It uses index algorithms like HNSW and IVF to achieve sub-millisecond retrieval. "
            "Traditional relational databases evaluate exact boolean matches on tables. "
            "Cookies help us deliver this website and personalize ads."
        )
        highlights = extract_query_highlights("vector database nearest neighbor search", text, num_highlights=2)
        self.assertGreaterEqual(len(highlights), 1)
        self.assertIn("vector database", highlights[0].lower())
        self.assertFalse(any("cookie" in h.lower() for h in highlights))

    def test_augment_link_query(self):
        # Questions preserved as is
        self.assertEqual(
            augment_link_query("what is the main purpose of joining in SQL"),
            "what is the main purpose of joining in SQL",
        )
        # Quoted queries preserved
        self.assertEqual(
            augment_link_query('"distributed consensus"'),
            '"distributed consensus"',
        )
        # Code mode augmented
        augmented_code = augment_link_query("fastapi connectrpc", mode="code")
        self.assertIn("github repository", augmented_code)

        # Papers mode augmented
        augmented_papers = augment_link_query("transformer attention", mode="papers")
        self.assertIn("research paper arxiv", augmented_papers)

    @patch("services.gateway.app._get_search_client")
    def test_contents_endpoint(self, mock_get_client):
        mock_search = AsyncMock()
        mock_get_client.return_value = mock_search

        doc1 = neutron_pb.SearchDocument(
            url="https://example.com/vector",
            url_hash="123456",
            title="Vector DB",
            crawled_at="2026-11-14",
            full_markdown="# Vector DB\n\nClean markdown text.",
            highlights=["Vector DB clean highlight."],
        )
        mock_search.batch_get_documents.return_value = neutron_pb.BatchGetDocumentsResponse(
            documents=[doc1]
        )

        resp = self.client.post(
            "/contents",
            json={
                "urls": ["https://example.com/vector"],
                "highlights": {"query": "vector db"},
                "max_characters": 2000,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("results", data)
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["url"], "https://example.com/vector")
        self.assertEqual(data["results"][0]["highlights"], ["Vector DB clean highlight."])

    @patch("services.gateway.app._get_search_client")
    def test_find_similar_endpoint(self, mock_get_client):
        mock_search = AsyncMock()
        mock_get_client.return_value = mock_search

        similar_doc = neutron_pb.SearchDocument(
            url="https://other.org/similar",
            url_hash="789012",
            title="Similar Tool",
            snippet="A similar tool for indexing.",
            score=0.88,
        )
        mock_search.find_similar.return_value = neutron_pb.FindSimilarResponse(
            results=[similar_doc]
        )

        resp = self.client.post(
            "/find_similar",
            json={
                "url": "https://example.com/source",
                "limit": 3,
                "exclude_source_domain": True,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["seed_url"], "https://example.com/source")
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["url"], "https://other.org/similar")

    @patch("services.gateway.app._execute_gateway_search")
    def test_search_accepts_domain_filters(self, mock_search):
        mock_search.return_value = {
            "query": "vector",
            "mode": "all",
            "source": "hybrid_jit",
            "total": 1,
            "answer": None,
            "results": [],
        }

        resp = self.client.get("/search?q=vector&include_domains=arxiv.org,github.com&exclude_domains=quora.com")
        self.assertEqual(resp.status_code, 200)
        mock_search.assert_called_once()
        _, kwargs = mock_search.call_args
        self.assertEqual(kwargs.get("include_domains"), ["arxiv.org", "github.com"])
        self.assertEqual(kwargs.get("exclude_domains"), ["quora.com"])


if __name__ == "__main__":
    unittest.main()


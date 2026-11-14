"""Unit tests for Neutron Agent Retrieval and evaluation features.

Validates:
- Query-conditioned sentence highlights extraction.
- Agent retrieval link query augmentation.
- Domain inclusion/exclusion in search and discovery.
- Batch contents extraction endpoint (/contents).
- Seed similarity search endpoint (/find_similar and /findSimilar).
- Evaluation metrics computation (confidence, coverage, faithfulness).
- Strict relevance floor preventing Frankenstein answer hallucinations.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from neutron_rpc.neutron.v1 import neutron_pb
from services.gateway.app import app
from spaces.crawler.discovery import augment_link_query
from spaces.crawler.parser import extract_subpage_candidates
from spaces.crawler.synthesis import (
    calculate_evaluation_metrics,
    classify_query_intent,
    extract_query_highlights,
    synthesize_grounded_answer,
)


class TestAgentRetrievalFeatures(unittest.TestCase):
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

    def test_classify_query_intent(self):
        # Keyword triggers
        self.assertEqual(classify_query_intent('"exact phrase search"'), "keyword")
        self.assertEqual(classify_query_intent("site:github.com python"), "keyword")
        self.assertEqual(classify_query_intent("filetype:pdf machine learning"), "keyword")
        self.assertEqual(classify_query_intent("HTTP_200_OK"), "keyword")
        self.assertEqual(classify_query_intent("foo.bar()"), "keyword")
        self.assertEqual(classify_query_intent("get_user_by_id"), "keyword")
        self.assertEqual(classify_query_intent("reactDom"), "keyword")
        self.assertEqual(classify_query_intent("python"), "keyword")

        # Neural triggers
        self.assertEqual(classify_query_intent("when bangladesh is established"), "neural")
        self.assertEqual(classify_query_intent("what is quantum computing"), "neural")
        self.assertEqual(classify_query_intent("whos is Md. Fahim Sarker Mridul from GUB"), "neural")
        self.assertEqual(classify_query_intent("whose idea was neural search"), "neural")
        self.assertEqual(classify_query_intent("how to build an autonomous agent in python"), "neural")
        self.assertEqual(classify_query_intent("best tools for distributed web scraping"), "neural")
        self.assertEqual(classify_query_intent("compare postgresql vs mongodb for json"), "neural")
        self.assertEqual(classify_query_intent("papers on diffusion models with code?"), "neural")

    def test_extract_subpage_candidates(self):
        parent_url = "https://example.com/project"
        links = [
            "https://example.com/project/docs",
            "https://example.com/project/pricing",
            "https://example.com/project/api",
            "https://example.com/login",
            "https://external.com/other",
            "https://example.com/project",
            "https://example.com/blog/2024",
        ]
        candidates = extract_subpage_candidates(parent_url, links, targets=["doc", "api"], max_subpages=3)
        self.assertIn("https://example.com/project/docs", candidates)
        self.assertIn("https://example.com/project/api", candidates)
        self.assertNotIn("https://external.com/other", candidates)
        self.assertNotIn("https://example.com/project", candidates)
        self.assertLessEqual(len(candidates), 3)

    @patch("services.gateway.app._execute_gateway_search")
    def test_agent_post_search_endpoint(self, mock_search):
        mock_search.return_value = {
            "query": "vector databases",
            "mode": "all",
            "source": "hybrid_jit",
            "total": 1,
            "answer": {"summary": "Vector databases index embeddings."},
            "evaluation": {
                "confidence_score": 0.92,
                "confidence_percent": 92,
                "query_coverage": 1.0,
                "grounding_faithfulness": 0.95,
                "relevance_grade": "High",
                "matched_concepts": ["vector", "databases"],
                "missing_concepts": [],
                "evaluation_summary": "Strictly grounded across 1 citation.",
            },
            "results": [
                {
                    "url": "https://example.com/docs",
                    "url_hash": "112233",
                    "title": "Vector Docs",
                    "snippet": "Full documentation.",
                    "score": 0.95,
                    "crawled_at": "2026-11-14",
                    "full_markdown": "# Documentation",
                    "highlights": ["Vector Docs highlight"],
                    "subpages": [
                        {"id": "4455", "url": "https://example.com/docs/api", "title": "API Reference"}
                    ],
                }
            ],
            "resolvedSearchType": "neural",
        }

        resp = self.client.post(
            "/search",
            json={
                "query": "vector databases",
                "type": "auto",
                "numResults": 5,
                "contents": {
                    "text": True,
                    "highlights": True,
                    "subpages": 2,
                },
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("resolvedSearchType", data)
        self.assertEqual(data["resolvedSearchType"], "neural")
        self.assertEqual(len(data["results"]), 1)
        res = data["results"][0]
        self.assertEqual(res["url"], "https://example.com/docs")
        self.assertEqual(res["text"], "# Documentation")
        self.assertIn("highlights", res)
        self.assertIn("subpages", res)
        self.assertEqual(data["answer"], "Vector databases index embeddings.")
        self.assertIn("evaluation", data)
        self.assertEqual(data["evaluation"]["confidence_score"], 0.92)

    @patch("services.gateway.app._execute_gateway_search")
    def test_research_api_returns_evaluation(self, mock_search):
        mock_search.return_value = {
            "query": "quantum computing",
            "mode": "all",
            "source": "hybrid_jit",
            "total": 1,
            "answer": {"summary": "Quantum computing uses qubits."},
            "evaluation": {
                "confidence_score": 0.88,
                "query_coverage": 1.0,
                "grounding_faithfulness": 0.95,
                "relevance_grade": "High",
            },
            "results": [{"url": "https://example.org/quantum", "title": "Quantum"}],
            "timings": {"total_ms": 12},
            "request_id": "test-req",
        }
        resp = self.client.get("/api/research?q=quantum+computing")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("evaluation", data)
        self.assertEqual(data["evaluation"]["confidence_score"], 0.88)
        self.assertEqual(data["total"], 1)

    def test_calculate_evaluation_metrics_grounded(self):
        query = "how does crispr cas9 gene editing work"
        docs = [
            {
                "url": "https://example.org/crispr",
                "title": "CRISPR-Cas9 Mechanism",
                "snippet": "CRISPR-Cas9 enables precise gene editing by utilizing a guide RNA and Cas9 endonuclease.",
                "score": 0.92,
            }
        ]
        answer_text = "CRISPR-Cas9 enables precise gene editing using guide RNA. [1]"
        citations = [{"index": 1, "url": "https://example.org/crispr"}]
        metrics = calculate_evaluation_metrics(query, docs, answer_text, citations)
        self.assertGreater(metrics["confidence_score"], 0.6)
        self.assertGreater(metrics["query_coverage"], 0.5)
        self.assertGreater(metrics["grounding_faithfulness"], 0.8)
        self.assertIn(metrics["relevance_grade"], ("High", "Moderate"))
        self.assertIn("crispr", metrics["matched_concepts"])

    def test_strict_relevance_gate_prevents_frankestein_hallucinations(self):
        # Query about a person should NOT synthesize an answer using unrelated cruise missile text
        query = "Whos is Md. Fahim Sarker Mridul from GUB"
        unrelated_docs = [
            {
                "url": "https://en.wikipedia.org/wiki/AGM-158_JASSM",
                "title": "AGM-158 JASSM - Wikipedia",
                "snippet": "It is a large, stealthy long-range weapon with a 1,000-pound (450 kg) armor piercing warhead.",
                "score": 0.05,
            },
            {
                "url": "https://arxiv.org/abs/1102.2017v2",
                "title": "Synthesis of Mechanism for single- and hybrid-tasks using Differential Evolution",
                "snippet": "The optimal dimensional synthesis for planar mechanism using differential evolution is demonstrated.",
                "score": 0.04,
            },
        ]
        # Must return None because candidate sentences don't match core query concepts
        answer = synthesize_grounded_answer(query, unrelated_docs, max_sentences=3)
        self.assertIsNone(answer)

    @patch("services.gateway.app._get_search_client")
    def test_find_similar_camel_case_endpoint(self, mock_get_client):
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
            "/findSimilar",
            json={
                "url": "https://example.com/source",
                "numResults": 3,
                "excludeSourceDomain": True,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["seed_url"], "https://example.com/source")
        self.assertEqual(len(data["results"]), 1)


if __name__ == "__main__":
    unittest.main()


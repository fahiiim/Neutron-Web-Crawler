"""Unit tests for core crawler normalization and deduplication algorithms."""

import unittest
from spaces.crawler.dedup import canonicalize_url, hash_url, hash_domain, compute_simhash
from spaces.crawler.compression import compress_text, decompress_text


class TestCrawlerCore(unittest.TestCase):
    """Test suite for URL canonicalization, hashing, and compression."""

    def test_canonicalize_url_strips_tracking(self):
        raw = "https://example.com/blog/article/?utm_source=twitter&utm_medium=social&ref=newsletter#comments"
        expected = "https://example.com/blog/article"
        self.assertEqual(canonicalize_url(raw), expected)

    def test_canonicalize_url_normalizes_ports(self):
        raw = "http://example.com:80/path/"
        expected = "http://example.com/path"
        self.assertEqual(canonicalize_url(raw), expected)

    def test_hash_url_is_signed_64bit(self):
        url = "https://en.wikipedia.org/wiki/Zig_(programming_language)"
        h = hash_url(url)
        self.assertIsInstance(h, int)
        self.assertGreaterEqual(h, -(1 << 63))
        self.assertLess(h, (1 << 63))

    def test_zstd_compression_roundtrip(self):
        original = "# Rust and Zig Benchmarks\n\nHigh performance asynchronous IO comparison."
        compressed = compress_text(original)
        self.assertIsInstance(compressed, bytes)
        decompressed = decompress_text(compressed)
        self.assertEqual(decompressed, original)

    def test_simhash_consistency(self):
        text_a = "High performance web crawler with asynchronous IO and parallel fetching."
        text_b = "High performance web crawler with asynchronous IO and concurrent fetching."
        hash_a = compute_simhash(text_a)
        hash_b = compute_simhash(text_b)
        self.assertIsInstance(hash_a, int)
        self.assertIsInstance(hash_b, int)


if __name__ == "__main__":
    unittest.main()

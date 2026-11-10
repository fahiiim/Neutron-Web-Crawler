"""In-memory URL Bloom Filter for O(1) duplicate crawl avoidance."""

import math
from typing import Iterable

try:
    import mmh3
    from bitarray import bitarray

    _HAS_NATIVE_BLOOM = True
except ImportError:
    import xxhash

    _HAS_NATIVE_BLOOM = False

try:
    from .dedup import canonicalize_url
except ImportError:
    from dedup import canonicalize_url


class URLBloomFilter:
    """Space-efficient probabilistic set for checking previously crawled URLs."""

    def __init__(self, capacity: int = 1_000_000, fp_rate: float = 0.001) -> None:
        capacity = max(1000, capacity)
        fp_rate = min(max(fp_rate, 1e-6), 0.5)

        self.capacity = capacity
        self.fp_rate = fp_rate
        self.size = max(1024, int(-capacity * math.log(fp_rate) / (math.log(2) ** 2)))
        self.hash_count = max(1, int((self.size / capacity) * math.log(2)))
        self._count = 0

        if _HAS_NATIVE_BLOOM:
            self._bits = bitarray(self.size)
            self._bits.setall(0)
        else:
            self._bytes = bytearray((self.size + 7) // 8)

    def _indices(self, key: str) -> Iterable[int]:
        if _HAS_NATIVE_BLOOM:
            for seed in range(self.hash_count):
                yield mmh3.hash(key, seed, signed=False) % self.size
        else:
            encoded = key.encode("utf-8")
            for seed in range(self.hash_count):
                yield xxhash.xxh64(encoded, seed=seed).intdigest() % self.size

    @staticmethod
    def _normalize(url: str) -> str:
        normalized = canonicalize_url(url, strip_www=True)
        return normalized or url.strip()

    def add(self, url: str) -> None:
        """Record a URL in the Bloom filter."""
        key = self._normalize(url)
        if not key:
            return
        if _HAS_NATIVE_BLOOM:
            for idx in self._indices(key):
                self._bits[idx] = 1
        else:
            for idx in self._indices(key):
                self._bytes[idx >> 3] |= 1 << (idx & 7)
        self._count += 1

    def add_many(self, urls: Iterable[str]) -> int:
        """Bulk-insert URLs into the Bloom filter."""
        added = 0
        for url in urls:
            if url:
                self.add(url)
                added += 1
        return added

    def might_contain(self, url: str) -> bool:
        """Return True if the URL may have been seen before, False if definitely new."""
        key = self._normalize(url)
        if not key:
            return False
        if _HAS_NATIVE_BLOOM:
            return all(self._bits[idx] for idx in self._indices(key))
        return all(
            bool(self._bytes[idx >> 3] & (1 << (idx & 7)))
            for idx in self._indices(key)
        )

    def clear(self) -> None:
        """Reset all bits in the Bloom filter."""
        if _HAS_NATIVE_BLOOM:
            self._bits.setall(0)
        else:
            self._bytes[:] = b"\x00" * len(self._bytes)
        self._count = 0

    def __len__(self) -> int:
        return self._count

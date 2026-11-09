import re
import urllib.parse
import xxhash
from typing import Set

# Tracking params to strip during canonicalization
STRIP_QUERY_PARAMS = {
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'gclid', 'fbclid', 'ref', 'source', 'mc_cid', 'mc_eid'
}

def canonicalize_url(raw_url: str) -> str:
    """Normalize URLs to prevent crawling the same page multiple times."""
    try:
        parsed = urllib.parse.urlsplit(raw_url.strip())
        scheme = parsed.scheme.lower()
        if scheme not in ('http', 'https'):
            return ""

        netloc = parsed.netloc.lower()
        # Remove standard default ports
        if netloc.endswith(':80') and scheme == 'http':
            netloc = netloc[:-3]
        elif netloc.endswith(':443') and scheme == 'https':
            netloc = netloc[:-4]

        # Filter tracking query parameters
        query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
        filtered_queries = [
            (k, v) for k, v in query_pairs if k.lower() not in STRIP_QUERY_PARAMS
        ]
        filtered_queries.sort(key=lambda x: x[0])
        new_query = urllib.parse.urlencode(filtered_queries)

        path = parsed.path
        if not path:
            path = "/"
        elif len(path) > 1 and path.endswith('/'):
            path = path[:-1]

        # Ignore fragments (#section) completely for web crawling
        return urllib.parse.urlunsplit((scheme, netloc, path, new_query, ""))
    except Exception:
        return ""

def hash_url(url: str) -> int:
    """Return signed 64-bit integer hash of canonical URL for database primary keys."""
    # xxhash64 returns an unsigned 64-bit int; convert to signed 64-bit int for SQL compatibility
    val = xxhash.xxh64(url.encode('utf-8')).intdigest()
    if val >= (1 << 63):
        val -= (1 << 64)
    return val

def extract_domain_host(url: str) -> str:
    """Extract registered domain / hostname for politeness queues."""
    try:
        return urllib.parse.urlsplit(url).netloc.lower()
    except Exception:
        return "unknown"

def hash_domain(hostname: str) -> int:
    """Return signed 64-bit integer hash of domain."""
    val = xxhash.xxh64(hostname.encode('utf-8')).intdigest()
    if val >= (1 << 63):
        val -= (1 << 64)
    return val

def compute_simhash(text: str) -> int:
    """Compute 64-bit SimHash of text for near-duplicate document detection."""
    tokens = re.findall(r'\b\w{3,}\b', text.lower())
    if not tokens:
        return 0

    v = [0] * 64
    for token in tokens:
        h = xxhash.xxh64(token.encode('utf-8')).intdigest()
        for i in range(64):
            bit = (h >> i) & 1
            v[i] += 1 if bit else -1

    simhash = 0
    for i in range(64):
        if v[i] > 0:
            simhash |= (1 << i)

    # Convert to signed 64-bit int
    if simhash >= (1 << 63):
        simhash -= (1 << 64)
    return simhash

def simhash_distance(hash1: int, hash2: int) -> int:
    """Calculate Hamming distance between two 64-bit SimHashes (<=3 means near duplicate)."""
    # Unpack signed to unsigned for bitwise XOR
    u1 = hash1 if hash1 >= 0 else hash1 + (1 << 64)
    u2 = hash2 if hash2 >= 0 else hash2 + (1 << 64)
    return bin(u1 ^ u2).count('1')

class InMemoryDeduplicator:
    """
    Fast in-memory 64-bit hash tracker.
    Stores up to 10M hashes in RAM with O(1) membership checks.
    """
    def __init__(self):
        self._seen: Set[int] = set()

    def contains(self, url_hash: int) -> bool:
        return url_hash in self._seen

    def add(self, url_hash: int) -> bool:
        """Returns True if newly added, False if already present."""
        if url_hash in self._seen:
            return False
        self._seen.add(url_hash)
        return True

    def __len__(self) -> int:
        return len(self._seen)


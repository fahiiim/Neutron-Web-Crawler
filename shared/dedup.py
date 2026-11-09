import re
import urllib.parse
import xxhash
from typing import Set

STRIP_QUERY_PARAMS = {
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'gclid', 'fbclid', 'ref', 'source', 'mc_cid', 'mc_eid'
}

def canonicalize_url(raw_url: str) -> str:
    """Normalize URLs to prevent duplicate crawling."""
    try:
        parsed = urllib.parse.urlsplit(raw_url.strip())
        scheme = parsed.scheme.lower()
        if scheme not in ('http', 'https'):
            return ""

        netloc = parsed.netloc.lower()
        if netloc.endswith(':80') and scheme == 'http':
            netloc = netloc[:-3]
        elif netloc.endswith(':443') and scheme == 'https':
            netloc = netloc[:-4]

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

        return urllib.parse.urlunsplit((scheme, netloc, path, new_query, ""))
    except Exception:
        return ""

def hash_url(url: str) -> int:
    """Return signed 64-bit integer hash of canonical URL."""
    val = xxhash.xxh64(url.encode('utf-8')).intdigest()
    if val >= (1 << 63):
        val -= (1 << 64)
    return val

def extract_domain_host(url: str) -> str:
    """Extract registered domain / hostname."""
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
    """Compute 64-bit SimHash of text."""
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

    if simhash >= (1 << 63):
        simhash -= (1 << 64)
    return simhash


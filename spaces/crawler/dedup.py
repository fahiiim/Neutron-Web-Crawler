"""URL normalization, hashing, and near-duplicate deduplication algorithms."""

from collections import Counter
import re
from typing import Set
import urllib.parse
import xxhash

STRIP_QUERY_PARAMS: Set[str] = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "gclid",
    "fbclid",
    "msclkid",
    "twclid",
    "dclid",
    "srsltid",
    "igshid",
    "yclid",
    "ref",
    "source",
    "mc_cid",
    "mc_eid",
    "_ga",
    "_gl",
}


def canonicalize_url(raw_url: str, strip_www: bool = False) -> str:
    """Normalize a raw URL to ensure deduplication accuracy across the index.

    Removes tracking parameters, normalizes default ports, trailing slashes,
    percent-encoding, and strips fragments.

    Args:
        raw_url: The unnormalized target URL string.
        strip_www: When True, strips a leading 'www.' subdomain for strict dedup.

    Returns:
        The canonicalized URL string, or empty string if invalid.
    """
    try:
        parsed = urllib.parse.urlsplit(raw_url.strip())
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            return ""

        netloc = parsed.netloc.lower()
        if not netloc:
            return ""
        if netloc.endswith(":80") and scheme == "http":
            netloc = netloc[:-3]
        elif netloc.endswith(":443") and scheme == "https":
            netloc = netloc[:-4]

        if strip_www and netloc.startswith("www."):
            netloc = netloc[4:]

        # Filter out analytics/marketing tracking params and sort consistently
        query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
        clean_pairs = [
            (k, v) for k, v in query_pairs if k.lower() not in STRIP_QUERY_PARAMS
        ]
        clean_pairs.sort(key=lambda item: (item[0], item[1]))
        new_query = urllib.parse.urlencode(clean_pairs)

        # Normalize percent-encoding in path
        unquoted_path = urllib.parse.unquote(parsed.path)
        path = urllib.parse.quote(unquoted_path, safe="/:@-._~!$&'()*+,;=")
        if not path:
            path = "/"
        elif len(path) > 1 and path.endswith("/"):
            path = path[:-1]

        return urllib.parse.urlunsplit((scheme, netloc, path, new_query, ""))
    except Exception:
        return ""


def hash_url(url: str) -> int:
    """Compute a signed 64-bit integer hash of a canonical URL for SQL indexing."""
    digest = xxhash.xxh64(url.encode("utf-8")).intdigest()
    if digest >= (1 << 63):
        digest -= 1 << 64
    return digest


def extract_domain_host(url: str) -> str:
    """Extract normalized lowercase hostname (without port or 'www.') from a URL."""
    try:
        netloc = urllib.parse.urlsplit(url).netloc.lower()
        host = netloc.split("@")[-1].split(":")[0]
        if host.startswith("www."):
            host = host[4:]
        return host or "unknown"
    except Exception:
        return "unknown"


def hash_domain(hostname: str) -> int:
    """Compute a signed 64-bit integer hash of a domain name."""
    normalized = hostname.lower().strip()
    if normalized.startswith("www."):
        normalized = normalized[4:]
    digest = xxhash.xxh64(normalized.encode("utf-8")).intdigest()
    if digest >= (1 << 63):
        digest -= 1 << 64
    return digest


def compute_simhash(text: str) -> int:
    """Calculate a 64-bit Charikar SimHash using weighted unigrams and 2-gram shingles."""
    tokens = re.findall(r"\b\w{3,}\b", text.lower())
    if not tokens:
        return 0

    features: Counter[str] = Counter(tokens)
    # Add overlapping 2-gram shingles to preserve phrase ordering
    if len(tokens) > 1:
        for idx in range(len(tokens) - 1):
            features[f"{tokens[idx]}_{tokens[idx + 1]}"] += 2

    vector = [0] * 64
    for feature, weight in features.items():
        token_hash = xxhash.xxh64(feature.encode("utf-8")).intdigest()
        for i in range(64):
            bit = (token_hash >> i) & 1
            vector[i] += weight if bit else -weight

    fingerprint = 0
    for i in range(64):
        if vector[i] > 0:
            fingerprint |= 1 << i

    if fingerprint >= (1 << 63):
        fingerprint -= 1 << 64
    return fingerprint


def hamming_distance(hash_a: int, hash_b: int) -> int:
    """Compute the 64-bit Hamming distance between two signed 64-bit hashes."""
    xor_val = (hash_a ^ hash_b) & 0xFFFFFFFFFFFFFFFF
    return xor_val.bit_count()

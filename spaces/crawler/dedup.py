"""URL normalization, hashing, and near-duplicate deduplication algorithms."""

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
    "gclid",
    "fbclid",
    "ref",
    "source",
    "mc_cid",
    "mc_eid",
}


def canonicalize_url(raw_url: str) -> str:
    """Normalize a raw URL to ensure deduplication accuracy across the index.

    Removes tracking parameters, normalizes default ports and trailing slashes,
    and strips fragments.

    Args:
        raw_url: The unnormalized target URL string.

    Returns:
        The canonicalized URL string, or empty string if invalid.
    """
    try:
        parsed = urllib.parse.urlsplit(raw_url.strip())
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            return ""

        netloc = parsed.netloc.lower()
        if netloc.endswith(":80") and scheme == "http":
            netloc = netloc[:-3]
        elif netloc.endswith(":443") and scheme == "https":
            netloc = netloc[:-4]

        # Filter out common analytics and marketing tracking query parameters
        query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
        clean_pairs = [
            (k, v) for k, v in query_pairs if k.lower() not in STRIP_QUERY_PARAMS
        ]
        clean_pairs.sort(key=lambda item: item[0])
        new_query = urllib.parse.urlencode(clean_pairs)

        path = parsed.path
        if not path:
            path = "/"
        elif len(path) > 1 and path.endswith("/"):
            path = path[:-1]

        return urllib.parse.urlunsplit((scheme, netloc, path, new_query, ""))
    except Exception:
        return ""


def hash_url(url: str) -> int:
    """Compute a signed 64-bit integer hash of a canonical URL for SQL indexing.

    Args:
        url: Canonical URL string.

    Returns:
        Signed 64-bit integer.
    """
    digest = xxhash.xxh64(url.encode("utf-8")).intdigest()
    if digest >= (1 << 63):
        digest -= 1 << 64
    return digest


def extract_domain_host(url: str) -> str:
    """Extract the lowercase hostname from a URL.

    Args:
        url: Target URL string.

    Returns:
        Hostname string.
    """
    try:
        return urllib.parse.urlsplit(url).netloc.lower()
    except Exception:
        return "unknown"


def hash_domain(hostname: str) -> int:
    """Compute a signed 64-bit integer hash of a domain name.

    Args:
        hostname: Lowercase domain string.

    Returns:
        Signed 64-bit integer.
    """
    digest = xxhash.xxh64(hostname.encode("utf-8")).intdigest()
    if digest >= (1 << 63):
        digest -= 1 << 64
    return digest


def compute_simhash(text: str) -> int:
    """Calculate a 64-bit Charikar SimHash for near-duplicate text detection.

    Args:
        text: Extracted page text.

    Returns:
        Signed 64-bit integer representing document fingerprint.
    """
    tokens = re.findall(r"\b\w{3,}\b", text.lower())
    if not tokens:
        return 0

    vector = [0] * 64
    for token in tokens:
        token_hash = xxhash.xxh64(token.encode("utf-8")).intdigest()
        for i in range(64):
            bit = (token_hash >> i) & 1
            vector[i] += 1 if bit else -1

    fingerprint = 0
    for i in range(64):
        if vector[i] > 0:
            fingerprint |= 1 << i

    if fingerprint >= (1 << 63):
        fingerprint -= 1 << 64
    return fingerprint


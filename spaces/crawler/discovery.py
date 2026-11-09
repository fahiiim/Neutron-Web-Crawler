"""Meta-search discovery adapters resilient against datacenter IP rate limits."""

from typing import List, Set
import httpx

from dedup import canonicalize_url, extract_domain_host

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


async def discover_seed_urls(query: str, max_urls: int = 12) -> List[str]:
    """Discover candidate seed URLs for a query across open, high-yield APIs.

    Enforces domain diversity so the immediate crawl burst never violates
    per-host politeness constraints.

    Args:
        query: User search query string.
        max_urls: Target count of diverse URLs.

    Returns:
        List of canonicalized seed URLs.
    """
    discovered: List[str] = []
    headers = {"User-Agent": USER_AGENT}

    async with httpx.AsyncClient(timeout=3.5, headers=headers) as client:
        # 1. Wikipedia OpenSearch API (High authority, instant, never blocked)
        try:
            wiki_url = (
                f"https://en.wikipedia.org/w/api.php?action=opensearch"
                f"&search={query}&limit=6&namespace=0&format=json"
            )
            response = await client.get(wiki_url)
            if response.status_code == 200:
                data = response.json()
                if len(data) >= 4 and isinstance(data[3], list):
                    discovered.extend(data[3])
        except Exception as exc:
            print(f"[Seed Discovery Wikipedia Warning]: {exc}")

        # 2. HackerNews / Tech Algolia API (Exceptional for programming & dev topics)
        try:
            hn_url = (
                f"https://hn.algolia.com/api/v1/search?query={query}"
                f"&tags=story&hitsPerPage=8"
            )
            response = await client.get(hn_url)
            if response.status_code == 200:
                hits = response.json().get("hits", [])
                for hit in hits:
                    story_url = hit.get("url")
                    if story_url:
                        discovered.append(story_url)
        except Exception as exc:
            print(f"[Seed Discovery HN Warning]: {exc}")

    # Canonicalize and apply domain diversity constraint
    seen_domains: Set[str] = set()
    diverse_urls: List[str] = []

    for raw_url in discovered:
        canonical = canonicalize_url(raw_url)
        if not canonical:
            continue
        domain = extract_domain_host(canonical)
        if domain not in seen_domains:
            seen_domains.add(domain)
            diverse_urls.append(canonical)
        if len(diverse_urls) >= max_urls:
            break

    return diverse_urls


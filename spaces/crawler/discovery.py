"""Meta-search discovery adapters resilient against datacenter IP rate limits.

Integrates real-time DuckDuckGo HTML web search with Chrome impersonation,
Wikipedia full-text search, and HackerNews Algolia.
"""

import asyncio
from typing import List, Set
import urllib.parse
from curl_cffi.requests import AsyncSession
import httpx
from selectolax.lexbor import LexborHTMLParser

from dedup import canonicalize_url, extract_domain_host

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

WIKI_USER_AGENT = (
    "NeutronSearchEngine/2.0 (https://github.com/fahiiim/Neutron-Web-Crawler; contact@neutron.search)"
)


async def _discover_duckduckgo(session: AsyncSession, query: str) -> List[str]:
    """Discover real-time web results via DuckDuckGo HTML using Chrome impersonation."""
    urls: List[str] = []
    try:
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        resp = await session.get(url, timeout=5.0)
        if resp.status_code == 200:
            tree = LexborHTMLParser(resp.text)
            for a in tree.css("a"):
                href = a.attributes.get("href", "")
                if "uddg=" in href:
                    idx = href.find("uddg=")
                    raw_target = href[idx + 5 :].split("&")[0]
                    unquoted = urllib.parse.unquote(raw_target)
                    if unquoted.startswith("http") and unquoted not in urls:
                        urls.append(unquoted)
    except Exception as exc:
        print(f"[Seed Discovery DDG Warning]: {exc}")
    return urls


async def _discover_wikipedia_fulltext(client: httpx.AsyncClient, query: str) -> List[str]:
    """Discover high-authority Wikipedia encyclopedic articles via full-text search."""
    urls: List[str] = []
    try:
        url = (
            f"https://en.wikipedia.org/w/api.php?action=query&list=search"
            f"&srsearch={urllib.parse.quote(query)}&utf8=&format=json"
        )
        resp = await client.get(url, headers={"User-Agent": WIKI_USER_AGENT}, timeout=4.0)
        if resp.status_code == 200:
            data = resp.json()
            for hit in data.get("query", {}).get("search", [])[:8]:
                title_slug = urllib.parse.quote(hit["title"].replace(" ", "_"))
                urls.append(f"https://en.wikipedia.org/wiki/{title_slug}")
    except Exception as exc:
        print(f"[Seed Discovery Wikipedia Warning]: {exc}")
    return urls


async def _discover_hackernews(client: httpx.AsyncClient, query: str) -> List[str]:
    """Discover programming, tech, and engineering articles via Algolia HN."""
    urls: List[str] = []
    try:
        url = (
            f"https://hn.algolia.com/api/v1/search?query={urllib.parse.quote(query)}"
            f"&tags=story&hitsPerPage=8"
        )
        resp = await client.get(url, timeout=3.5)
        if resp.status_code == 200:
            hits = resp.json().get("hits", [])
            for hit in hits:
                story_url = hit.get("url")
                if story_url and story_url.startswith("http"):
                    urls.append(story_url)
    except Exception as exc:
        print(f"[Seed Discovery HN Warning]: {exc}")
    return urls


async def discover_seed_urls(query: str, max_urls: int = 12) -> List[str]:
    """Discover candidate seed URLs across DuckDuckGo HTML, Wikipedia, and HackerNews.

    Enforces domain diversity so the immediate crawl burst never violates
    per-host politeness constraints.

    Args:
        query: User search query string.
        max_urls: Target count of diverse URLs.

    Returns:
        List of canonicalized seed URLs.
    """
    discovered: List[str] = []

    # Parallel discovery across primary web and knowledge engines
    async with AsyncSession(impersonate="chrome124") as curl_session:
        async with httpx.AsyncClient(timeout=4.5) as http_client:
            ddg_task = _discover_duckduckgo(curl_session, query)
            wiki_task = _discover_wikipedia_fulltext(http_client, query)
            hn_task = _discover_hackernews(http_client, query)

            results = await asyncio.gather(
                ddg_task, wiki_task, hn_task, return_exceptions=True
            )
            for res in results:
                if isinstance(res, list):
                    discovered.extend(res)

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

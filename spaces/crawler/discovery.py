"""Multi-source meta-search discovery adapters resilient against rate limits.

Integrates DuckDuckGo HTML, Wikipedia full-text search, HackerNews Algolia,
Reddit public JSON, arXiv academic search, GitHub repositories, and optional Brave Search.
"""

import asyncio
import random
import re
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple
import urllib.parse
import xml.etree.ElementTree as ET
import httpx
from selectolax.lexbor import LexborHTMLParser

try:
    from .config import settings
    from .dedup import canonicalize_url, extract_domain_host
    from .logging_utils import get_logger
except ImportError:
    from config import settings
    from dedup import canonicalize_url, extract_domain_host
    from logging_utils import get_logger

logger = get_logger("neutron.discovery")

CHROME_USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
]

USER_AGENT = CHROME_USER_AGENTS[0]

NEUTRON_BOT_AGENT = (
    "NeutronSearchEngine/3.0 (https://github.com/fahiiim/Neutron-Web-Crawler)"
)


def _pick_user_agent() -> str:
    return random.choice(CHROME_USER_AGENTS)


def _strip_question_framing(query: str) -> str:
    """Normalize conversational question queries to extract key search entities."""
    cleaned = re.sub(
        r"^(what\s+is\s+(the\s+)?(name\s+of\s+)?|who\s+is\s+(the\s+)?|"
        r"tell\s+me\s+about\s+|can\s+you\s+find\s+|how\s+to\s+|which\s+is\s+)",
        "",
        query.strip(),
        flags=re.IGNORECASE,
    ).strip()
    return cleaned if cleaned else query.strip()


async def _discover_duckduckgo_html(client: httpx.AsyncClient, query: str) -> List[str]:
    """Discover real-time web results via DuckDuckGo HTML with single retry."""
    urls: List[str] = []
    target_url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)

    for attempt in range(2):
        try:
            resp = await client.get(
                target_url,
                headers={"User-Agent": _pick_user_agent()},
                timeout=5.0,
            )
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
                break
        except Exception as exc:
            if attempt == 1:
                logger.warning("discovery_ddg_failed", error=str(exc))
            else:
                await asyncio.sleep(0.3)
    return urls


async def _discover_wikipedia_fulltext(
    client: httpx.AsyncClient, query: str
) -> List[str]:
    """Discover encyclopedic articles via Wikipedia's official search API."""
    urls: List[str] = []
    clean_q = _strip_question_framing(query)
    try:
        url = (
            f"https://en.wikipedia.org/w/api.php?action=query&list=search"
            f"&srsearch={urllib.parse.quote(clean_q)}&utf8=&format=json"
        )
        resp = await client.get(
            url, headers={"User-Agent": NEUTRON_BOT_AGENT}, timeout=4.0
        )
        if resp.status_code == 200:
            data = resp.json()
            for hit in data.get("query", {}).get("search", [])[:6]:
                title_slug = urllib.parse.quote(hit["title"].replace(" ", "_"))
                urls.append(f"https://en.wikipedia.org/wiki/{title_slug}")
    except Exception as exc:
        logger.warning("discovery_wikipedia_failed", error=str(exc))
    return urls


async def _discover_hackernews(client: httpx.AsyncClient, query: str) -> List[str]:
    """Discover programming, tech, and engineering articles via Algolia HN."""
    urls: List[str] = []
    clean_q = _strip_question_framing(query)
    try:
        url = (
            f"https://hn.algolia.com/api/v1/search?query={urllib.parse.quote(clean_q)}"
            f"&tags=story&hitsPerPage=6"
        )
        resp = await client.get(url, timeout=3.5)
        if resp.status_code == 200:
            hits = resp.json().get("hits", [])
            for hit in hits:
                story_url = hit.get("url")
                if story_url and story_url.startswith("http"):
                    urls.append(story_url)
    except Exception as exc:
        logger.warning("discovery_hackernews_failed", error=str(exc))
    return urls


async def _discover_reddit(client: httpx.AsyncClient, query: str) -> List[str]:
    """Discover community discussions and linked references via Reddit search JSON."""
    urls: List[str] = []
    clean_q = _strip_question_framing(query)
    try:
        url = (
            f"https://www.reddit.com/search.json?q={urllib.parse.quote(clean_q)}"
            f"&limit=6&sort=relevance"
        )
        resp = await client.get(
            url, headers={"User-Agent": NEUTRON_BOT_AGENT}, timeout=4.0
        )
        if resp.status_code == 200:
            children = resp.json().get("data", {}).get("children", [])
            for child in children:
                post = child.get("data", {})
                target = post.get("url_overridden_by_dest") or post.get("url")
                if target and target.startswith("http"):
                    urls.append(target)
                elif post.get("permalink"):
                    urls.append(f"https://www.reddit.com{post['permalink']}")
    except Exception as exc:
        logger.debug("discovery_reddit_skipped", error=str(exc))
    return urls


async def _discover_arxiv(client: httpx.AsyncClient, query: str) -> List[str]:
    """Discover scientific and technical preprints via the public arXiv Atom API."""
    urls: List[str] = []
    clean_q = _strip_question_framing(query)
    try:
        url = (
            f"https://export.arxiv.org/api/query?"
            f"search_query=all:{urllib.parse.quote(clean_q)}&start=0&max_results=5"
        )
        resp = await client.get(
            url, headers={"User-Agent": NEUTRON_BOT_AGENT}, timeout=4.5
        )
        if resp.status_code == 200 and resp.text.lstrip().startswith("<"):
            root = ET.fromstring(resp.text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns):
                id_node = entry.find("atom:id", ns)
                if id_node is not None and id_node.text:
                    paper_url = id_node.text.strip().replace("http://", "https://")
                    if paper_url.startswith("https://"):
                        urls.append(paper_url)
    except Exception as exc:
        logger.debug("discovery_arxiv_skipped", error=str(exc))
    return urls


async def _discover_github(client: httpx.AsyncClient, query: str) -> List[str]:
    """Discover open-source repositories and documentation via GitHub Search API."""
    urls: List[str] = []
    clean_q = _strip_question_framing(query)
    try:
        url = (
            f"https://api.github.com/search/repositories?"
            f"q={urllib.parse.quote(clean_q)}&sort=stars&order=desc&per_page=5"
        )
        resp = await client.get(
            url,
            headers={
                "User-Agent": NEUTRON_BOT_AGENT,
                "Accept": "application/vnd.github+json",
            },
            timeout=4.0,
        )
        if resp.status_code == 200:
            for repo in resp.json().get("items", []):
                html_url = repo.get("html_url")
                if html_url and html_url.startswith("http"):
                    urls.append(html_url)
    except Exception as exc:
        logger.debug("discovery_github_skipped", error=str(exc))
    return urls


async def _discover_brave(client: httpx.AsyncClient, query: str) -> List[str]:
    """Optional Brave Search API adapter when BRAVE_SEARCH_API_KEY is configured."""
    if not settings.BRAVE_SEARCH_API_KEY:
        return []
    urls: List[str] = []
    try:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": 8},
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": settings.BRAVE_SEARCH_API_KEY,
            },
            timeout=4.0,
        )
        if resp.status_code == 200:
            for item in resp.json().get("web", {}).get("results", []):
                target = item.get("url")
                if target and target.startswith("http"):
                    urls.append(target)
    except Exception as exc:
        logger.warning("discovery_brave_failed", error=str(exc))
    return urls


async def _timed_adapter(
    source_name: str,
    coro: Awaitable[List[str]],
) -> Dict[str, Any]:
    t0 = time.perf_counter()
    try:
        urls = await coro
    except Exception as exc:
        logger.warning("discovery_adapter_crashed", source=source_name, error=str(exc))
        urls = []
    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    return {
        "source": source_name,
        "urls": urls,
        "url_count": len(urls),
        "duration_ms": elapsed_ms,
    }


async def discover_seed_urls_detailed(
    query: str,
    max_urls: int = 12,
    on_source_complete: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Run all discovery adapters concurrently and return diverse URLs + telemetry."""
    headers = {
        "User-Agent": _pick_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    discovered: List[str] = []
    metrics: List[Dict[str, Any]] = []

    async with httpx.AsyncClient(
        headers=headers, timeout=5.5, follow_redirects=True
    ) as client:
        adapters: List[Tuple[str, Awaitable[List[str]]]] = [
            ("duckduckgo", _discover_duckduckgo_html(client, query)),
            ("wikipedia", _discover_wikipedia_fulltext(client, query)),
            ("hackernews", _discover_hackernews(client, query)),
            ("reddit", _discover_reddit(client, query)),
            ("arxiv", _discover_arxiv(client, query)),
            ("github", _discover_github(client, query)),
        ]
        if settings.BRAVE_SEARCH_API_KEY:
            adapters.append(("brave", _discover_brave(client, query)))

        tasks = [
            asyncio.create_task(_timed_adapter(name, coro))
            for name, coro in adapters
        ]

        # Prioritize DDG and Wikipedia URLs first once collected, while streaming progress
        by_source: Dict[str, List[str]] = {}
        for completed in asyncio.as_completed(tasks):
            outcome = await completed
            src = outcome["source"]
            by_source[src] = outcome["urls"]
            metric = {
                "source": src,
                "url_count": outcome["url_count"],
                "duration_ms": outcome["duration_ms"],
            }
            metrics.append(metric)
            if on_source_complete is not None:
                await on_source_complete(metric)

        ordered_sources = [
            "brave",
            "duckduckgo",
            "wikipedia",
            "hackernews",
            "arxiv",
            "github",
            "reddit",
        ]
        for src in ordered_sources:
            discovered.extend(by_source.get(src, []))

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

    return diverse_urls, metrics


async def discover_seed_urls(query: str, max_urls: int = 12) -> List[str]:
    """Discover diverse candidate seed URLs across web, encyclopedia, tech, and paper sources."""
    urls, _ = await discover_seed_urls_detailed(query, max_urls=max_urls)
    return urls

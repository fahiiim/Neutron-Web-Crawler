"""Multi-source meta-search discovery adapters resilient against rate limits.

Integrates DuckDuckGo HTML, Wikipedia full-text search, HackerNews Algolia,
Reddit public JSON, arXiv academic search, GitHub repositories, and optional Brave Search.
"""

import asyncio
import random
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple
import urllib.parse
import xml.etree.ElementTree as ET
import httpx
from selectolax.lexbor import LexborHTMLParser

try:
    from .config import settings
    from .db_turso import normalize_search_query
    from .dedup import canonicalize_url, extract_domain_host
    from .logging_utils import get_logger
    from .parser import IGNORED_EXTENSIONS
except ImportError:
    from config import settings
    from db_turso import normalize_search_query
    from dedup import canonicalize_url, extract_domain_host
    from logging_utils import get_logger
    from parser import IGNORED_EXTENSIONS

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

_MULTI_ARTICLE_DOMAINS = {
    "en.wikipedia.org",
    "arxiv.org",
    "github.com",
    "stackoverflow.com",
}


def _pick_user_agent() -> str:
    return random.choice(CHROME_USER_AGENTS)


def _strip_question_framing(query: str) -> str:
    """Normalize conversational question queries to extract key search entities."""
    return normalize_search_query(query)


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


_MODE_ADAPTERS: Dict[str, Set[str]] = {
    "all": {"brave", "duckduckgo", "wikipedia", "hackernews", "reddit", "arxiv", "github"},
    "encyclopedia": {"brave", "wikipedia", "duckduckgo"},
    "papers": {"brave", "arxiv", "wikipedia", "duckduckgo"},
    "code": {"brave", "github", "hackernews", "duckduckgo"},
    "discussions": {"brave", "reddit", "hackernews", "duckduckgo"},
}


def augment_link_query(query: str, mode: str = "all") -> str:
    """Enhance queries with recommendation intent for live web discovery."""
    q = query.strip()
    low = q.lower()
    if q.startswith('"') or q.endswith('"') or len(q.split()) > 7:
        return q
    if any(low.startswith(p) for p in ("how ", "what ", "why ", "when ", "where ", "who ")):
        return q
    if mode == "code" and not any(k in low for k in ("github", "repo", "library", "code")):
        return f"{q} github repository"
    if mode == "papers" and not any(k in low for k in ("arxiv", "paper", "research", "study")):
        return f"{q} research paper arxiv"
    return q


async def discover_seed_urls_detailed(
    query: str,
    max_urls: int = 12,
    on_source_complete: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    mode: str = "all",
    skip_domains: Optional[Set[str]] = None,
    include_domains: Optional[Set[str]] = None,
    exclude_domains: Optional[Set[str]] = None,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Run selected discovery adapters concurrently and return diverse URLs + telemetry."""
    headers = {
        "User-Agent": _pick_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    effective_query = augment_link_query(query, mode=mode)
    allowed_sources = _MODE_ADAPTERS.get((mode or "all").lower(), _MODE_ADAPTERS["all"])
    blocked_domains = set(skip_domains or set())
    if exclude_domains:
        blocked_domains.update(exclude_domains)
    discovered: List[str] = []
    metrics: List[Dict[str, Any]] = []

    async with httpx.AsyncClient(
        headers=headers, timeout=4.5, follow_redirects=True
    ) as client:
        all_adapters: List[Tuple[str, Awaitable[List[str]]]] = [
            ("duckduckgo", _discover_duckduckgo_html(client, effective_query)),
            ("wikipedia", _discover_wikipedia_fulltext(client, effective_query)),
            ("hackernews", _discover_hackernews(client, effective_query)),
            ("reddit", _discover_reddit(client, effective_query)),
            ("arxiv", _discover_arxiv(client, effective_query)),
            ("github", _discover_github(client, effective_query)),
        ]
        if settings.BRAVE_SEARCH_API_KEY:
            all_adapters.append(("brave", _discover_brave(client, query)))

        tasks = []
        for name, coro in all_adapters:
            if name in allowed_sources:
                tasks.append(asyncio.create_task(_timed_adapter(name, coro)))
            elif hasattr(coro, "close"):
                coro.close()

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

    seen_domains: Dict[str, int] = {}
    seen_urls: Set[str] = set()
    diverse_urls: List[str] = []

    candidates_clean: List[Tuple[str, str]] = []
    for raw_url in discovered:
        canonical = canonicalize_url(raw_url)
        if not canonical or canonical in seen_urls:
            continue
        url_path = urllib.parse.urlsplit(canonical).path.lower()
        if url_path.endswith(IGNORED_EXTENSIONS):
            continue
        domain = extract_domain_host(canonical)
        if domain in blocked_domains:
            continue
        if include_domains and domain not in include_domains:
            continue
        seen_urls.add(canonical)
        candidates_clean.append((canonical, domain))

    # Pass 1: maximize domain diversity (1 URL per domain)
    for canonical, domain in candidates_clean:
        if domain not in seen_domains:
            seen_domains[domain] = 1
            diverse_urls.append(canonical)
        if len(diverse_urls) >= max_urls:
            break

    # Pass 2: backfill remaining slots from multi-article knowledge hubs when needed
    if len(diverse_urls) < max_urls:
        selected_set = set(diverse_urls)
        for canonical, domain in candidates_clean:
            if canonical in selected_set or domain not in _MULTI_ARTICLE_DOMAINS:
                continue
            if seen_domains.get(domain, 0) < 2:
                seen_domains[domain] = seen_domains.get(domain, 0) + 1
                diverse_urls.append(canonical)
                selected_set.add(canonical)
            if len(diverse_urls) >= max_urls:
                break

    return diverse_urls, metrics


async def discover_seed_urls(
    query: str,
    max_urls: int = 12,
    mode: str = "all",
    skip_domains: Optional[Set[str]] = None,
    include_domains: Optional[Set[str]] = None,
    exclude_domains: Optional[Set[str]] = None,
) -> List[str]:
    """Discover diverse candidate seed URLs across web, encyclopedia, tech, and paper sources."""
    urls, _ = await discover_seed_urls_detailed(
        query,
        max_urls=max_urls,
        mode=mode,
        skip_domains=skip_domains,
        include_domains=include_domains,
        exclude_domains=exclude_domains,
    )
    return urls

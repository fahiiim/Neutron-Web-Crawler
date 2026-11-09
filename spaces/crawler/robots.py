"""Asynchronous in-memory cached robots.txt parser and politeness manager."""

import asyncio
import time
from typing import Dict, Optional, Set
import urllib.parse
import urllib.robotparser
import httpx

USER_AGENT = "NeutronBot"


class RobotsTxtManager:
    """Manages asynchronous fetching, parsing, and caching of robots.txt files."""

    def __init__(self, cache_ttl_seconds: int = 86400) -> None:
        self._cache_ttl = cache_ttl_seconds
        # Mapping: domain -> (urllib.robotparser.RobotFileParser, timestamp)
        self._parsers: Dict[str, tuple[urllib.robotparser.RobotFileParser, float]] = {}
        self._lock = asyncio.Lock()

    async def is_allowed(self, target_url: str) -> bool:
        """Verify whether crawling the target URL is permitted by robots.txt.

        Args:
            target_url: The canonical URL to inspect.

        Returns:
            True if allowed (or if robots.txt is unavailable), False if disallowed.
        """
        try:
            parsed = urllib.parse.urlsplit(target_url)
            domain = parsed.netloc.lower()
            if not domain:
                return True

            parser = await self._get_or_fetch_parser(parsed.scheme, domain)
            if parser is None:
                return True

            return parser.can_fetch(USER_AGENT, target_url)
        except Exception as exc:
            print(f"[Robots.txt Check Warning for {target_url}]: {exc}")
            return True

    async def get_crawl_delay(self, target_url: str) -> Optional[float]:
        """Retrieve Crawl-delay directive for the domain if specified.

        Args:
            target_url: Source URL string.

        Returns:
            Crawl delay in seconds, or None if unspecified.
        """
        try:
            parsed = urllib.parse.urlsplit(target_url)
            domain = parsed.netloc.lower()
            parser = await self._get_or_fetch_parser(parsed.scheme, domain)
            if parser is not None:
                delay = parser.crawl_delay(USER_AGENT)
                if delay is not None:
                    return float(delay)
        except Exception:
            pass
        return None

    async def _get_or_fetch_parser(
        self, scheme: str, domain: str
    ) -> Optional[urllib.robotparser.RobotFileParser]:
        """Fetch robots.txt from remote host or retrieve from active in-memory cache."""
        now = time.time()
        async with self._lock:
            if domain in self._parsers:
                parser, cached_at = self._parsers[domain]
                if (now - cached_at) < self._cache_ttl:
                    return parser

        # Fetch over network with strict timeout
        robots_url = f"{scheme}://{domain}/robots.txt"
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)

        try:
            async with httpx.AsyncClient(timeout=3.0, follow_redirects=True) as client:
                resp = await client.get(robots_url)
                if resp.status_code == 200:
                    parser.parse(resp.text.splitlines())
                elif resp.status_code in (401, 403):
                    # Forbidden means disallow everything
                    parser.disallow_all = True
                else:
                    # 404 or other errors mean allow all
                    parser.allow_all = True
        except Exception:
            parser.allow_all = True

        async with self._lock:
            self._parsers[domain] = (parser, now)

        return parser


robots_manager = RobotsTxtManager()

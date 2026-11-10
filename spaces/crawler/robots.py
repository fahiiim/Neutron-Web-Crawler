"""Asynchronous per-domain cached robots.txt parser and politeness manager."""

import asyncio
import time
from typing import Dict, List, Optional, Tuple
import urllib.parse
import urllib.robotparser
import httpx

try:
    from .logging_utils import get_logger
except ImportError:
    from logging_utils import get_logger

logger = get_logger("neutron.robots")

ROBOTS_TOKEN = "NeutronBot"
USER_AGENT = "NeutronBot/3.0 (+https://github.com/fahiiim/Neutron-Web-Crawler)"


def _extract_float_crawl_delay(lines: List[str]) -> Optional[float]:
    """Parse fractional or integer Crawl-delay directives ignored by stdlib parser."""
    in_matching_group = False
    fallback_delay: Optional[float] = None
    specific_delay: Optional[float] = None
    specific_match = False

    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, val = [part.strip() for part in line.split(":", 1)]
        low_key = key.lower()
        if low_key == "user-agent":
            ua = val.lower()
            if ROBOTS_TOKEN.lower() in ua:
                in_matching_group = True
                specific_match = True
            elif ua == "*":
                in_matching_group = True
                specific_match = False
            else:
                in_matching_group = False
                specific_match = False
        elif low_key == "crawl-delay" and in_matching_group:
            try:
                parsed_delay = max(0.0, min(60.0, float(val)))
                if specific_match:
                    specific_delay = parsed_delay
                elif fallback_delay is None:
                    fallback_delay = parsed_delay
            except ValueError:
                continue

    return specific_delay if specific_delay is not None else fallback_delay


class RobotsTxtManager:
    """Manages asynchronous fetching, parsing, and per-domain caching of robots.txt."""

    def __init__(self, cache_ttl_seconds: int = 86400) -> None:
        self._cache_ttl = cache_ttl_seconds
        self._parsers: Dict[str, Tuple[urllib.robotparser.RobotFileParser, float]] = {}
        self._float_delays: Dict[str, Optional[float]] = {}
        self._domain_locks: Dict[str, asyncio.Lock] = {}
        self._meta_lock = asyncio.Lock()

    async def _get_domain_lock(self, domain: str) -> asyncio.Lock:
        async with self._meta_lock:
            lock = self._domain_locks.get(domain)
            if lock is None:
                lock = asyncio.Lock()
                self._domain_locks[domain] = lock
            return lock

    async def is_allowed(self, target_url: str) -> bool:
        """Verify whether crawling the target URL is permitted by robots.txt."""
        try:
            parsed = urllib.parse.urlsplit(target_url)
            domain = parsed.netloc.lower()
            if not domain:
                return True

            parser = await self._get_or_fetch_parser(parsed.scheme or "https", domain)
            if parser is None:
                return True

            return parser.can_fetch(ROBOTS_TOKEN, target_url)
        except Exception:
            logger.warning("robots_check_failed", url=target_url, exc_info=True)
            return True

    async def get_crawl_delay(self, target_url: str) -> Optional[float]:
        """Retrieve Crawl-delay directive (supports integer and float values)."""
        try:
            parsed = urllib.parse.urlsplit(target_url)
            domain = parsed.netloc.lower()
            if not domain:
                return None
            parser = await self._get_or_fetch_parser(parsed.scheme or "https", domain)
            if parser is not None:
                delay = parser.crawl_delay(ROBOTS_TOKEN)
                if delay is not None:
                    return float(delay)
                return self._float_delays.get(domain)
        except Exception:
            logger.debug("robots_crawl_delay_failed", url=target_url, exc_info=True)
        return None

    async def get_sitemaps(self, target_url: str) -> List[str]:
        """Return any Sitemap URLs advertised inside the domain's robots.txt."""
        try:
            parsed = urllib.parse.urlsplit(target_url)
            domain = parsed.netloc.lower()
            if not domain:
                return []
            parser = await self._get_or_fetch_parser(parsed.scheme or "https", domain)
            if parser is not None and hasattr(parser, "site_maps"):
                sitemaps = parser.site_maps()
                if sitemaps:
                    return list(sitemaps)
        except Exception:
            logger.debug("robots_sitemap_lookup_failed", url=target_url, exc_info=True)
        return []

    async def _get_or_fetch_parser(
        self, scheme: str, domain: str
    ) -> Optional[urllib.robotparser.RobotFileParser]:
        """Fetch robots.txt from remote host or retrieve from per-domain cache."""
        now = time.time()
        cached = self._parsers.get(domain)
        if cached and (now - cached[1]) < self._cache_ttl:
            return cached[0]

        domain_lock = await self._get_domain_lock(domain)
        async with domain_lock:
            now = time.time()
            cached = self._parsers.get(domain)
            if cached and (now - cached[1]) < self._cache_ttl:
                return cached[0]

            robots_url = f"{scheme}://{domain}/robots.txt"
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(robots_url)
            float_delay: Optional[float] = None

            try:
                async with httpx.AsyncClient(
                    timeout=3.0,
                    follow_redirects=True,
                    headers={"User-Agent": USER_AGENT},
                ) as client:
                    resp = await client.get(robots_url)
                    if resp.status_code == 200:
                        lines = resp.text.splitlines()
                        parser.parse(lines)
                        float_delay = _extract_float_crawl_delay(lines)
                    elif resp.status_code in (401, 403):
                        parser.disallow_all = True
                    else:
                        parser.allow_all = True
            except Exception as exc:
                logger.debug("robots_fetch_fallback_allow", domain=domain, error=str(exc))
                parser.allow_all = True

            self._parsers[domain] = (parser, time.time())
            self._float_delays[domain] = float_delay
            return parser


robots_manager = RobotsTxtManager()

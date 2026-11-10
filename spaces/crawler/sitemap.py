"""Sitemap.xml and Sitemap Index parser for high-efficiency URL discovery."""

import gzip
from typing import List, Optional, Set
import xml.etree.ElementTree as ET
import httpx

try:
    from .dedup import canonicalize_url
    from .logging_utils import get_logger
    from .parser import IGNORED_EXTENSIONS
except ImportError:
    from dedup import canonicalize_url
    from logging_utils import get_logger
    from parser import IGNORED_EXTENSIONS

logger = get_logger("neutron.sitemap")

_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def _local_tag(tag: str) -> str:
    """Strip XML namespace prefix from an ElementTree tag name."""
    if "}" in tag:
        return tag.split("}", 1)[1].lower()
    return tag.lower()


def _decode_sitemap_payload(resp: httpx.Response, url: str) -> str:
    """Decode plain XML or gzipped XML sitemap responses safely."""
    content = resp.content
    if url.lower().endswith(".gz") or resp.headers.get("content-type", "").endswith("gzip"):
        try:
            content = gzip.decompress(content)
        except Exception:
            pass
    return content.decode("utf-8", errors="replace")


async def _parse_single_sitemap(
    client: httpx.AsyncClient,
    sitemap_url: str,
    max_urls: int,
    depth: int,
    visited: Set[str],
    collected: List[str],
) -> None:
    if len(collected) >= max_urls or depth > 2 or sitemap_url in visited:
        return
    visited.add(sitemap_url)

    try:
        resp = await client.get(sitemap_url, timeout=5.0)
        if resp.status_code != 200:
            return

        xml_text = _decode_sitemap_payload(resp, sitemap_url)
        if not xml_text.strip().startswith("<"):
            return

        root = ET.fromstring(xml_text)
        root_name = _local_tag(root.tag)

        if root_name == "sitemapindex":
            child_sitemaps: List[str] = []
            for elem in root:
                if _local_tag(elem.tag) == "sitemap":
                    for child in elem:
                        if _local_tag(child.tag) == "loc" and child.text:
                            child_sitemaps.append(child.text.strip())
                            break
                if len(child_sitemaps) >= 5:
                    break

            for child_url in child_sitemaps:
                if len(collected) >= max_urls:
                    break
                await _parse_single_sitemap(
                    client, child_url, max_urls, depth + 1, visited, collected
                )
            return

        if root_name == "urlset":
            for elem in root:
                if _local_tag(elem.tag) != "url":
                    continue
                for child in elem:
                    if _local_tag(child.tag) == "loc" and child.text:
                        canonical = canonicalize_url(child.text.strip())
                        if canonical and not canonical.lower().endswith(IGNORED_EXTENSIONS):
                            if canonical not in collected:
                                collected.append(canonical)
                        break
                if len(collected) >= max_urls:
                    break
    except Exception as exc:
        logger.debug("sitemap_parse_skipped", sitemap_url=sitemap_url, error=str(exc))


async def discover_sitemap_urls(
    client: httpx.AsyncClient,
    domain: str,
    max_urls: int = 50,
    extra_sitemap_urls: Optional[List[str]] = None,
) -> List[str]:
    """Discover canonical URLs from a domain's sitemap.xml or robots-declared sitemaps."""
    candidates: List[str] = []
    if extra_sitemap_urls:
        candidates.extend(extra_sitemap_urls[:3])

    clean_domain = domain.strip().lower()
    if clean_domain:
        default_sitemap = f"https://{clean_domain}/sitemap.xml"
        if default_sitemap not in candidates:
            candidates.append(default_sitemap)

    collected: List[str] = []
    visited: Set[str] = set()
    for sitemap_url in candidates:
        if len(collected) >= max_urls:
            break
        await _parse_single_sitemap(
            client, sitemap_url, max_urls, depth=0, visited=visited, collected=collected
        )
    return collected[:max_urls]

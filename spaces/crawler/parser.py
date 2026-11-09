"""High-speed HTML parsing, SSR JSON extraction, and outbound link discovery."""

import json
from typing import Any, Dict, List
import urllib.parse
try:
    from selectolax.lexbor import LexborHTMLParser as HTMLParser
except ImportError:
    from selectolax.parser import HTMLParser

from dedup import canonicalize_url

IGNORED_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".mp4",
    ".mp3",
    ".css",
    ".js",
)


def extract_outbound_links(tree: HTMLParser, base_url: str) -> List[Dict[str, Any]]:
    """Extract and canonicalize outbound hyperlink references.

    Args:
        tree: Parsed Selectolax DOM tree.
        base_url: Document base URL for relative link resolution.

    Returns:
        List of link dictionaries containing canonical URL and anchor text.
    """
    links: List[Dict[str, Any]] = []
    for anchor in tree.css("a[href]"):
        href = anchor.attributes.get("href", "").strip()
        anchor_text = anchor.text(strip=True)[:100]

        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue

        resolved = urllib.parse.urljoin(base_url, href)
        canonical = canonicalize_url(resolved)
        if not canonical or canonical.endswith(IGNORED_EXTENSIONS):
            continue

        links.append({"url": canonical, "anchor": anchor_text})
    return links


def parse_page_content(html: str, base_url: str) -> Dict[str, Any]:
    """Extract page title, meta snippet, cleaned article text, and outbound links.

    Uses a zero-browser extraction hierarchy:
    1. Inspects __NEXT_DATA__ or __NUXT__ SSR state for instant clean JSON.
    2. Uses Selectolax for high-speed CSS tree traversal.

    Args:
        html: Raw HTML page content.
        base_url: Source page URL.

    Returns:
        Dictionary with title, snippet, text, outbound links, and SPA flag.
    """
    tree = HTMLParser(html)

    # 1. Zero-Browser Next.js State Extraction
    next_data_node = tree.css_first("script#__NEXT_DATA__")
    if next_data_node and next_data_node.text():
        try:
            payload = json.loads(next_data_node.text())
            page_props = payload.get("props", {}).get("pageProps", {})
            title = page_props.get("title") or page_props.get("name")
            desc = page_props.get("description") or page_props.get("summary")
            if title and desc:
                return {
                    "title": str(title)[:200],
                    "snippet": str(desc)[:400],
                    "text": f"{title}\n\n{desc}",
                    "is_spa_empty": False,
                    "links": extract_outbound_links(tree, base_url),
                }
        except Exception:
            pass

    # 2. Extract standard semantic HTML metadata
    title_node = tree.css_first("title")
    title = title_node.text().strip() if title_node else "Untitled Document"

    desc_node = tree.css_first('meta[name="description"]') or tree.css_first(
        'meta[property="og:description"]'
    )
    snippet = desc_node.attributes.get("content", "").strip() if desc_node else ""

    # Collect outbound links prior to cleaning DOM tree
    links = extract_outbound_links(tree, base_url)

    # Decompose script, style, navigation, and advertisement elements
    for junk in tree.css("script, style, noscript, svg, nav, footer, header"):
        junk.decompose()

    text_blocks: List[str] = []
    for node in tree.css("h1, h2, h3, p"):
        text = node.text(strip=True)
        if text and len(text) > 20:
            text_blocks.append(text)

    full_text = "\n\n".join(text_blocks)
    if not snippet and text_blocks:
        snippet = text_blocks[0][:300]

    is_spa_empty = len(full_text) < 150 and bool(
        tree.css_first("#root, #app, #__next")
    )

    return {
        "title": title[:200],
        "snippet": snippet[:400] if snippet else full_text[:400],
        "text": full_text,
        "is_spa_empty": is_spa_empty,
        "links": links,
    }


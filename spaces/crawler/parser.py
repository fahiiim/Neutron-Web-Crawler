"""High-speed HTML parsing, SSR JSON/JSON-LD extraction, and outbound link discovery."""

import json
from typing import Any, Dict, List, Optional, Set
import urllib.parse

try:
    from selectolax.lexbor import LexborHTMLParser as HTMLParser
except ImportError:
    from selectolax.parser import HTMLParser

try:
    from .dedup import canonicalize_url
except ImportError:
    from dedup import canonicalize_url

IGNORED_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp",
    ".pdf", ".zip", ".tar", ".gz", ".rar", ".7z",
    ".mp4", ".mp3", ".webm", ".avi", ".mov", ".wav", ".ogg",
    ".css", ".js", ".mjs", ".map",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".xml", ".rss", ".atom", ".exe", ".dmg", ".apk",
)

_NOFOLLOW_TOKENS = {"nofollow", "sponsored", "ugc"}

_MAIN_CONTENT_SELECTORS = (
    "article",
    "main",
    "[role='main']",
    ".post-content",
    ".article-body",
    ".entry-content",
    ".markdown-body",
)

_BLOCK_SELECTORS = (
    "h1, h2, h3, h4, p, li, blockquote, pre, td, th, figcaption, summary, details"
)

_JUNK_SELECTORS = (
    "script, style, noscript, svg, nav, footer, aside, "
    "[role='navigation'], [role='complementary'], "
    ".cookie-banner, .cookie-consent, .advertisement, .ads, .sidebar"
)

_WAF_EXACT_TITLES = {
    "just a moment...",
    "just a moment",
    "attention required! | cloudflare",
    "please wait... | cloudflare",
    "access denied",
    "403 forbidden",
    "404 not found",
    "error 403",
    "error 1020",
    "pardon our interruption",
    "are you a robot?",
    "robot or human?",
    "verify you are human",
    "checking your browser",
    "ddos-guard",
}

_WAF_PREFIX_TITLES = (
    "just a moment",
    "attention required! | cloudflare",
    "access denied |",
    "error 1020",
    "error 1015",
    "please wait...",
)

_WAF_BODY_MARKERS = (
    "performing security verification",
    "enable javascript and cookies to continue",
    "checking if the site connection is secure",
    "why have i been blocked",
    "action you just performed triggered the security solution",
    "cloudflare ray id",
    "ddos protection by cloudflare",
    "you don't have permission to access",
    "pardon our interruption",
    "please verify you are a human",
    "verify you are human by completing the action below",
)


def is_waf_or_empty_page(title: str, text: str) -> bool:
    """Detect Cloudflare/Akamai/bot-challenge interstitials and near-empty shells."""
    clean_text = (text or "").strip()
    if len(clean_text) < 50:
        return True

    low_title = " ".join((title or "").lower().split())
    if low_title in _WAF_EXACT_TITLES or low_title.startswith(_WAF_PREFIX_TITLES):
        return True

    if low_title == "untitled document" and len(clean_text) < 200:
        return True

    low_text = clean_text.lower()
    if len(clean_text) < 2000 and any(marker in low_text for marker in _WAF_BODY_MARKERS):
        return True

    return False


def extract_outbound_links(tree: HTMLParser, base_url: str) -> List[Dict[str, Any]]:
    """Extract and canonicalize followable outbound hyperlink references."""
    links: List[Dict[str, Any]] = []
    seen_urls: Set[str] = set()

    for anchor in tree.css("a[href]"):
        rel_raw = (anchor.attributes.get("rel") or "").lower()
        rel_tokens = set(rel_raw.split())
        if rel_tokens & _NOFOLLOW_TOKENS:
            continue

        href = (anchor.attributes.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            continue

        resolved = urllib.parse.urljoin(base_url, href)
        canonical = canonicalize_url(resolved)
        if not canonical or canonical.lower().endswith(IGNORED_EXTENSIONS):
            continue

        if canonical in seen_urls:
            continue
        seen_urls.add(canonical)

        anchor_text = anchor.text(strip=True)[:100]
        links.append({"url": canonical, "anchor": anchor_text})

    return links


def _extract_json_ld_metadata(tree: HTMLParser) -> Dict[str, Optional[str]]:
    """Extract structured Schema.org metadata from JSON-LD scripts."""
    meta: Dict[str, Optional[str]] = {
        "title": None,
        "description": None,
        "author": None,
        "published_at": None,
        "article_body": None,
    }
    for script_node in tree.css('script[type="application/ld+json"]'):
        raw_json = script_node.text()
        if not raw_json:
            continue
        try:
            data = json.loads(raw_json)
            items = data if isinstance(data, list) else [data]
            if isinstance(data, dict) and isinstance(data.get("@graph"), list):
                items.extend(data["@graph"])
            for item in items:
                if not isinstance(item, dict):
                    continue
                meta["title"] = meta["title"] or item.get("headline") or item.get("name")
                meta["description"] = meta["description"] or item.get("description")
                meta["published_at"] = meta["published_at"] or item.get("datePublished")
                meta["article_body"] = meta["article_body"] or item.get("articleBody")
                author = item.get("author")
                if not meta["author"] and author:
                    if isinstance(author, dict):
                        meta["author"] = author.get("name")
                    elif isinstance(author, list) and author and isinstance(author[0], dict):
                        meta["author"] = author[0].get("name")
                    elif isinstance(author, str):
                        meta["author"] = author
        except Exception:
            continue
    return meta


def _format_node_as_markdown(node: Any) -> Optional[str]:
    """Convert a parsed HTML block node into clean Markdown syntax."""
    tag = (node.tag or "").lower()
    text = node.text(strip=True)
    if not text:
        return None

    if tag == "h1":
        return f"# {text}"
    if tag == "h2":
        return f"## {text}"
    if tag == "h3":
        return f"### {text}"
    if tag == "h4":
        return f"#### {text}"
    if tag == "blockquote":
        return f"> {text}"
    if tag == "li":
        return f"- {text}"
    if tag == "pre":
        return f"```\n{text}\n```"
    if len(text) <= 15:
        return None
    return text


def parse_page_content(html: str, base_url: str) -> Dict[str, Any]:
    """Extract page title, meta snippet, structured Markdown, and outbound links."""
    tree = HTMLParser(html)

    html_node = tree.css_first("html")
    language = (html_node.attributes.get("lang") or "").strip()[:16] if html_node else ""

    # Collect followable outbound links prior to DOM cleanup
    links = extract_outbound_links(tree, base_url)
    json_ld = _extract_json_ld_metadata(tree)

    # 1. Zero-Browser Next.js State Extraction
    next_data_node = tree.css_first("script#__NEXT_DATA__")
    if next_data_node and next_data_node.text():
        try:
            payload = json.loads(next_data_node.text())
            page_props = payload.get("props", {}).get("pageProps", {})
            ssr_title = page_props.get("title") or page_props.get("name")
            ssr_desc = page_props.get("description") or page_props.get("summary")
            ssr_body = page_props.get("content") or page_props.get("body")
            if ssr_title and (ssr_desc or ssr_body):
                md_text = f"# {ssr_title}\n\n{ssr_body or ssr_desc}"
                return {
                    "title": str(ssr_title)[:200],
                    "snippet": str(ssr_desc or ssr_body)[:400],
                    "text": md_text,
                    "is_spa_empty": False,
                    "links": links,
                    "language": language,
                    "author": json_ld.get("author"),
                    "published_at": json_ld.get("published_at"),
                }
        except Exception:
            pass

    # 2. Extract standard semantic HTML + OpenGraph + JSON-LD + H1 metadata
    title_node = tree.css_first("title")
    og_title_node = tree.css_first('meta[property="og:title"]')
    h1_node = tree.css_first("h1")
    title = (
        (title_node.text().strip() if title_node else "")
        or (og_title_node.attributes.get("content", "").strip() if og_title_node else "")
        or (str(json_ld["title"]).strip() if json_ld.get("title") else "")
        or (h1_node.text(strip=True) if h1_node else "")
        or "Untitled Document"
    )

    desc_node = (
        tree.css_first('meta[name="description"]')
        or tree.css_first('meta[property="og:description"]')
        or tree.css_first('meta[name="twitter:description"]')
    )
    snippet = (
        (desc_node.attributes.get("content", "").strip() if desc_node else "")
        or (str(json_ld["description"]).strip() if json_ld.get("description") else "")
    )

    pub_node = tree.css_first('meta[property="article:published_time"]')
    published_at = (
        (pub_node.attributes.get("content", "").strip() if pub_node else None)
        or json_ld.get("published_at")
    )

    # Decompose navigation, scripts, styles, and ad containers
    for junk in tree.css(_JUNK_SELECTORS):
        junk.decompose()

    # Prefer focused main/article container when substantial
    scope_node: Any = tree
    for selector in _MAIN_CONTENT_SELECTORS:
        candidate = tree.css_first(selector)
        if candidate and len(candidate.text(strip=True)) >= 200:
            scope_node = candidate
            break

    text_blocks: List[str] = []
    seen_blocks: Set[str] = set()
    for node in scope_node.css(_BLOCK_SELECTORS):
        md_line = _format_node_as_markdown(node)
        if not md_line:
            continue
        norm_key = md_line.lstrip("#>- ").strip()
        if norm_key in seen_blocks:
            continue
        seen_blocks.add(norm_key)
        text_blocks.append(md_line)

    full_text = "\n\n".join(text_blocks)
    if len(full_text) < 120 and json_ld.get("article_body"):
        full_text = f"# {title}\n\n{json_ld['article_body']}"

    if not snippet and text_blocks:
        snippet = text_blocks[0].lstrip("#>- ").strip()[:300]

    is_waf_blocked = is_waf_or_empty_page(title, full_text)
    is_spa_empty = (len(full_text) < 150 and bool(
        tree.css_first("#root, #app, #__next")
    ))

    return {
        "title": title[:200],
        "snippet": snippet[:400] if snippet else full_text[:400],
        "text": full_text,
        "is_spa_empty": is_spa_empty,
        "is_waf_blocked": is_waf_blocked,
        "links": links,
        "language": language,
        "author": json_ld.get("author"),
        "published_at": published_at,
    }

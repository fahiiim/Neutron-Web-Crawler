import asyncio
import json
import time
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel
from curl_cffi.requests import AsyncSession
from selectolax.parser import HTMLParser
import httpx

from shared.config import settings
from shared.db_turso import turso_db
from shared.storage_r2 import r2_storage
from shared.compression import compress_text
from shared.dedup import (
    canonicalize_url,
    hash_url,
    extract_domain_host,
    hash_domain,
    compute_simhash
)

app = FastAPI(
    title="Neutron Fast Crawler & Extractor Microservice",
    description="Dual-lane async crawler: JIT real-time burst fetches + 27k/day background crawl."
)

class JITCrawlRequest(BaseModel):
    query: str
    max_pages: int = 8

def verify_internal_auth(authorization: Optional[str] = Header(None)):
    """Ensure only the internal API Gateway or K8s ingress can invoke crawler endpoints."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")
    token = authorization.split(" ")[1]
    if token != settings.INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid internal API key")

@app.on_event("startup")
async def on_startup():
    await turso_db.connect()
    print("[Crawler] Connected to Turso DB.")

@app.on_event("shutdown")
async def on_shutdown():
    await turso_db.close()

@app.get("/health")
async def health():
    return {"status": "ok", "service": "svc-crawler-worker"}

# --------------------------------------------------------------------------
# SEED DISCOVERY ADAPTERS (Datacenter IP Resilient)
# --------------------------------------------------------------------------
async def discover_seed_urls(query: str, max_urls: int = 12) -> List[str]:
    """
    Query multiple resilient search discovery endpoints:
    Uses Wikipedia API + HackerNews Tech API + DuckDuckGo HTML fallback.
    """
    discovered = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36"}

    async with httpx.AsyncClient(timeout=3.0, headers=headers) as client:
        # 1. Wikipedia OpenSearch API (Ultra-fast, authoritative, never blocks datacenter IPs)
        try:
            wiki_url = f"https://en.wikipedia.org/w/api.php?action=opensearch&search={query}&limit=5&namespace=0&format=json"
            r = await client.get(wiki_url)
            if r.status_code == 200:
                data = r.json()
                if len(data) >= 4 and isinstance(data[3], list):
                    discovered.extend(data[3])
        except Exception as e:
            print(f"[Seed Wiki Error]: {e}")

        # 2. HackerNews / Tech Algolia API (Incredible for programming, engineering, dev topics)
        try:
            hn_url = f"https://hn.algolia.com/api/v1/search?query={query}&tags=story&hitsPerPage=6"
            r = await client.get(hn_url)
            if r.status_code == 200:
                hits = r.json().get("hits", [])
                for h in hits:
                    story_url = h.get("url")
                    if story_url:
                        discovered.append(story_url)
        except Exception as e:
            print(f"[Seed HN Error]: {e}")

    # Canonicalize and apply domain diversity (at most 1 URL per domain in the immediate batch)
    seen_domains = set()
    diverse_urls = []
    for raw in discovered:
        canon = canonicalize_url(raw)
        if not canon:
            continue
        domain = extract_domain_host(canon)
        if domain not in seen_domains:
            seen_domains.add(domain)
            diverse_urls.append(canon)
        if len(diverse_urls) >= max_urls:
            break

    return diverse_urls

# --------------------------------------------------------------------------
# ZERO-BROWSER SSR JSON EXTRACTOR & SELECTOLAX PARSER
# --------------------------------------------------------------------------
def extract_page_data(html: str, url: str) -> Dict[str, Any]:
    """
    Extracts title, meta snippet, and clean markdown text:
    Stage 1: Inspect Next.js / Nuxt / JSON-LD embedded data.
    Stage 2: Selectolax fast HTML DOM parsing.
    """
    tree = HTMLParser(html)

    # 1. Try Next.js __NEXT_DATA__
    next_data_node = tree.css_first("script#__NEXT_DATA__")
    if next_data_node and next_data_node.text():
        try:
            nd = json.loads(next_data_node.text())
            page_props = nd.get("props", {}).get("pageProps", {})
            title = page_props.get("title") or page_props.get("name")
            desc = page_props.get("description") or page_props.get("summary")
            if title and desc:
                return {
                    "title": str(title)[:200],
                    "snippet": str(desc)[:400],
                    "text": f"{title}\n\n{desc}",
                    "is_spa_empty": False
                }
        except Exception:
            pass

    # 2. Extract Standard HTML tags
    title_node = tree.css_first("title")
    title = title_node.text().strip() if title_node else "Untitled Page"

    # Meta description / OpenGraph
    desc_node = tree.css_first('meta[name="description"]') or tree.css_first('meta[property="og:description"]')
    snippet = desc_node.attributes.get("content", "").strip() if desc_node else ""

    # Strip junk tags: scripts, styles, svg, forms, nav, footer
    for junk in tree.css("script, style, noscript, svg, nav, footer, header"):
        junk.decompose()

    # Extract text from paragraphs and headings
    text_blocks = []
    for node in tree.css("h1, h2, h3, p"):
        txt = node.text(strip=True)
        if txt and len(txt) > 20:
            text_blocks.append(txt)

    full_text = "\n\n".join(text_blocks)
    if not snippet and text_blocks:
        snippet = text_blocks[0][:300]

    is_spa_empty = len(full_text) < 150 and bool(tree.css_first("#root, #app, #__next"))

    return {
        "title": title[:200],
        "snippet": snippet[:400] if snippet else full_text[:400],
        "text": full_text,
        "is_spa_empty": is_spa_empty
    }

# --------------------------------------------------------------------------
# SINGLE URL FETCH WORKER (curl_cffi JA3/JA4 Impersonation)
# --------------------------------------------------------------------------
async def fetch_and_index_url(session: AsyncSession, url: str) -> Optional[Dict[str, Any]]:
    """Fetch URL with Chrome TLS fingerprint impersonation and index to Turso & R2."""
    try:
        t0 = time.time()
        resp = await session.get(url, timeout=3.5)
        if resp.status_code != 200:
            return None

        content_type = resp.headers.get("content-type", "")
        if "text/html" not in content_type:
            return None

        html = resp.text
        extracted = extract_page_data(html, url)

        # Stage 3 Escalation: If page is an empty client-side SPA, escalate to svc-stealth-renderer
        if extracted["is_spa_empty"]:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    rend_resp = await client.post(
                        f"{settings.RENDERER_SERVICE_URL}/render",
                        json={"url": url},
                        headers={"Authorization": f"Bearer {settings.INTERNAL_API_KEY}"}
                    )
                    if rend_resp.status_code == 200:
                        rendered_data = rend_resp.json()
                        extracted["title"] = rendered_data.get("title", extracted["title"])
                        extracted["text"] = rendered_data.get("text", extracted["text"])
                        extracted["snippet"] = rendered_data.get("snippet", extracted["snippet"])
            except Exception as e:
                print(f"[Renderer Escalation Error]: {e}")

        u_hash = hash_url(url)
        d_hash = hash_domain(extract_domain_host(url))
        simhash = compute_simhash(extracted["text"])

        # Compress text payload with Zstandard
        compressed_payload = compress_text(extracted["text"])
        chunk_key = f"chunk_{time.strftime('%Y%m%d')}.zst"
        offset = 0
        length = len(compressed_payload)

        # Upload payload to Cloudflare R2
        await r2_storage.put_chunk(chunk_key, compressed_payload)

        # Write metadata & full-text index into Turso FTS5
        await turso_db.insert_search_index(
            url_hash=u_hash,
            domain_hash=d_hash,
            canonical_url=url,
            title=extracted["title"],
            snippet=extracted["snippet"],
            r2_batch_id=chunk_key,
            r2_byte_offset=offset,
            r2_byte_length=length,
            opic_authority=0.25,
            simhash=simhash
        )

        return {
            "url_hash": u_hash,
            "url": url,
            "title": extracted["title"],
            "snippet": extracted["snippet"],
            "score": 1.0
        }
    except Exception as e:
        print(f"[Fetch Error for {url}]: {e}")
        return None

# --------------------------------------------------------------------------
# JIT CRAWL ENDPOINT (Invoked by svc-search-gateway)
# --------------------------------------------------------------------------
@app.post("/crawl/jit", dependencies=[Depends(verify_internal_auth)])
async def crawl_jit(req: JITCrawlRequest):
    """
    Just-In-Time Burst Crawl:
    1. Queries discovery seeds.
    2. Fetches candidates in parallel via curl_cffi (<600ms).
    3. Indexes to Turso and returns immediately.
    """
    candidate_urls = await discover_seed_urls(req.query, max_urls=req.max_pages)
    if not candidate_urls:
        return {"query": req.query, "results": []}

    results = []
    async with AsyncSession(impersonate="chrome124") as session:
        tasks = [fetch_and_index_url(session, u) for u in candidate_urls]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        for item in completed:
            if isinstance(item, dict) and item:
                results.append(item)

    return {"query": req.query, "total": len(results), "results": results}


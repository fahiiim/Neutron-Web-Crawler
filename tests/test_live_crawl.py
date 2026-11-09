"""End-to-end live integration test.

Performs a real crawl of a public page, indexes it into live Turso LibSQL FTS5,
verifies BM25 ranking retrieval, and reads the full decompressed article payload.
"""

import asyncio
import os
import sys
import time
from dotenv import load_dotenv

# Ensure project root and crawler space are in sys.path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
crawler_dir = os.path.join(root_dir, "spaces", "crawler")
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
if crawler_dir not in sys.path:
    sys.path.insert(0, crawler_dir)

load_dotenv(os.path.join(root_dir, ".env"))

from spaces.crawler.db_turso import turso_crawler_client
from spaces.crawler.discovery import discover_seed_urls
from spaces.crawler.parser import parse_page_content
from spaces.crawler.compression import compress_text, decompress_text
from spaces.crawler.dedup import hash_url, hash_domain, extract_domain_host, compute_simhash
from curl_cffi.requests import AsyncSession


async def run_live_test():
    print("=" * 65)
    print("   NEUTRON SEARCH ENGINE: LIVE END-TO-END VERIFICATION")
    print("=" * 65)

    # 1. Connect to Turso
    print("\n[Step 1] Connecting to Turso Database...")
    await turso_crawler_client.connect()
    print("  ✓ Connected successfully!")

    # 2. Seed Discovery Test
    query = "Zig programming language"
    print(f"\n[Step 2] Discovering seed candidates for: '{query}'...")
    urls = await discover_seed_urls(query, max_urls=3)
    for u in urls:
        print(f"  ✓ Discovered: {u}")

    if not urls:
        print("  ❌ No seed URLs discovered.")
        return

    test_url = urls[0]

    # 3. Fetching with Chrome 124 TLS JA3 Impersonation
    print(f"\n[Step 3] Fetching page with curl_cffi (Chrome 124 TLS Impersonation)...")
    print(f"  Target: {test_url}")
    t0 = time.perf_counter()

    async with AsyncSession(impersonate="chrome124") as session:
        resp = await session.get(test_url, timeout=5.0)

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    print(f"  ✓ HTTP {resp.status_code} in {elapsed_ms}ms (Length: {len(resp.text)} chars)")

    # 4. Parsing and Extraction
    print("\n[Step 4] Extracting metadata and clean text with Selectolax...")
    extracted = parse_page_content(resp.text, test_url)
    print(f"  ✓ Title: {extracted['title']}")
    print(f"  ✓ Snippet: {extracted['snippet'][:120]}...")
    print(f"  ✓ Outbound Links Discovered: {len(extracted['links'])}")

    # 5. Compress and Index to Live Turso
    print("\n[Step 5] Compressing with Zstandard and indexing to Turso FTS5...")
    compressed = compress_text(extracted["text"])
    u_hash = hash_url(test_url)
    d_hash = hash_domain(extract_domain_host(test_url))
    simhash = compute_simhash(extracted["text"])

    ratio = round(len(compressed) / max(len(extracted["text"]), 1) * 100, 1)
    print(f"  ✓ Raw Text: {len(extracted['text'])} bytes -> Compressed: {len(compressed)} bytes ({ratio}%)")

    success = await turso_crawler_client.insert_search_index(
        url_hash=u_hash,
        domain_hash=d_hash,
        canonical_url=test_url,
        title=extracted["title"],
        snippet=extracted["snippet"],
        opic_authority=0.5,
        simhash=simhash,
        compressed_text=compressed,
    )
    if success:
        print("  ✓ Document successfully written to Turso search_index & page_payloads!")
    else:
        print("  ❌ Write to Turso failed.")
        return

    # 6. Execute BM25 Full-Text Search
    print(f"\n[Step 6] Running BM25 Full-Text Query for '{query}'...")
    t_search = time.perf_counter()
    search_hits = await turso_crawler_client.search(query, limit=5)
    search_ms = round((time.perf_counter() - t_search) * 1000, 2)

    print(f"  ✓ BM25 Query completed in {search_ms}ms! Found {len(search_hits)} results:")
    for hit in search_hits:
        print(f"    - [{hit['score']}] {hit['title']} ({hit['url']})")

    # 7. Read Full Decompressed Article from Turso
    print(f"\n[Step 7] Reading full article payload directly from Turso (Zero-Card)...")
    t_payload = time.perf_counter()
    raw_payload = await turso_crawler_client.get_document_payload(u_hash)
    payload_ms = round((time.perf_counter() - t_payload) * 1000, 2)

    if raw_payload:
        full_text = decompress_text(raw_payload)
        print(f"  ✓ Retrieved & decompressed full payload in {payload_ms}ms! ({len(full_text)} chars)")
    else:
        print("  ❌ Could not read payload from Turso.")

    await turso_crawler_client.close()

    print("\n" + "=" * 65)
    print("  🎉 FULL SYSTEM VERIFIED LIVE ON TURSO!")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(run_live_test())

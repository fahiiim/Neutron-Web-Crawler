"""Refresh older indexed Turso documents cleanly using the current HTML-to-Markdown parser."""

from __future__ import annotations

import argparse
import asyncio
from typing import Any, Dict, List

from curl_cffi.requests import AsyncSession
from dotenv import load_dotenv

from spaces.crawler.compression import compress_text
from spaces.crawler.db_turso import turso_crawler_client
from spaces.crawler.dedup import compute_simhash, extract_domain_host, hash_domain
from spaces.crawler.parser import parse_page_content
from spaces.crawler.robots import robots_manager

load_dotenv()


async def fetch_stale_rows(*, older_than_days: int = 14, limit: int = 25) -> List[Dict[str, Any]]:
    """Query oldest indexed rows in Turso eligible for a clean re-crawl."""
    client = await turso_crawler_client._ensure_client()
    if client is None:
        return []
    modifier = f"-{max(0, int(older_than_days))} days"
    rs = await client.execute(
        """
        SELECT url_hash, domain_hash, canonical_url, title, opic_authority, crawled_at
        FROM search_index
        WHERE crawled_at <= DATETIME('now', ?)
        ORDER BY crawled_at ASC
        LIMIT ?;
        """,
        [modifier, max(1, min(int(limit), 200))],
    )
    return [row.asdict() if hasattr(row, "asdict") else dict(row) for row in rs.rows]


async def refresh_stale_documents(
    *,
    older_than_days: int = 14,
    limit: int = 25,
    dry_run: bool = False,
) -> Dict[str, int]:
    """Re-fetch and re-index stale pages without altering unrelated tables."""
    if not turso_crawler_client.is_configured():
        raise RuntimeError("TURSO_DATABASE_URL and TURSO_AUTH_TOKEN must be configured.")

    await turso_crawler_client.connect()
    summary = {"candidates": 0, "refreshed": 0, "skipped": 0, "failed": 0}
    try:
        rows = await fetch_stale_rows(older_than_days=older_than_days, limit=limit)
        summary["candidates"] = len(rows)
        if dry_run or not rows:
            return summary

        sem = asyncio.Semaphore(4)
        async with AsyncSession(impersonate="chrome124") as session:
            async def _refresh_one(row: Dict[str, Any]) -> str:
                url = str(row.get("canonical_url") or "")
                if not url:
                    return "skipped"
                async with sem:
                    try:
                        if not await robots_manager.is_allowed(url):
                            return "skipped"
                        resp = await session.get(url, timeout=6.0, allow_redirects=True)
                        content_type = (resp.headers.get("content-type") or "").lower()
                        if (
                            resp.status_code != 200
                            or not resp.text
                            or ("text/html" not in content_type and "application/xhtml" not in content_type)
                        ):
                            return "failed"
                        parsed = parse_page_content(resp.text, str(resp.url or url))
                        if (
                            parsed.get("is_waf_blocked")
                            or parsed.get("is_spa_empty")
                            or len(parsed.get("text") or "") < 120
                        ):
                            return "skipped"
                        raw_opic = float(row.get("opic_authority") or 0.5)
                        bounded_opic = round(min(0.95, max(0.1, raw_opic)), 3)
                        ok = await turso_crawler_client.insert_search_index(
                            int(row["url_hash"]),
                            int(row.get("domain_hash") or hash_domain(extract_domain_host(url))),
                            url,
                            str(parsed.get("title") or row.get("title") or url)[:200],
                            str(parsed.get("snippet") or "")[:1200],
                            bounded_opic,
                            compute_simhash(parsed["text"]),
                            compress_text(parsed["text"]),
                        )
                        return "refreshed" if ok else "failed"
                    except Exception:
                        return "failed"

            outcomes = await asyncio.gather(*(_refresh_one(r) for r in rows))
            for status in outcomes:
                summary[status] = summary.get(status, 0) + 1
        return summary
    finally:
        await turso_crawler_client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh older Turso search_index entries.")
    parser.add_argument("--older-than-days", type=int, default=14)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = asyncio.run(
        refresh_stale_documents(
            older_than_days=args.older_than_days,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    )
    print(f"Stale refresh summary: {result}")


if __name__ == "__main__":
    main()


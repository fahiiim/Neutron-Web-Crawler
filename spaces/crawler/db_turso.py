"""Database client for managing index insertions and frontier queues in Turso."""

from typing import Any, Dict, List, Optional
import libsql_client

from config import settings


class TursoCrawlerClient:
    """Manages asynchronous database writes and queue leases on Turso LibSQL."""

    def __init__(self) -> None:
        self._client: Optional[libsql_client.Client] = None

    async def connect(self) -> None:
        """Establish persistent async client session to Turso."""
        if self._client is None:
            self._client = libsql_client.create_client_async(
                url=settings.TURSO_DATABASE_URL,
                auth_token=settings.TURSO_AUTH_TOKEN,
            )

    async def close(self) -> None:
        """Gracefully terminate client session."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def insert_search_index(
        self,
        url_hash: int,
        domain_hash: int,
        canonical_url: str,
        title: str,
        snippet: str,
        opic_authority: float,
        simhash: int,
        compressed_text: Optional[bytes] = None,
    ) -> bool:
        """Insert or update indexed page metadata and payload directly in Turso.

        Args:
            url_hash: Signed 64-bit primary key.
            domain_hash: Signed 64-bit domain key.
            canonical_url: Clean URL string.
            title: Document title.
            snippet: Short search result summary.
            opic_authority: Authority score (0.0 to 1.0).
            simhash: 64-bit Charikar SimHash.
            compressed_text: Optional Zstandard-compressed full markdown payload.

        Returns:
            True if write succeeded.
        """
        if self._client is None:
            await self.connect()

        sql_index = """
        INSERT INTO search_index (
            url_hash, domain_hash, canonical_url, title, snippet,
            opic_authority, simhash
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (url_hash) DO UPDATE SET
            title = excluded.title,
            snippet = excluded.snippet,
            opic_authority = excluded.opic_authority;
        """
        try:
            await self._client.execute(
                sql_index,
                [
                    url_hash,
                    domain_hash,
                    canonical_url,
                    title,
                    snippet,
                    opic_authority,
                    simhash,
                ],
            )

            # Store compressed text payload directly in Turso (eliminating Cloudflare R2!)
            if compressed_text:
                sql_payload = """
                INSERT INTO page_payloads (url_hash, compressed_text)
                VALUES (?, ?)
                ON CONFLICT(url_hash) DO UPDATE SET
                    compressed_text = excluded.compressed_text,
                    updated_at = DATETIME('now');
                """
                await self._client.execute(sql_payload, [url_hash, compressed_text])

            return True
        except Exception as exc:
            print(f"[Turso Insert Error]: {exc}")
            return False

    async def enqueue_frontier_urls(self, urls: List[Dict[str, Any]]) -> int:
        """Batch insert discovered outbound URLs into the frontier queue."""
        if self._client is None:
            await self.connect()

        sql = """
        INSERT OR IGNORE INTO frontier_queue (
            url_hash, domain_hash, url, priority_score, status
        ) VALUES (?, ?, ?, ?, 0);
        """
        enqueued_count = 0
        for item in urls:
            try:
                await self._client.execute(
                    sql,
                    [
                        item["url_hash"],
                        item["domain_hash"],
                        item["url"],
                        item.get("priority", 0.5),
                    ],
                )
                enqueued_count += 1
            except Exception:
                pass
        return enqueued_count

    async def lease_next_frontier_url(self) -> Optional[Dict[str, Any]]:
        """Lease the highest priority pending URL from the crawl frontier."""
        if self._client is None:
            await self.connect()

        select_sql = """
        SELECT url_hash, domain_hash, url
        FROM frontier_queue
        WHERE status = 0
        ORDER BY priority_score DESC, discovered_at ASC
        LIMIT 1;
        """
        try:
            rs = await self._client.execute(select_sql)
            if not rs.rows:
                return None

            row = rs.rows[0]
            url_hash = int(row["url_hash"])

            await self._client.execute(
                "UPDATE frontier_queue SET status = 1 WHERE url_hash = ?",
                [url_hash],
            )
            return {
                "url_hash": url_hash,
                "domain_hash": int(row["domain_hash"]),
                "url": str(row["url"]),
            }
        except Exception as exc:
            print(f"[Turso Frontier Lease Error]: {exc}")
            return None

    async def update_frontier_status(self, url_hash: int, status: int) -> None:
        """Update crawl status (2=Success, 3=Failed)."""
        if self._client is None:
            await self.connect()

        try:
            await self._client.execute(
                "UPDATE frontier_queue SET status = ? WHERE url_hash = ?",
                [status, url_hash],
            )
        except Exception:
            pass


turso_crawler_client = TursoCrawlerClient()

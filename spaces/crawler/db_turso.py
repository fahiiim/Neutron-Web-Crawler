"""Database client for managing index insertions, frontier queues, and search in Turso."""

from typing import Any, Dict, List, Optional
import libsql_client

from config import settings


class TursoCrawlerClient:
    """Manages asynchronous database queries, writes, and queue leases on Turso LibSQL."""

    def __init__(self) -> None:
        self._client: Optional[libsql_client.Client] = None

    async def connect(self) -> None:
        """Establish persistent async client session to Turso."""
        if self._client is None:
            clean_url = (
                settings.TURSO_DATABASE_URL.replace("libsql://", "https://")
                if settings.TURSO_DATABASE_URL.startswith("libsql://")
                else settings.TURSO_DATABASE_URL
            )
            self._client = libsql_client.create_client(
                url=clean_url,
                auth_token=settings.TURSO_AUTH_TOKEN,
            )

    async def close(self) -> None:
        """Gracefully terminate client session."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def search(self, query: str, limit: int = 15) -> List[Dict[str, Any]]:
        """Execute high-speed BM25 ranked full-text query against SQLite FTS5 index."""
        if self._client is None:
            await self.connect()

        clean_terms = [
            token.strip()
            for token in "".join(c for c in query if c.isalnum() or c.isspace()).split()
            if len(token.strip()) > 1
        ][:8]

        if not clean_terms:
            return []

        fts_pattern = " ".join([f'"{term}"*' for term in clean_terms])

        sql = """
        SELECT
            s.url_hash,
            s.domain_hash,
            s.canonical_url,
            s.title,
            s.snippet,
            s.opic_authority,
            bm25(search_fts, 2.0, 1.0, 0.5) AS bm25_rank
        FROM search_fts f
        JOIN search_index s ON f.rowid = s.url_hash
        WHERE search_fts MATCH ?
        ORDER BY bm25_rank ASC, s.opic_authority DESC
        LIMIT ?;
        """

        try:
            result_set = await self._client.execute(sql, [fts_pattern, limit])
            results: List[Dict[str, Any]] = []

            for row in result_set.rows:
                rank_score = round(
                    abs(float(row["bm25_rank"] or 0.0))
                    + float(row["opic_authority"] or 0.1),
                    4,
                )
                results.append(
                    {
                        "url_hash": row["url_hash"],
                        "url": row["canonical_url"],
                        "title": row["title"],
                        "snippet": row["snippet"],
                        "score": rank_score,
                    }
                )
            return results
        except Exception as exc:
            print(f"[Turso Search Warning]: {exc}")
            return []

    async def get_document_payload(self, url_hash: int) -> Optional[bytes]:
        """Fetch compressed markdown payload directly from Turso (Sub-5ms, Zero-Card)."""
        if self._client is None:
            await self.connect()

        sql = "SELECT compressed_text FROM page_payloads WHERE url_hash = ? LIMIT 1;"
        try:
            rs = await self._client.execute(sql, [url_hash])
            if rs.rows:
                raw_bytes = rs.rows[0]["compressed_text"]
                return bytes(raw_bytes) if raw_bytes else None
        except Exception as exc:
            print(f"[Turso Payload Retrieval Warning]: {exc}")
        return None

    async def record_hot_topic(self, term: str) -> None:
        """Increment frequency in the hot_topics lexicon for focused crawling."""
        if self._client is None:
            await self.connect()

        sql = """
        INSERT INTO hot_topics (term, frequency, last_searched_at)
        VALUES (?, 1, DATETIME('now'))
        ON CONFLICT(term) DO UPDATE SET
            frequency = frequency + 1,
            last_searched_at = DATETIME('now');
        """
        try:
            await self._client.execute(sql, [term.lower().strip()[:64]])
        except Exception:
            pass

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
        """Insert or update indexed page metadata and payload directly in Turso."""
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

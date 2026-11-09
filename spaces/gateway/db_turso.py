"""Database client for querying Turso (LibSQL / SQLite FTS5) and reading payloads."""

from typing import Any, Dict, List, Optional
import libsql_client

from config import settings


class TursoSearchClient:
    """Manages asynchronous queries to the Turso LibSQL search engine."""

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
            print(f"[Turso Client Warning]: {exc}")
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


turso_client = TursoSearchClient()

import libsql_client
from typing import List, Dict, Any, Optional
from shared.config import settings

class TursoDatabase:
    """Async database client for Turso (LibSQL / SQLite FTS5)."""
    def __init__(self):
        self._client: Optional[libsql_client.Client] = None

    async def connect(self):
        if self._client is None:
            self._client = libsql_client.create_client_async(
                url=settings.TURSO_DATABASE_URL,
                auth_token=settings.TURSO_AUTH_TOKEN
            )

    async def close(self):
        if self._client:
            await self._client.close()
            self._client = None

    async def search(self, query: str, limit: int = 15) -> List[Dict[str, Any]]:
        """Perform sub-15ms BM25 full-text search against FTS5 index."""
        if not self._client:
            await self.connect()

        # Sanitize query for FTS5 (strip special syntax characters like quotes, asterisks)
        clean_query = "".join(c for c in query if c.isalnum() or c.isspace()).strip()
        if not clean_query:
            return []

        # Prepare tokens for FTS5 prefix match
        fts_terms = " ".join([f'"{token}"*' for token in clean_query.split()[:8]])

        sql = """
        SELECT 
            s.url_hash,
            s.domain_hash,
            s.canonical_url,
            s.title,
            s.snippet,
            s.r2_batch_id,
            s.r2_byte_offset,
            s.r2_byte_length,
            s.opic_authority,
            bm25(search_fts, 2.0, 1.0, 0.5) AS bm25_rank
        FROM search_fts f
        JOIN search_index s ON f.rowid = s.url_hash
        WHERE search_fts MATCH ?
        ORDER BY bm25_rank ASC, s.opic_authority DESC
        LIMIT ?;
        """
        try:
            rs = await self._client.execute(sql, [fts_terms, limit])
            results = []
            for row in rs.rows:
                # Invert BM25 for display (higher = more relevant)
                score = round(abs(float(row["bm25_rank"] or 0.0)) + float(row["opic_authority"] or 0.1), 4)
                results.append({
                    "url_hash": row["url_hash"],
                    "url": row["canonical_url"],
                    "title": row["title"],
                    "snippet": row["snippet"],
                    "r2_batch_id": row["r2_batch_id"],
                    "r2_byte_offset": row["r2_byte_offset"],
                    "r2_byte_length": row["r2_byte_length"],
                    "score": score
                })
            return results
        except Exception as e:
            print(f"[Turso DB Error in search]: {e}")
            return []

    async def insert_search_index(
        self,
        url_hash: int,
        domain_hash: int,
        canonical_url: str,
        title: str,
        snippet: str,
        r2_batch_id: str,
        r2_byte_offset: int,
        r2_byte_length: int,
        opic_authority: float,
        simhash: int
    ):
        """Insert or replace document entry into index."""
        if not self._client:
            await self.connect()

        sql = """
        INSERT INTO search_index (
            url_hash, domain_hash, canonical_url, title, snippet,
            r2_batch_id, r2_byte_offset, r2_byte_length, opic_authority, simhash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (url_hash) DO UPDATE SET
            title = excluded.title,
            snippet = excluded.snippet,
            r2_batch_id = excluded.r2_batch_id,
            opic_authority = excluded.opic_authority;
        """
        await self._client.execute(sql, [
            url_hash, domain_hash, canonical_url, title, snippet,
            r2_batch_id, r2_byte_offset, r2_byte_length, opic_authority, simhash
        ])

    async def record_hot_topic(self, term: str):
        """Log user search term for query-focused crawling priority."""
        if not self._client:
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

turso_db = TursoDatabase()


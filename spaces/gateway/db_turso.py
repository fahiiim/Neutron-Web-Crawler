"""Database client for querying Turso (LibSQL / SQLite FTS5) and reading payloads."""

import re
from typing import Any, Dict, List, Optional
import libsql_client
import structlog

try:
    from .config import settings
except ImportError:
    from config import settings

logger = structlog.get_logger("neutron.gateway.db")

_FTS5_RESERVED = {"and", "or", "not", "near"}

_STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "also", "am", "an",
    "and", "any", "are", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "could", "did", "do", "does",
    "doing", "down", "during", "each", "few", "for", "from", "further", "get", "go",
    "had", "has", "have", "having", "he", "her", "here", "hers", "herself", "him",
    "himself", "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself",
    "just", "like", "me", "more", "most", "my", "myself", "no", "nor", "not", "of",
    "off", "on", "once", "only", "or", "other", "our", "ours", "ourselves", "out",
    "over", "own", "same", "she", "should", "so", "some", "such", "than", "that",
    "the", "their", "theirs", "them", "themselves", "then", "there", "these", "they",
    "this", "those", "through", "to", "too", "under", "until", "up", "very", "was",
    "we", "were", "what", "when", "where", "which", "while", "who", "whom", "why",
    "will", "with", "would", "you", "your", "yours", "yourself", "yourselves",
}

_QUESTION_PREFIX_RE = re.compile(
    r"^(what\s+is\s+(the\s+)?(name\s+of\s+)?|who\s+is\s+(the\s+)?|"
    r"tell\s+me\s+about\s+|can\s+you\s+find\s+|how\s+to\s+|which\s+is\s+)",
    flags=re.IGNORECASE,
)


def _sanitize_terms(query: str) -> List[str]:
    stripped = _QUESTION_PREFIX_RE.sub("", (query or "").strip()).strip()
    source_text = stripped if stripped else (query or "")
    tokens = re.findall(r"[a-zA-Z0-9]+", source_text.lower())
    if not tokens:
        return []
    multi = [t for t in tokens if len(t) > 1]
    base = multi if multi else tokens
    clean = [
        t for t in base if t not in _STOP_WORDS and t not in _FTS5_RESERVED
    ] or [t for t in base if t not in _FTS5_RESERVED] or base
    seen = set()
    out: List[str] = []
    for t in clean:
        if t not in seen:
            seen.add(t)
            out.append(t)
        if len(out) >= 8:
            break
    return out


class TursoSearchClient:
    """Manages asynchronous queries to the Turso LibSQL search engine."""

    def __init__(self) -> None:
        self._client: Optional[libsql_client.Client] = None

    def is_configured(self) -> bool:
        return bool(
            settings.TURSO_DATABASE_URL
            and settings.TURSO_AUTH_TOKEN
            and "placeholder" not in settings.TURSO_AUTH_TOKEN
        )

    async def connect(self) -> None:
        """Establish persistent async client session to Turso."""
        if self._client is not None or not self.is_configured():
            return
        raw_url = settings.TURSO_DATABASE_URL.strip()
        clean_url = (
            raw_url.replace("libsql://", "https://")
            if raw_url.startswith("libsql://")
            else raw_url
        )
        self._client = libsql_client.create_client(
            url=clean_url,
            auth_token=settings.TURSO_AUTH_TOKEN.strip(),
        )

    async def close(self) -> None:
        """Gracefully terminate client session."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def _ensure_client(self) -> Optional[libsql_client.Client]:
        if self._client is None:
            await self.connect()
        return self._client

    async def _execute_fts(self, fts_pattern: str, limit: int) -> List[Dict[str, Any]]:
        client = await self._ensure_client()
        if client is None:
            return []

        sql = """
        SELECT
            s.url_hash,
            s.domain_hash,
            s.canonical_url,
            s.title,
            s.snippet,
            s.opic_authority,
            s.crawled_at,
            bm25(search_fts, 2.0, 1.0, 0.5) AS bm25_rank
        FROM search_fts f
        JOIN search_index s ON f.rowid = s.url_hash
        WHERE search_fts MATCH ?
        ORDER BY bm25_rank ASC, s.opic_authority DESC
        LIMIT ?;
        """
        try:
            rs = await client.execute(sql, [fts_pattern, limit])
            results: List[Dict[str, Any]] = []
            for row in rs.rows:
                rank_score = round(
                    abs(float(row["bm25_rank"] or 0.0))
                    + float(row["opic_authority"] or 0.1),
                    4,
                )
                results.append(
                    {
                        "url_hash": str(row["url_hash"]),
                        "url": row["canonical_url"],
                        "title": row["title"],
                        "snippet": row["snippet"],
                        "score": rank_score,
                        "crawled_at": row["crawled_at"],
                    }
                )
            return results
        except Exception as exc:
            logger.warning("gateway_fts_query_failed", error=str(exc))
            return []

    async def search(self, query: str, limit: int = 15) -> List[Dict[str, Any]]:
        """Execute sanitized BM25 full-text query against SQLite FTS5 index."""
        terms = _sanitize_terms(query)
        if not terms:
            return []

        and_pattern = " ".join([f'"{t}"*' for t in terms])
        hits = await self._execute_fts(and_pattern, limit)
        if len(hits) < 3 and len(terms) > 1:
            or_pattern = " OR ".join([f'"{t}"*' for t in terms])
            or_hits = await self._execute_fts(or_pattern, limit)
            seen = {h["url_hash"] for h in hits}
            for item in or_hits:
                if item["url_hash"] not in seen:
                    hits.append(item)
                    seen.add(item["url_hash"])
        return hits[:limit]

    async def get_document_payload(self, url_hash: int) -> Optional[bytes]:
        client = await self._ensure_client()
        if client is None:
            return None
        try:
            rs = await client.execute(
                "SELECT compressed_text FROM page_payloads WHERE url_hash = ? LIMIT 1;",
                [url_hash],
            )
            if rs.rows:
                raw_bytes = rs.rows[0]["compressed_text"]
                return bytes(raw_bytes) if raw_bytes else None
        except Exception as exc:
            logger.warning("gateway_payload_read_failed", url_hash=url_hash, error=str(exc))
        return None

    async def get_document_metadata(self, url_hash: int) -> Optional[Dict[str, Any]]:
        client = await self._ensure_client()
        if client is None:
            return None
        try:
            rs = await client.execute(
                "SELECT url_hash, canonical_url, title, snippet, crawled_at FROM search_index WHERE url_hash = ? LIMIT 1;",
                [url_hash],
            )
            if rs.rows:
                row = rs.rows[0]
                return {
                    "url_hash": str(row["url_hash"]),
                    "url": row["canonical_url"],
                    "title": row["title"],
                    "snippet": row["snippet"],
                    "crawled_at": row["crawled_at"],
                }
        except Exception as exc:
            logger.warning("gateway_metadata_read_failed", url_hash=url_hash, error=str(exc))
        return None

    async def record_hot_topic(self, term: str) -> None:
        client = await self._ensure_client()
        if client is None:
            return
        cleaned = " ".join(term.lower().strip().split())[:64]
        if not cleaned or len(cleaned) > 40 or len(cleaned.split()) > 5:
            return
        try:
            await client.execute(
                """
                INSERT INTO hot_topics (term, frequency, last_searched_at)
                VALUES (?, 1, DATETIME('now'))
                ON CONFLICT(term) DO UPDATE SET
                    frequency = frequency + 1,
                    last_searched_at = DATETIME('now');
                """,
                [cleaned],
            )
        except Exception as exc:
            logger.debug("gateway_record_hot_topic_failed", error=str(exc))

    async def get_trending_topics(self, limit: int = 8) -> List[Dict[str, Any]]:
        client = await self._ensure_client()
        if client is None:
            return []
        try:
            rs = await client.execute(
                """
                SELECT term, frequency FROM hot_topics
                WHERE LENGTH(term) <= 36
                  AND term NOT LIKE 'what %'
                  AND term NOT LIKE 'who %'
                  AND term NOT LIKE 'how %'
                ORDER BY frequency DESC, last_searched_at DESC
                LIMIT ?;
                """,
                [limit],
            )
            return [
                {"term": str(r["term"]), "count": int(r["frequency"])}
                for r in rs.rows
            ]
        except Exception as exc:
            logger.warning("gateway_trending_failed", error=str(exc))
            return []

    async def get_autocomplete_suggestions(self, prefix: str, limit: int = 6) -> List[str]:
        client = await self._ensure_client()
        clean = prefix.strip().lower()[:64]
        if client is None or len(clean) < 2:
            return []
        try:
            rs = await client.execute(
                "SELECT term FROM hot_topics WHERE LOWER(term) LIKE ? ORDER BY frequency DESC LIMIT ?;",
                [f"{clean}%", limit],
            )
            return [str(r["term"]) for r in rs.rows if r["term"]]
        except Exception as exc:
            logger.debug("gateway_autocomplete_failed", error=str(exc))
            return []

    async def get_stats(self) -> Dict[str, Any]:
        client = await self._ensure_client()
        if client is None:
            return {
                "pages_indexed": 0,
                "domains_covered": 0,
                "frontier_pending": 0,
                "payloads_stored": 0,
                "connected": False,
            }
        try:
            res = await client.batch(
                [
                    "SELECT COUNT(*) AS cnt FROM search_index;",
                    "SELECT COUNT(DISTINCT domain_hash) AS cnt FROM search_index;",
                    "SELECT COUNT(*) AS cnt FROM frontier_queue WHERE status = 0;",
                    "SELECT COUNT(*) AS cnt FROM page_payloads;",
                ]
            )
            return {
                "pages_indexed": int(res[0].rows[0]["cnt"]) if res[0].rows else 0,
                "domains_covered": int(res[1].rows[0]["cnt"]) if res[1].rows else 0,
                "frontier_pending": int(res[2].rows[0]["cnt"]) if res[2].rows else 0,
                "payloads_stored": int(res[3].rows[0]["cnt"]) if res[3].rows else 0,
                "connected": True,
            }
        except Exception as exc:
            logger.warning("gateway_stats_failed", error=str(exc))
            return {
                "pages_indexed": 0,
                "domains_covered": 0,
                "frontier_pending": 0,
                "payloads_stored": 0,
                "connected": False,
            }


turso_client = TursoSearchClient()

"""Database client for managing index insertions, frontier queues, and search in Turso."""

import itertools
import math
import re
from typing import Any, Dict, List, Optional, Tuple
import libsql_client

try:
    from .config import settings
    from .dedup import extract_domain_host, hamming_distance
    from .logging_utils import get_logger
except ImportError:
    from config import settings
    from dedup import extract_domain_host, hamming_distance
    from logging_utils import get_logger

logger = get_logger("neutron.db")

_FTS5_RESERVED = {"and", "or", "not", "near"}

STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "also", "am", "an",
    "and", "any", "are", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "could", "did", "do", "does",
    "doing", "down", "during", "each", "explain", "few", "for", "from", "further",
    "get", "getting", "go", "had", "has", "have", "having", "he", "her", "here",
    "hers", "herself", "him", "himself", "his", "how", "i", "if", "in", "into",
    "is", "it", "its", "itself", "just", "like", "me", "more", "most", "my",
    "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other",
    "our", "ours", "ourselves", "out", "over", "own", "please", "same", "she",
    "should", "so", "some", "such", "tell", "than", "that", "the", "their",
    "theirs", "them", "themselves", "then", "there", "these", "they", "this",
    "those", "through", "to", "too", "under", "until", "up", "very", "was", "we",
    "were", "what", "when", "where", "which", "while", "who", "whom", "why",
    "will", "with", "would", "you", "your", "yours", "yourself", "yourselves",
}

_SYNONYM_GROUPS = {
    "us": '("us" OR "usa")',
    "usa": '("usa" OR "us")',
}

_QUESTION_PREFIX_RE = re.compile(
    r"^(what\s+(?:is|are|was|were|does|do|to\s+do\s+to(?:\s+make\s+me)?)\s+(?:the\s+)?(?:(?:name|(?:\w+\s+)?purpose|reason|role|benefit|benefits|meaning|definition|overview|concept)\s+of\s+(?:the\s+)?)?|"
    r"who\s+(?:is|are|was|were|invented|wrote|created)\s+(?:the\s+)?|"
    r"when\s+(?:was|were|is|are|did|do|will)?\s*|"
    r"where\s+(?:is|are|was|were|did|do)?\s*|"
    r"how\s+(?:does|do|did|can|to)\s+|"
    r"why\s+(?:does|do|did|is|are)\s+|"
    r"tell\s+me\s+about\s+|"
    r"can\s+you\s+(?:tell\s+me|find|explain)\s+|"
    r"explain\s+|"
    r"which\s+(?:is|are)\s+)",
    flags=re.IGNORECASE,
)

_LEADING_QUESTION_RE = re.compile(
    r"^(what|who|how|why|which|where|when|tell|can|explain)\b",
    flags=re.IGNORECASE,
)


def normalize_search_query(query: str) -> str:
    """Strip conversational question framing while preserving entity keywords."""
    raw = (query or "").strip()
    if not raw:
        return ""
    is_question = bool(_LEADING_QUESTION_RE.match(raw)) or raw.endswith("?")
    cleaned = _QUESTION_PREFIX_RE.sub("", raw).strip()
    if is_question:
        cleaned = re.sub(r"\s+(?:works?|working)\??$", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.rstrip("?!.").strip()
    return cleaned if cleaned else raw.rstrip("?!.").strip()


_FILLER_QUERY_WORDS = frozenset(
    {
        "purpose",
        "main",
        "primary",
        "reason",
        "role",
        "benefit",
        "benefits",
        "definition",
        "overview",
        "meaning",
        "important",
        "importance",
        "concept",
    }
)

_AUTHORITATIVE_DOMAINS = (
    "wikipedia.org",
    "developer.mozilla.org",
    "docs.python.org",
    "python.org",
    "postgresql.org",
    "dev.mysql.com",
    "sqlite.org",
    "learn.microsoft.com",
    "w3schools.com",
    "geeksforgeeks.org",
    "sqltutorial.org",
    "react.dev",
    "rust-lang.org",
    "typescriptlang.org",
    "go.dev",
    "arxiv.org",
)

_BOILERPLATE_PHRASES = (
    "main purpose of this project",
    "course-enrollment",
    "starter template",
    "fork me on github",
)


def _is_authoritative_host(url: str) -> bool:
    """Check whether URL belongs to an authoritative reference domain (host or subdomain)."""
    host = extract_domain_host(url)
    if not host or host == "unknown":
        return False
    return any(host == d or host.endswith(f".{d}") for d in _AUTHORITATIVE_DOMAINS)


def _expand_term_variants(term: str) -> Tuple[str, ...]:
    """Produce conservative morphological variants (e.g. joining -> join) for FTS/scoring."""
    variants: List[str] = [term]
    if len(term) >= 6 and term.endswith("ing"):
        stem = term[:-3]
        if len(stem) >= 4 and stem[-1] == stem[-2]:
            variants.append(stem[:-1])
        variants.extend((stem, f"{stem}s", f"{stem}ed"))
    elif len(term) >= 5 and term.endswith("ies"):
        variants.append(term[:-3] + "y")
    elif len(term) >= 5 and term.endswith("ed"):
        stem = term[:-2]
        variants.extend((stem, f"{stem}s", f"{stem}ing"))
    elif len(term) >= 5 and term.endswith(("ches", "shes", "xes", "zes", "sses")):
        variants.extend((term[:-2], term[:-1]))
    elif len(term) >= 4 and term.endswith("s") and not term.endswith(("ss", "us", "is")):
        variants.append(term[:-1])

    seen = set()
    deduped: List[str] = []
    for item in variants:
        if len(item) >= 2 and item not in seen:
            seen.add(item)
            deduped.append(item)
    return tuple(deduped)


def sanitize_fts_terms(query: str) -> List[str]:
    """Normalize conversational prefixes, extract safe tokens, and strip FTS5 syntax."""
    source_text = normalize_search_query(query)
    tokens = re.findall(r"[a-zA-Z0-9]+", source_text.lower())
    if not tokens:
        return []

    multi_char = [t for t in tokens if len(t) > 1]
    base_tokens = multi_char if multi_char else tokens

    non_reserved = [
        t for t in base_tokens if t not in STOP_WORDS and t not in _FTS5_RESERVED
    ]
    terms = non_reserved if non_reserved else [
        t for t in base_tokens if t not in _FTS5_RESERVED
    ]
    if not terms:
        terms = base_tokens

    non_filler = [t for t in terms if t not in _FILLER_QUERY_WORDS]
    if non_filler:
        terms = non_filler

    # Deduplicate preserving order and cap at 8 terms
    seen = set()
    unique_terms: List[str] = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            unique_terms.append(term)
        if len(unique_terms) >= 8:
            break
    return unique_terms


def _format_fts_term(term: str) -> str:
    """Format an exact Porter-stemmed FTS5 token (expanding safe aliases and inflections)."""
    if term in _SYNONYM_GROUPS:
        return _SYNONYM_GROUPS[term]
    variants = _expand_term_variants(term)
    if len(variants) == 1:
        return f'"{variants[0]}"'
    return "(" + " OR ".join(f'"{v}"' for v in variants) + ")"


def _term_matches_text(term: str, low_text: str) -> bool:
    """Check whether a query term (or inflected/prefix stem / us<->usa) matches text."""
    if not low_text:
        return False
    if term == "us":
        return bool(re.search(r"\b(?:us|u\.s\.?|usa|united states)\b", low_text))
    if term == "usa":
        return bool(re.search(r"\b(?:usa|us|u\.s\.?|united states)\b", low_text))
    for variant in _expand_term_variants(term):
        if re.search(rf"\b{re.escape(variant)}\w*", low_text):
            return True
    if len(term) >= 4:
        stem = term[: max(4, min(len(term) - 1, 5))]
        return bool(re.search(rf"\b{re.escape(stem)}\w*", low_text))
    return False


def score_document_relevance(
    query: str,
    title: str,
    snippet: str,
    url: str,
    body_text: str = "",
    *,
    mode: str = "all",
) -> Tuple[int, float]:
    """Compute matched query concept count and relevance boost across document fields."""
    terms = sanitize_fts_terms(query)
    if not terms:
        return 0, 0.0

    low_title = (title or "").lower()
    low_snippet = (snippet or "").lower()
    low_url = (url or "").lower().replace("-", " ").replace("_", " ").replace("/", " ")
    low_body = (body_text or "")[:6000].lower()

    matched_terms = 0
    score = 0.0
    for term in terms:
        in_title = _term_matches_text(term, low_title)
        in_url = _term_matches_text(term, low_url)
        in_snippet = _term_matches_text(term, low_snippet)
        in_body = _term_matches_text(term, low_body)
        if in_title or in_url or in_snippet or in_body:
            matched_terms += 1
        if in_title:
            score += 4.0
        if in_url:
            score += 1.5
        if in_snippet:
            score += 1.5
        elif in_body:
            score += 0.8

    clean_mode = (mode or "all").strip().lower()
    if clean_mode != "code":
        combined_preview = f"{low_title} {low_snippet} {low_url}"
        if any(phrase in combined_preview for phrase in _BOILERPLATE_PHRASES):
            score -= 4.0
    if matched_terms > 0 and clean_mode in ("all", "encyclopedia"):
        if _is_authoritative_host(url or ""):
            score += 1.5

    return matched_terms, round(score, 3)


class TursoCrawlerClient:
    """Manages asynchronous database queries, writes, and queue leases on Turso LibSQL."""

    def __init__(self) -> None:
        self._client: Optional[libsql_client.Client] = None

    def is_configured(self) -> bool:
        """Return True if Turso credentials are present."""
        return bool(
            settings.TURSO_DATABASE_URL
            and settings.TURSO_AUTH_TOKEN
            and "placeholder" not in settings.TURSO_AUTH_TOKEN
        )

    async def connect(self) -> None:
        """Establish persistent async client session to Turso."""
        if self._client is not None:
            return
        if not self.is_configured():
            logger.warning("turso_credentials_missing")
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
        """Run an FTS5 MATCH query with BM25 ranking."""
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
            bm25(search_fts, 4.0, 1.5, 0.5) AS bm25_rank
        FROM search_fts f
        JOIN search_index s ON f.rowid = s.url_hash
        WHERE search_fts MATCH ?
        ORDER BY bm25_rank ASC, s.opic_authority DESC
        LIMIT ?;
        """
        try:
            result_set = await client.execute(sql, [fts_pattern, limit])
            results: List[Dict[str, Any]] = []
            for row in result_set.rows:
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
            logger.warning("turso_fts_query_failed", pattern=fts_pattern, error=str(exc))
            return []

    async def search(self, query: str, limit: int = 15) -> List[Dict[str, Any]]:
        """Execute high-precision stemmed AND -> multi-term quorum FTS5 search."""
        terms = sanitize_fts_terms(query)
        if not terms:
            return []

        and_pattern = " AND ".join(_format_fts_term(term) for term in terms)
        hits = await self._execute_fts(and_pattern, limit)

        # For 4+ terms, allow high-threshold quorum (>= 70%, min 3 terms) for typo resilience
        if len(terms) >= 4 and len(hits) < limit:
            core = terms[:6]
            quorum = max(3, min(len(core) - 1, math.ceil(len(core) * 0.7)))
            quorum_clauses = [
                "(" + " AND ".join(_format_fts_term(t) for t in comb) + ")"
                for comb in itertools.combinations(core, quorum)
            ]
            quorum_hits = await self._execute_fts(" OR ".join(quorum_clauses), limit)
            seen_hashes = {h["url_hash"] for h in hits}
            for item in quorum_hits:
                if item["url_hash"] not in seen_hashes:
                    hits.append(item)
                    seen_hashes.add(item["url_hash"])

        return hits[:limit]

    async def get_payloads_map(self, url_hashes: List[int]) -> Dict[int, bytes]:
        """Batch-fetch compressed payloads for multiple url_hashes in one round-trip."""
        client = await self._ensure_client()
        if client is None or not url_hashes:
            return {}

        limited = url_hashes[:10]
        placeholders = ",".join("?" for _ in limited)
        sql = f"SELECT url_hash, compressed_text FROM page_payloads WHERE url_hash IN ({placeholders});"
        out: Dict[int, bytes] = {}
        try:
            rs = await client.execute(sql, limited)
            for row in rs.rows:
                raw_bytes = row["compressed_text"]
                if raw_bytes:
                    out[int(row["url_hash"])] = bytes(raw_bytes)
        except Exception as exc:
            logger.warning("turso_payload_batch_read_failed", error=str(exc))
        return out

    async def get_document_payload(self, url_hash: int) -> Optional[bytes]:
        """Fetch compressed markdown payload directly from Turso."""
        client = await self._ensure_client()
        if client is None:
            return None

        sql = "SELECT compressed_text FROM page_payloads WHERE url_hash = ? LIMIT 1;"
        try:
            rs = await client.execute(sql, [url_hash])
            if rs.rows:
                raw_bytes = rs.rows[0]["compressed_text"]
                return bytes(raw_bytes) if raw_bytes else None
        except Exception as exc:
            logger.warning("turso_payload_read_failed", url_hash=url_hash, error=str(exc))
        return None

    async def get_document_metadata(self, url_hash: int) -> Optional[Dict[str, Any]]:
        """Retrieve direct metadata row for a url_hash."""
        client = await self._ensure_client()
        if client is None:
            return None

        sql = """
        SELECT url_hash, canonical_url, title, snippet, crawled_at
        FROM search_index
        WHERE url_hash = ?
        LIMIT 1;
        """
        try:
            rs = await client.execute(sql, [url_hash])
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
            logger.warning("turso_metadata_read_failed", url_hash=url_hash, error=str(exc))
        return None

    async def is_near_duplicate(
        self,
        simhash_val: int,
        domain_hash: int,
        threshold: int = 3,
        exclude_url_hash: Optional[int] = None,
    ) -> bool:
        """Check whether a near-duplicate document already exists for the domain."""
        client = await self._ensure_client()
        if client is None or simhash_val == 0:
            return False

        sql = """
        SELECT url_hash, simhash
        FROM search_index
        WHERE domain_hash = ?
        LIMIT 200;
        """
        try:
            rs = await client.execute(sql, [domain_hash])
            for row in rs.rows:
                row_url_hash = int(row["url_hash"])
                if exclude_url_hash is not None and row_url_hash == exclude_url_hash:
                    continue
                existing_simhash = int(row["simhash"])
                if hamming_distance(simhash_val, existing_simhash) <= threshold:
                    return True
        except Exception as exc:
            logger.warning("turso_simhash_check_failed", domain_hash=domain_hash, error=str(exc))
        return False

    async def record_hot_topic(self, term: str) -> None:
        """Increment frequency in hot_topics for concise, non-conversational terms."""
        client = await self._ensure_client()
        if client is None:
            return

        cleaned = " ".join(term.lower().strip().split())[:64]
        if not cleaned or len(cleaned) > 40 or len(cleaned.split()) > 5:
            return

        sql = """
        INSERT INTO hot_topics (term, frequency, last_searched_at)
        VALUES (?, 1, DATETIME('now'))
        ON CONFLICT(term) DO UPDATE SET
            frequency = frequency + 1,
            last_searched_at = DATETIME('now');
        """
        try:
            await client.execute(sql, [cleaned])
        except Exception as exc:
            logger.debug("record_hot_topic_failed", term=cleaned, error=str(exc))

    async def get_trending_topics(self, limit: int = 8) -> List[Dict[str, Any]]:
        """Return concise top searched topics for UI trending chips."""
        client = await self._ensure_client()
        if client is None:
            return []

        sql = """
        SELECT term, frequency
        FROM hot_topics
        WHERE LENGTH(term) <= 36
          AND term NOT LIKE 'what %'
          AND term NOT LIKE 'who %'
          AND term NOT LIKE 'how %'
        ORDER BY frequency DESC, last_searched_at DESC
        LIMIT ?;
        """
        try:
            rs = await client.execute(sql, [limit])
            return [
                {"term": str(row["term"]), "count": int(row["frequency"])}
                for row in rs.rows
            ]
        except Exception as exc:
            logger.warning("get_trending_failed", error=str(exc))
            return []

    async def get_autocomplete_suggestions(
        self, prefix: str, limit: int = 6
    ) -> List[str]:
        """Return query autocomplete suggestions from hot_topics and indexed titles."""
        client = await self._ensure_client()
        clean_prefix = prefix.strip()[:64]
        if client is None or len(clean_prefix) < 2:
            return []

        like_pattern = f"{clean_prefix.lower()}%"
        suggestions: List[str] = []
        seen = set()

        try:
            rs_topics = await client.execute(
                """
                SELECT term FROM hot_topics
                WHERE LOWER(term) LIKE ?
                ORDER BY frequency DESC
                LIMIT ?;
                """,
                [like_pattern, limit],
            )
            for row in rs_topics.rows:
                val = str(row["term"]).strip()
                if val and val.lower() not in seen:
                    seen.add(val.lower())
                    suggestions.append(val)

            if len(suggestions) < limit:
                rs_titles = await client.execute(
                    """
                    SELECT title FROM search_index
                    WHERE LOWER(title) LIKE ?
                      AND LOWER(title) NOT IN ('just a moment...', 'access denied', 'untitled document', 'attention required! | cloudflare')
                    ORDER BY crawled_at DESC
                    LIMIT ?;
                    """,
                    [f"%{clean_prefix.lower()}%", limit - len(suggestions)],
                )
                for row in rs_titles.rows:
                    val = str(row["title"]).strip()
                    if val and val.lower() not in seen:
                        seen.add(val.lower())
                        suggestions.append(val)
        except Exception as exc:
            logger.debug("autocomplete_query_failed", prefix=clean_prefix, error=str(exc))

        return suggestions[:limit]

    async def get_stats(self) -> Dict[str, Any]:
        """Return live index & crawl frontier statistics."""
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
            results = await client.batch(
                [
                    "SELECT COUNT(*) AS cnt FROM search_index;",
                    "SELECT COUNT(DISTINCT domain_hash) AS cnt FROM search_index;",
                    "SELECT COUNT(*) AS cnt FROM frontier_queue WHERE status = 0;",
                    "SELECT COUNT(*) AS cnt FROM page_payloads;",
                ]
            )
            return {
                "pages_indexed": int(results[0].rows[0]["cnt"]) if results[0].rows else 0,
                "domains_covered": int(results[1].rows[0]["cnt"]) if results[1].rows else 0,
                "frontier_pending": int(results[2].rows[0]["cnt"]) if results[2].rows else 0,
                "payloads_stored": int(results[3].rows[0]["cnt"]) if results[3].rows else 0,
                "connected": True,
            }
        except Exception as exc:
            logger.warning("get_stats_failed", error=str(exc))
            return {
                "pages_indexed": 0,
                "domains_covered": 0,
                "frontier_pending": 0,
                "payloads_stored": 0,
                "connected": False,
            }

    async def get_indexed_urls(self, limit: int = 50000) -> List[str]:
        """Fetch existing canonical URLs to warm the in-memory Bloom filter."""
        client = await self._ensure_client()
        if client is None:
            return []

        try:
            rs = await client.execute(
                "SELECT canonical_url FROM search_index ORDER BY crawled_at DESC LIMIT ?;",
                [limit],
            )
            return [str(row["canonical_url"]) for row in rs.rows if row["canonical_url"]]
        except Exception as exc:
            logger.warning("bloom_warmup_query_failed", error=str(exc))
            return []

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
        """Atomically insert or update indexed metadata and compressed payload in Turso."""
        client = await self._ensure_client()
        if client is None:
            return False

        domain_host = extract_domain_host(canonical_url)
        sql_domain_seed = (
            "INSERT OR IGNORE INTO domains (domain_hash, hostname) VALUES (?, ?);"
        )
        sql_domain_inc = (
            "UPDATE domains SET total_crawled = total_crawled + 1, "
            "updated_at = DATETIME('now') WHERE domain_hash = ?;"
        )
        sql_index = """
        INSERT INTO search_index (
            url_hash, domain_hash, canonical_url, title, snippet,
            opic_authority, simhash, crawled_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, DATETIME('now'))
        ON CONFLICT (url_hash) DO UPDATE SET
            title = excluded.title,
            snippet = excluded.snippet,
            opic_authority = excluded.opic_authority,
            simhash = excluded.simhash,
            crawled_at = DATETIME('now');
        """
        statements = [
            libsql_client.Statement(sql_domain_seed, [domain_hash, domain_host]),
            libsql_client.Statement(sql_domain_inc, [domain_hash]),
            libsql_client.Statement(
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
        ]

        if compressed_text:
            sql_payload = """
            INSERT INTO page_payloads (url_hash, compressed_text, updated_at)
            VALUES (?, ?, DATETIME('now'))
            ON CONFLICT(url_hash) DO UPDATE SET
                compressed_text = excluded.compressed_text,
                updated_at = DATETIME('now');
            """
            statements.append(
                libsql_client.Statement(sql_payload, [url_hash, compressed_text])
            )

        try:
            await client.batch(statements)
            return True
        except Exception as exc:
            logger.error(
                "turso_insert_failed",
                url=canonical_url,
                url_hash=url_hash,
                error=str(exc),
                exc_info=True,
            )
            return False

    async def enqueue_frontier_urls(self, urls: List[Dict[str, Any]]) -> int:
        """Batch insert discovered outbound URLs into the frontier queue in one round-trip."""
        if not urls:
            return 0
        client = await self._ensure_client()
        if client is None:
            return 0

        sql_domain = (
            "INSERT OR IGNORE INTO domains (domain_hash, hostname) VALUES (?, ?);"
        )
        sql_frontier = """
        INSERT OR IGNORE INTO frontier_queue (
            url_hash, domain_hash, url, priority_score, status
        ) VALUES (?, ?, ?, ?, 0);
        """
        unique_domains: Dict[int, str] = {}
        for item in urls:
            d_hash = int(item["domain_hash"])
            if d_hash not in unique_domains:
                unique_domains[d_hash] = (
                    item.get("domain") or extract_domain_host(item["url"])
                )

        statements = [
            libsql_client.Statement(sql_domain, [d_hash, host])
            for d_hash, host in unique_domains.items()
        ]
        statements.extend(
            libsql_client.Statement(
                sql_frontier,
                [
                    item["url_hash"],
                    item["domain_hash"],
                    item["url"],
                    float(item.get("priority", 0.5)),
                ],
            )
            for item in urls
        )

        try:
            await client.batch(statements)
            return len(urls)
        except Exception as exc:
            logger.warning(
                "frontier_batch_enqueue_failed",
                count=len(statements),
                error=str(exc),
            )
            return 0

    async def lease_next_frontier_url(self) -> Optional[Dict[str, Any]]:
        """Atomically lease a pending frontier URL interleaved across domains."""
        client = await self._ensure_client()
        if client is None:
            return None

        atomic_sql = """
        UPDATE frontier_queue
        SET status = 1, lease_expires_at = DATETIME('now', '+5 minutes')
        WHERE url_hash = (
            SELECT f.url_hash
            FROM frontier_queue f
            LEFT JOIN domains d ON f.domain_hash = d.domain_hash
            WHERE f.status = 0
            ORDER BY
                CASE WHEN d.next_fetch_at IS NULL OR d.next_fetch_at <= DATETIME('now') THEN 0 ELSE 1 END ASC,
                f.priority_score DESC,
                COALESCE(d.next_fetch_at, '1970-01-01') ASC,
                f.discovered_at ASC
            LIMIT 1
        )
        RETURNING url_hash, domain_hash, url;
        """
        try:
            rs = await client.execute(atomic_sql)
            if not rs.rows:
                return None
            row = rs.rows[0]
            domain_hash = int(row["domain_hash"])
            try:
                await client.execute(
                    "UPDATE domains SET next_fetch_at = DATETIME('now', '+15 seconds'), updated_at = DATETIME('now') WHERE domain_hash = ?;",
                    [domain_hash],
                )
            except Exception:
                pass
            return {
                "url_hash": int(row["url_hash"]),
                "domain_hash": domain_hash,
                "url": str(row["url"]),
            }
        except Exception as exc:
            logger.warning("frontier_lease_failed", error=str(exc))
            return None

    async def recover_expired_leases(self) -> int:
        """Reset leased frontier URLs whose 5-minute lease expired back to pending."""
        client = await self._ensure_client()
        if client is None:
            return 0

        sql = """
        UPDATE frontier_queue
        SET status = 0, lease_expires_at = NULL
        WHERE status = 1
          AND lease_expires_at IS NOT NULL
          AND lease_expires_at < DATETIME('now');
        """
        try:
            rs = await client.execute(sql)
            return int(getattr(rs, "rows_affected", 0) or 0)
        except Exception as exc:
            logger.warning("frontier_lease_recovery_failed", error=str(exc))
            return 0

    async def update_frontier_status(self, url_hash: int, status: int) -> None:
        """Update crawl status (2=Success, 3=Failed)."""
        client = await self._ensure_client()
        if client is None:
            return

        try:
            await client.execute(
                "UPDATE frontier_queue SET status = ?, lease_expires_at = NULL WHERE url_hash = ?",
                [status, url_hash],
            )
        except Exception as exc:
            logger.warning(
                "frontier_status_update_failed",
                url_hash=url_hash,
                status=status,
                error=str(exc),
            )


turso_crawler_client = TursoCrawlerClient()

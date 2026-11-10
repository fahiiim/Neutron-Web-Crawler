-- ==============================================================================
-- TURSO (LIBSQL / SQLITE) FTS5 SCHEMA (NO CREDIT CARD REQUIRED)
-- Purpose: Unified single-project storage for search index, FTS5, and full text BLOBs.
-- ==============================================================================

-- 1. Domains Table (Politeness & Rate Limits)
CREATE TABLE IF NOT EXISTS domains (
    domain_hash INTEGER PRIMARY KEY,           -- xxHash64 (64-bit signed int)
    hostname TEXT NOT NULL UNIQUE,
    crawl_delay_ms INTEGER NOT NULL DEFAULT 1500,
    ema_rtt_ms INTEGER NOT NULL DEFAULT 250,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    backoff_level INTEGER NOT NULL DEFAULT 0,
    next_fetch_at TEXT NOT NULL DEFAULT (DATETIME('now')),
    total_crawled INTEGER NOT NULL DEFAULT 0,
    search_hits INTEGER NOT NULL DEFAULT 0,
    is_blacklisted INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (DATETIME('now'))
);

CREATE INDEX IF NOT EXISTS idx_domains_politeness
ON domains (next_fetch_at ASC)
WHERE is_blacklisted = 0;

-- 2. Frontier Queue Table
CREATE TABLE IF NOT EXISTS frontier_queue (
    url_hash INTEGER PRIMARY KEY,              -- xxHash64 of normalized URL
    domain_hash INTEGER NOT NULL,
    url TEXT NOT NULL,
    priority_score REAL NOT NULL DEFAULT 0.5,
    depth INTEGER NOT NULL DEFAULT 0,
    status INTEGER NOT NULL DEFAULT 0,         -- 0=Pending, 1=Leased, 2=Crawled, 3=Failed
    lease_expires_at TEXT,
    discovered_at TEXT NOT NULL DEFAULT (DATETIME('now')),
    FOREIGN KEY (domain_hash) REFERENCES domains(domain_hash) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_frontier_priority
ON frontier_queue (status, priority_score DESC, discovered_at ASC)
WHERE status = 0;

CREATE INDEX IF NOT EXISTS idx_frontier_lease
ON frontier_queue (status, lease_expires_at)
WHERE status = 1;

-- 3. Document Search Metadata Table
CREATE TABLE IF NOT EXISTS search_index (
    url_hash INTEGER PRIMARY KEY,              -- xxHash64
    domain_hash INTEGER NOT NULL,
    canonical_url TEXT NOT NULL,
    title TEXT NOT NULL,
    snippet TEXT NOT NULL,
    opic_authority REAL NOT NULL DEFAULT 0.1,
    simhash INTEGER NOT NULL,
    crawled_at TEXT NOT NULL DEFAULT (DATETIME('now'))
);

CREATE INDEX IF NOT EXISTS idx_search_domain ON search_index (domain_hash);
CREATE INDEX IF NOT EXISTS idx_search_domain_simhash ON search_index (domain_hash, simhash);
CREATE INDEX IF NOT EXISTS idx_search_crawled_at ON search_index (crawled_at DESC);

-- 4. Full-Text Compressed Payloads Table
CREATE TABLE IF NOT EXISTS page_payloads (
    url_hash INTEGER PRIMARY KEY,
    compressed_text BLOB NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (DATETIME('now')),
    FOREIGN KEY (url_hash) REFERENCES search_index(url_hash) ON DELETE CASCADE
);

-- 5. High-Performance FTS5 Virtual Table with Porter Stemmer & BM25
CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
    title,
    snippet,
    canonical_url,
    content='search_index',
    content_rowid='url_hash',
    tokenize = 'porter unicode61'
);

-- Triggers to keep FTS index synchronized with search_index
CREATE TRIGGER IF NOT EXISTS search_index_ai AFTER INSERT ON search_index BEGIN
  INSERT INTO search_fts(rowid, title, snippet, canonical_url)
  VALUES (new.url_hash, new.title, new.snippet, new.canonical_url);
END;

CREATE TRIGGER IF NOT EXISTS search_index_ad AFTER DELETE ON search_index BEGIN
  INSERT INTO search_fts(search_fts, rowid, title, snippet, canonical_url)
  VALUES('delete', old.url_hash, old.title, old.snippet, old.canonical_url);
END;

CREATE TRIGGER IF NOT EXISTS search_index_au AFTER UPDATE ON search_index BEGIN
  INSERT INTO search_fts(search_fts, rowid, title, snippet, canonical_url)
  VALUES('delete', old.url_hash, old.title, old.snippet, old.canonical_url);
  INSERT INTO search_fts(rowid, title, snippet, canonical_url)
  VALUES (new.url_hash, new.title, new.snippet, new.canonical_url);
END;

-- 6. Hot Topics Lexicon
CREATE TABLE IF NOT EXISTS hot_topics (
    term TEXT PRIMARY KEY,
    frequency INTEGER NOT NULL DEFAULT 1,
    last_searched_at TEXT NOT NULL DEFAULT (DATETIME('now'))
);

CREATE INDEX IF NOT EXISTS idx_hot_topics_freq
ON hot_topics (frequency DESC, last_searched_at DESC);

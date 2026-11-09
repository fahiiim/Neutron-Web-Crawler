-- ==============================================================================
-- SUPABASE CONTROL DATABASE SCHEMA (supa-control-db)
-- Purpose: Shard routing, politeness state, active crawl frontier, and query logs.
-- ==============================================================================

-- 1. Shard Registry (Tracks all federated Supabase instances and their sizes)
CREATE TABLE IF NOT EXISTS shard_registry (
    shard_id SMALLINT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    db_connection_uri TEXT NOT NULL,       -- Supavisor pooling connection string
    rest_url TEXT NOT NULL,
    service_role_key TEXT NOT NULL,
    is_writable BOOLEAN NOT NULL DEFAULT TRUE,
    current_size_mb REAL NOT NULL DEFAULT 0.0,
    doc_count INTEGER NOT NULL DEFAULT 0,
    max_capacity_mb REAL NOT NULL DEFAULT 450.0,
    last_health_check TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed initial shard placeholder (to be updated with your actual credentials)
INSERT INTO shard_registry (shard_id, name, db_connection_uri, rest_url, service_role_key, is_writable, current_size_mb, doc_count)
VALUES (1, 'supa-shard-01', 'postgresql://postgres:password@db.xxxx.supabase.co:6543/postgres', 'https://xxxx.supabase.co', 'service-key-here', true, 0.0, 0)
ON CONFLICT (shard_id) DO NOTHING;

-- 2. Domain Politeness & Crawl Delay Ledger
CREATE TABLE IF NOT EXISTS domains (
    domain_hash BIGINT PRIMARY KEY,             -- xxHash64 of eTLD+1
    hostname TEXT NOT NULL UNIQUE,
    crawl_delay_ms INTEGER NOT NULL DEFAULT 1500,
    ema_rtt_ms SMALLINT NOT NULL DEFAULT 250,
    consecutive_failures SMALLINT NOT NULL DEFAULT 0,
    backoff_level SMALLINT NOT NULL DEFAULT 0,
    next_fetch_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    total_crawled INTEGER NOT NULL DEFAULT 0,
    search_hits INTEGER NOT NULL DEFAULT 0,      -- Frequency in user queries
    is_blacklisted BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_domains_politeness 
ON domains (next_fetch_at ASC) 
WHERE is_blacklisted = FALSE;

-- 3. Frontier Queue (Capped rolling buffer of high-priority URLs to crawl)
CREATE UNLOGGED TABLE IF NOT EXISTS frontier_queue (
    url_hash BIGINT PRIMARY KEY,                -- xxHash64 of normalized URL
    domain_hash BIGINT NOT NULL REFERENCES domains(domain_hash) ON DELETE CASCADE,
    compressed_url BYTEA NOT NULL,              -- Zstandard compressed URL string
    priority_score REAL NOT NULL DEFAULT 0.5,   -- Shark-Search + OPIC score
    depth SMALLINT NOT NULL DEFAULT 0,
    status SMALLINT NOT NULL DEFAULT 0,         -- 0=Pending, 1=Leased, 2=Crawled, 3=Failed
    lease_expires_at TIMESTAMPTZ,
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_frontier_priority 
ON frontier_queue (status, priority_score DESC, discovered_at ASC)
WHERE status = 0;

-- 4. Hot Topics Lexicon (Fed by live user searches for Shark-Search focused crawling)
CREATE TABLE IF NOT EXISTS hot_topics (
    term TEXT PRIMARY KEY,
    frequency INTEGER NOT NULL DEFAULT 1,
    last_searched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_hot_topics_freq 
ON hot_topics (frequency DESC, last_searched_at DESC);


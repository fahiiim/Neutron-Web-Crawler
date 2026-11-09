-- ==============================================================================
-- SUPABASE INDEX SHARD SCHEMA (supa-shard-01 .. supa-shard-N)
-- Deploy this exact script to every federated storage shard project.
-- ==============================================================================

-- 1. Search Index Table (Optimized for ~500k-600k rows per 500MB shard)
CREATE TABLE IF NOT EXISTS search_index (
    url_hash BIGINT PRIMARY KEY,                 -- xxHash64 of canonical URL
    domain_hash BIGINT NOT NULL,                 -- xxHash64 of domain
    r2_batch_id VARCHAR(64) NOT NULL,            -- Cloudflare R2 chunk key (e.g. 'batch_20261109_001.zst')
    r2_byte_offset INTEGER NOT NULL,             -- Byte offset in R2 chunk
    r2_byte_length INTEGER NOT NULL,             -- Byte length in R2 chunk
    opic_authority REAL NOT NULL DEFAULT 0.1,     -- On-line Page Importance score (0.0 to 1.0)
    simhash BIGINT NOT NULL,                     -- 64-bit Charikar SimHash for near-duplicate filtering
    crawled_at DATE NOT NULL DEFAULT CURRENT_DATE,
    compressed_meta BYTEA NOT NULL,              -- Zstandard compressed JSON: {url, title, snippet}
    search_tsv TSVECTOR NOT NULL                 -- Weighted tsvector: Title='A', Headings='B', Body='C'
);

-- 2. GIN Index for fast BM25 full-text ranking (<50ms)
CREATE INDEX IF NOT EXISTS idx_search_tsv 
ON search_index USING GIN (search_tsv);

-- 3. Secondary index on domain_hash for domain diversity lookups
CREATE INDEX IF NOT EXISTS idx_search_domain 
ON search_index (domain_hash);

-- 4. Fast helper function to check shard size in MB (used by Capacity Router)
CREATE OR REPLACE FUNCTION get_shard_disk_usage()
RETURNS TABLE (
    total_size_mb REAL,
    table_size_mb REAL,
    index_size_mb REAL,
    doc_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        (pg_database_size(current_database()) / (1024.0 * 1024.0))::REAL AS total_size_mb,
        (pg_total_relation_size('search_index') / (1024.0 * 1024.0))::REAL AS table_size_mb,
        (pg_indexes_size('search_index') / (1024.0 * 1024.0))::REAL AS index_size_mb,
        (SELECT count(*) FROM search_index)::BIGINT AS doc_count;
END;
$$ LANGUAGE plpgsql;

-- 5. Fast Ranked Search RPC called concurrently across all shards
CREATE OR REPLACE FUNCTION search_shard(
    p_query TEXT,
    p_limit INT DEFAULT 15
) RETURNS TABLE (
    url_hash BIGINT,
    compressed_meta BYTEA,
    r2_batch_id VARCHAR(64),
    r2_byte_offset INT,
    r2_byte_length INT,
    rank_score REAL
) AS $$
DECLARE
    v_tsquery TSQUERY;
BEGIN
    -- Convert user query into PostgreSQL websearch tsquery safely
    v_tsquery := websearch_to_tsquery('english', p_query);

    RETURN QUERY
    SELECT 
        si.url_hash,
        si.compressed_meta,
        si.r2_batch_id,
        si.r2_byte_offset,
        si.r2_byte_length,
        -- Weighted composite score: 75% Text Relevance (ts_rank_cd) + 25% Link Authority (OPIC)
        (ts_rank_cd(si.search_tsv, v_tsquery, 32) * 0.75 + si.opic_authority * 0.25)::REAL AS rank_score
    FROM search_index si
    WHERE si.search_tsv @@ v_tsquery
    ORDER BY rank_score DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;


export type SearchMode = 'all' | 'encyclopedia' | 'papers' | 'code' | 'discussions';

export interface SearchResult {
  url_hash: string;
  url: string;
  title: string;
  snippet: string;
  score?: number;
  crawled_at?: string | null;
  isLive?: boolean;
}

export interface AnswerCitation {
  index: number;
  title: string;
  url: string;
  url_hash: string;
  domain: string;
}

export interface GroundedAnswer {
  summary: string;
  citations: AnswerCitation[];
  mode: string;
}

export interface DiscoveryMetric {
  source: string;
  url_count: number;
  duration_ms: number;
}

export interface CrawlItemStatus {
  url: string;
  domain: string;
  title?: string;
  status: 'pending' | 'success' | 'blocked' | 'error';
  durationMs?: number;
  detail?: string;
}

export interface SearchTimings {
  index_ms: number;
  crawl_ms: number;
  synth_ms: number;
  total_ms: number;
}

export interface EngineStats {
  pages_indexed: number;
  domains_covered: number;
  frontier_pending: number;
  payloads_stored: number;
  connected: boolean;
  background_crawler_active?: boolean;
  bloom_entries?: number;
  uptime_seconds: number;
}

export interface TrendingItem {
  topic?: string;
  hits?: number;
  term?: string;
  count?: number;
}

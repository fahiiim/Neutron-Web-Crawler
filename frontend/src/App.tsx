import { Globe, Lock, ShieldCheck, Zap } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { CrawlProgressDrawer } from './components/CrawlProgressDrawer';
import { DocumentModal } from './components/DocumentModal';
import { Header } from './components/Header';
import { ResultCard } from './components/ResultCard';
import { SearchBar } from './components/SearchBar';
import { StatsDrawer } from './components/StatsDrawer';
import { CrawlItemStatus, DiscoveryMetric, SearchResult } from './types';
import { safeHttpUrl } from './utils/format';

const CURATED_TOPICS = [
  'Quantum error correction',
  'Rust async runtime',
  'DeepSeek R1 architecture',
  'Turso LibSQL FTS5',
];

const HISTORY_KEY = 'neutron_search_history';

export function App() {
  const [queryInput, setQueryInput] = useState('');
  const [activeQuery, setActiveQuery] = useState('');
  const [hasSearched, setHasSearched] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);

  const [trendingChips, setTrendingChips] = useState<string[]>(CURATED_TOPICS);
  const [recentSearches, setRecentSearches] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
    } catch {
      return [];
    }
  });

  const [showTelemetry, setShowTelemetry] = useState(false);
  const [telemetryExpanded, setTelemetryExpanded] = useState(true);
  const [indexStatus, setIndexStatus] = useState<{ count: number; durationMs: number } | null>(null);
  const [discoveryMetrics, setDiscoveryMetrics] = useState<DiscoveryMetric[]>([]);
  const [crawlItems, setCrawlItems] = useState<CrawlItemStatus[]>([]);

  const [statsOpen, setStatsOpen] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [modalIdx, setModalIdx] = useState<number>(-1);
  const [deepDocHash, setDeepDocHash] = useState<string | null>(null);
  const [focusedCardIdx, setFocusedCardIdx] = useState<number>(-1);

  const inputRef = useRef<HTMLInputElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const autoCollapseRef = useRef<number | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch('/trending');
        if (res.ok) {
          const data = await res.json();
          const terms: string[] = (data.trending || [])
            .map((t: { term: string }) => t.term.trim())
            .filter((t: string) => t.length >= 2 && t.length <= 36);
          if (terms.length >= 3) {
            setTrendingChips(terms.slice(0, 4));
          }
        }
      } catch {
        // keep curated chips
      }
    })();
  }, []);

  const persistHistory = useCallback((q: string) => {
    setRecentSearches((prev) => {
      const next = [q, ...prev.filter((item) => item.toLowerCase() !== q.toLowerCase())].slice(0, 15);
      localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const executeSearch = useCallback(
    (rawQuery: string) => {
      const clean = rawQuery.trim();
      if (!clean) return;

      if (eventSourceRef.current) eventSourceRef.current.close();
      if (autoCollapseRef.current) window.clearTimeout(autoCollapseRef.current);

      persistHistory(clean);
      setQueryInput(clean);
      setActiveQuery(clean);
      setHasSearched(true);
      setIsSearching(true);
      setResults([]);
      setLatencyMs(null);
      setFocusedCardIdx(-1);
      setShowTelemetry(false);
      setTelemetryExpanded(true);
      setIndexStatus(null);
      setDiscoveryMetrics([]);
      setCrawlItems([]);

      const t0 = performance.now();
      const seen = new Set<string>();

      const addResult = (item: SearchResult, isLive: boolean) => {
        const url = safeHttpUrl(item.url);
        if (url === '#' || seen.has(url)) return;
        seen.add(url);
        setResults((prev) => [...prev, { ...item, url, isLive }]);
      };

      const runFallback = async () => {
        try {
          const res = await fetch(`/search?q=${encodeURIComponent(clean)}`);
          if (res.ok) {
            const data = await res.json();
            (data.results || []).forEach((item: SearchResult) =>
              addResult(item, data.source !== 'index_cache')
            );
          }
        } catch {
          // ignore
        } finally {
          setIsSearching(false);
          setLatencyMs(Math.round(performance.now() - t0));
        }
      };

      try {
        const es = new EventSource(`/search/stream?q=${encodeURIComponent(clean)}`);
        eventSourceRef.current = es;

        es.addEventListener('cached_results', (ev) => {
          const data = JSON.parse(ev.data);
          setIndexStatus({
            count: data.count || 0,
            durationMs: data.duration_ms || Math.round(performance.now() - t0),
          });
          (data.results || []).forEach((item: SearchResult) => addResult(item, false));
        });

        es.addEventListener('discovery_start', () => {
          setShowTelemetry(true);
          setTelemetryExpanded(true);
        });

        es.addEventListener('discovery_result', (ev) => {
          const metric: DiscoveryMetric = JSON.parse(ev.data);
          setShowTelemetry(true);
          setDiscoveryMetrics((prev) => [
            ...prev.filter((m) => m.source !== metric.source),
            metric,
          ]);
        });

        es.addEventListener('crawl_start', (ev) => {
          const data = JSON.parse(ev.data);
          setShowTelemetry(true);
          setCrawlItems((prev) => [
            ...prev.filter((c) => c.url !== data.url),
            { url: data.url, domain: data.domain, status: 'fetching', detail: 'fetching...' },
          ]);
        });

        es.addEventListener('crawl_success', (ev) => {
          const data = JSON.parse(ev.data);
          setCrawlItems((prev) =>
            prev.map((c) =>
              c.url === data.url
                ? { ...c, status: 'indexed', detail: `${data.duration_ms}ms` }
                : c
            )
          );
        });

        es.addEventListener('crawl_blocked', (ev) => {
          const data = JSON.parse(ev.data);
          setCrawlItems((prev) =>
            prev.map((c) =>
              c.url === data.url
                ? { ...c, status: 'blocked', detail: data.reason || 'robots.txt' }
                : c
            )
          );
        });

        es.addEventListener('crawl_error', (ev) => {
          const data = JSON.parse(ev.data);
          setCrawlItems((prev) =>
            prev.map((c) =>
              c.url === data.url
                ? { ...c, status: 'error', detail: data.error || 'skipped' }
                : c
            )
          );
        });

        es.addEventListener('live_result', (ev) => {
          addResult(JSON.parse(ev.data), true);
        });

        es.addEventListener('done', () => {
          setIsSearching(false);
          setLatencyMs(Math.round(performance.now() - t0));
          es.close();
          autoCollapseRef.current = window.setTimeout(() => {
            setTelemetryExpanded(false);
          }, 2400);
        });

        es.onerror = () => {
          es.close();
          if (seen.size === 0) {
            runFallback();
          } else {
            setIsSearching(false);
            setLatencyMs(Math.round(performance.now() - t0));
          }
        };
      } catch {
        runFallback();
      }
    },
    [persistHistory]
  );

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const qParam = params.get('q');
    const docParam = params.get('doc');
    if (qParam) {
      executeSearch(qParam);
    } else if (docParam && /^-?\d+$/.test(docParam)) {
      setDeepDocHash(docParam);
      setModalOpen(true);
    }
  }, [executeSearch]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (modalOpen || statsOpen) return;

      if ((e.key === 'k' || e.key === 'K') && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
        return;
      }

      const activeTag = document.activeElement?.tagName.toLowerCase();
      if (activeTag === 'input' || activeTag === 'textarea') return;

      if (e.key === '/') {
        e.preventDefault();
        inputRef.current?.focus();
      } else if (e.key === 'j' && results.length > 0) {
        setFocusedCardIdx((i) => Math.min(results.length - 1, i + 1));
      } else if (e.key === 'k' && results.length > 0) {
        setFocusedCardIdx((i) => Math.max(0, i - 1));
      } else if (e.key === 'Enter' && focusedCardIdx >= 0 && results[focusedCardIdx]) {
        setDeepDocHash(null);
        setModalIdx(focusedCardIdx);
        setModalOpen(true);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [modalOpen, statsOpen, results, focusedCardIdx]);

  const resetToHome = () => {
    if (eventSourceRef.current) eventSourceRef.current.close();
    setHasSearched(false);
    setResults([]);
    setActiveQuery('');
    setQueryInput('');
    setShowTelemetry(false);
    setLatencyMs(null);
    inputRef.current?.focus();
  };

  const activeDoc = modalIdx >= 0 && results[modalIdx] ? results[modalIdx] : null;
  const activeUrlHash = deepDocHash ?? (activeDoc ? String(activeDoc.url_hash) : null);

  return (
    <div className="min-h-screen bg-black text-white flex flex-col justify-between relative">
      {/* Static subtle spotlight & dot grid (no animations) */}
      <div
        aria-hidden="true"
        className="hero-backdrop fixed inset-x-0 top-0 h-[520px] pointer-events-none z-0"
      />

      <div className="relative z-10 flex flex-col min-h-screen">
        <Header
          onOpenStats={() => setStatsOpen(true)}
          onResetHome={resetToHome}
          compact={hasSearched}
        />

        {!hasSearched ? (
          <main className="flex-1 flex flex-col items-center justify-center px-4 sm:px-6 pb-20 pt-10">
            <div className="w-full max-w-2xl text-center">
              <div className="inline-flex items-center space-x-2 px-3.5 py-1 rounded-full surface-panel text-[11px] font-mono text-white mb-6">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shadow-[0_0_8px_#4ade80]" />
                <span>DECENTRALIZED</span>
                <span className="text-white/40">&middot;</span>
                <span className="text-glow-green">REAL-TIME SEARCH</span>
              </div>

              <h1 className="font-varsity text-4xl sm:text-6xl text-white mb-4 leading-[1.12]">
                SEARCH THE <span className="text-glow-green">LIVE WEB</span>
              </h1>
              <p className="font-classic text-[15px] sm:text-base text-white/90 max-w-lg mx-auto mb-9 leading-relaxed">
                Sub-15ms indexed retrieval paired with live parallel crawling, clean
                markdown reading, and zero telemetry.
              </p>

              <SearchBar
                query={queryInput}
                onQueryChange={setQueryInput}
                onSubmit={executeSearch}
                recentSearches={recentSearches}
                onClearRecent={() => {
                  localStorage.removeItem(HISTORY_KEY);
                  setRecentSearches([]);
                }}
                compact={false}
                inputRef={inputRef}
              />

              {/* Prompt Chips */}
              <div className="mt-5 flex items-center justify-center flex-wrap gap-2 font-classic">
                {trendingChips.map((chip) => (
                  <button
                    key={chip}
                    type="button"
                    onClick={() => executeSearch(chip)}
                    className="text-xs px-3.5 py-1.5 rounded-lg surface-interactive text-white hover:text-[#4ade80] truncate max-w-[230px]"
                  >
                    {chip}
                  </button>
                ))}
              </div>

              {/* Clean 3-pillar trust strip */}
              <div className="mt-10 pt-6 border-t border-white/[0.08] flex flex-wrap items-center justify-center gap-x-7 gap-y-2 text-xs font-classic text-white/90">
                <span className="inline-flex items-center space-x-1.5">
                  <Zap className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Sub-15ms FTS5</span>
                </span>
                <span className="inline-flex items-center space-x-1.5">
                  <Globe className="w-3.5 h-3.5 text-emerald-400" />
                  <span>6 Live Discovery Sources</span>
                </span>
                <span className="inline-flex items-center space-x-1.5">
                  <Lock className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Zero Tracking</span>
                </span>
              </div>
            </div>
          </main>
        ) : (
          <main className="flex-1 w-full max-w-3xl mx-auto px-4 sm:px-6 py-6">
            <div className="mb-5">
              <SearchBar
                query={queryInput}
                onQueryChange={setQueryInput}
                onSubmit={executeSearch}
                recentSearches={recentSearches}
                onClearRecent={() => {
                  localStorage.removeItem(HISTORY_KEY);
                  setRecentSearches([]);
                }}
                compact={true}
                inputRef={inputRef}
              />
            </div>

            <div className="flex items-center justify-between text-xs font-mono text-white mb-3 px-0.5">
              <span>
                {isSearching
                  ? `Searching "${activeQuery}"...`
                  : `${results.length} ${results.length === 1 ? 'result' : 'results'} for "${activeQuery}"`}
              </span>
              {latencyMs !== null && (
                <span className="text-glow-green">{latencyMs}ms</span>
              )}
            </div>

            <CrawlProgressDrawer
              visible={showTelemetry}
              expanded={telemetryExpanded}
              onToggleExpand={() => setTelemetryExpanded((e) => !e)}
              indexStatus={indexStatus}
              discoveryMetrics={discoveryMetrics}
              crawlItems={crawlItems}
              isSearching={isSearching}
            />

            {isSearching && results.length === 0 && (
              <div className="space-y-3" aria-hidden="true">
                {[1, 2, 3].map((k) => (
                  <div
                    key={k}
                    className="surface-panel rounded-xl p-5 space-y-2.5"
                  >
                    <div className="h-3 w-36 bg-white/10 rounded" />
                    <div className="h-4 w-3/4 bg-white/15 rounded" />
                    <div className="h-3 w-full bg-white/10 rounded" />
                  </div>
                ))}
              </div>
            )}

            {!isSearching && results.length === 0 && (
              <div className="surface-panel rounded-xl p-8 text-center">
                <p className="font-varsity text-sm text-white mb-1.5">
                  NO DOCUMENTS FOUND FOR &ldquo;{activeQuery}&rdquo;
                </p>
                <p className="font-classic text-xs text-white/85">
                  Try shorter technical terms or broaden your search keywords.
                </p>
              </div>
            )}

            {results.length > 0 && (
              <ul role="list" className="space-y-3">
                {results.map((item, idx) => (
                  <ResultCard
                    key={item.url}
                    item={item}
                    query={activeQuery}
                    focused={idx === focusedCardIdx}
                    onOpenReader={() => {
                      setDeepDocHash(null);
                      setModalIdx(idx);
                      setModalOpen(true);
                    }}
                  />
                ))}
              </ul>
            )}
          </main>
        )}

        <footer className="border-t border-white/[0.1] bg-black py-4 px-4 sm:px-6 text-xs text-white font-classic">
          <div className="max-w-5xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-2">
            <div className="inline-flex items-center space-x-2">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
              <span>Zero tracking, cookies, or telemetry</span>
            </div>
            <div className="flex items-center space-x-5 font-mono text-[11px] text-white">
              <a href="/privacy" className="hover:text-[#4ade80] transition-colors">
                Privacy
              </a>
              <a
                href="/docs"
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-[#4ade80] transition-colors"
              >
                API Docs
              </a>
              <a
                href="/health"
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-[#4ade80] transition-colors"
              >
                Status
              </a>
              <a
                href="https://github.com/fahiiim/Neutron-Web-Crawler"
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-[#4ade80] transition-colors"
              >
                GitHub
              </a>
            </div>
          </div>
        </footer>
      </div>

      <DocumentModal
        open={modalOpen}
        urlHash={activeUrlHash}
        initialTitle={activeDoc?.title || 'Document Reader'}
        initialUrl={activeDoc?.url}
        canPrev={deepDocHash === null && modalIdx > 0}
        canNext={deepDocHash === null && modalIdx >= 0 && modalIdx < results.length - 1}
        onPrev={() => setModalIdx((i) => Math.max(0, i - 1))}
        onNext={() => setModalIdx((i) => Math.min(results.length - 1, i + 1))}
        onClose={() => {
          setModalOpen(false);
          setDeepDocHash(null);
        }}
      />

      <StatsDrawer open={statsOpen} onClose={() => setStatsOpen(false)} />
    </div>
  );
}

export default App;

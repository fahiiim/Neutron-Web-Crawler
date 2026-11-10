import { ShieldCheck } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { CrawlProgressDrawer } from './components/CrawlProgressDrawer';
import { DocumentModal } from './components/DocumentModal';
import { Header } from './components/Header';
import { NeutronStarCanvas } from './components/NeutronStarCanvas';
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
const THEME_KEY = 'neutron_theme_preference';

export function App() {
  const [lightMode, setLightMode] = useState<boolean>(() => {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === 'light') return true;
    if (saved === 'dark') return false;
    return window.matchMedia('(prefers-color-scheme: light)').matches;
  });

  const [queryInput, setQueryInput] = useState('');
  const [activeQuery, setActiveQuery] = useState('');
  const [hasSearched, setHasSearched] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [pulseSignal, setPulseSignal] = useState(0);

  // Trending & Recent
  const [trendingChips, setTrendingChips] = useState<string[]>(CURATED_TOPICS);
  const [recentSearches, setRecentSearches] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
    } catch {
      return [];
    }
  });

  // Live Crawl Telemetry
  const [showTelemetry, setShowTelemetry] = useState(false);
  const [telemetryExpanded, setTelemetryExpanded] = useState(true);
  const [indexStatus, setIndexStatus] = useState<{ count: number; durationMs: number } | null>(null);
  const [discoveryMetrics, setDiscoveryMetrics] = useState<DiscoveryMetric[]>([]);
  const [crawlItems, setCrawlItems] = useState<CrawlItemStatus[]>([]);

  // Modals & Navigation
  const [statsOpen, setStatsOpen] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [modalIdx, setModalIdx] = useState<number>(-1);
  const [deepDocHash, setDeepDocHash] = useState<string | null>(null);
  const [focusedCardIdx, setFocusedCardIdx] = useState<number>(-1);

  const inputRef = useRef<HTMLInputElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const autoCollapseRef = useRef<number | null>(null);

  useEffect(() => {
    const root = document.documentElement;
    if (lightMode) {
      root.classList.add('light');
      root.classList.remove('dark');
    } else {
      root.classList.remove('light');
      root.classList.add('dark');
    }
    localStorage.setItem(THEME_KEY, lightMode ? 'light' : 'dark');
  }, [lightMode]);

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
        // Keep clean curated fallback chips
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

      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
      if (autoCollapseRef.current) {
        window.clearTimeout(autoCollapseRef.current);
      }

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
      setPulseSignal((p) => p + 1);

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
          setDiscoveryMetrics((prev) => {
            const filtered = prev.filter((m) => m.source !== metric.source);
            return [...filtered, metric];
          });
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

  // Check URL ?q= or ?doc= deep-link on initial mount
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

  // Global keyboard shortcuts
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
  const activeUrlHash = deepDocHash ?? (activeDoc ? activeDoc.url_hash : null);

  return (
    <div className="min-h-screen flex flex-col justify-between relative">
      {/* Real-time 3D WebGL Spinning Neutron Star */}
      <NeutronStarCanvas
        dimmed={hasSearched}
        pulseSignal={pulseSignal}
        lightMode={lightMode}
      />

      <div className="relative z-10 flex flex-col min-h-screen">
        <Header
          lightMode={lightMode}
          onToggleTheme={() => setLightMode((m) => !m)}
          onOpenStats={() => setStatsOpen(true)}
          onResetHome={resetToHome}
          compact={hasSearched}
        />

        {/* Main Viewport */}
        {!hasSearched ? (
          /* Centered Executive Landing View */
          <main className="flex-1 flex flex-col items-center justify-center px-4 sm:px-6 pb-20 pt-8">
            <div className="w-full max-w-2xl text-center">
              <div className="inline-flex items-center space-x-2 px-3 py-1 rounded-full surface-panel text-[11px] font-mono text-secondary-theme mb-5">
                <span className="w-1.5 h-1.5 rounded-full bg-sky-400" />
                <span>Turso FTS5 &middot; Live JIT Web Crawler</span>
              </div>

              <h1 className="text-3xl sm:text-5xl font-semibold tracking-[-0.03em] text-primary-theme mb-3">
                Search the open web, transparently.
              </h1>
              <p className="text-sm sm:text-[15px] text-secondary-theme max-w-lg mx-auto mb-8 leading-relaxed">
                Sub-15ms indexed retrieval with parallel live crawling, markdown
                extraction, and zero user telemetry.
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

              {/* Single Clean Curated Prompt Row */}
              <div className="mt-5 flex items-center justify-center flex-wrap gap-2">
                {trendingChips.map((chip) => (
                  <button
                    key={chip}
                    type="button"
                    onClick={() => executeSearch(chip)}
                    className="text-xs px-3 py-1.5 rounded-lg surface-interactive text-secondary-theme hover:text-primary-theme truncate max-w-[230px]"
                  >
                    {chip}
                  </button>
                ))}
              </div>
            </div>
          </main>
        ) : (
          /* Compact Docked Search Results View */
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

            {/* Result Summary Header */}
            <div className="flex items-center justify-between text-xs font-mono text-muted-theme mb-3 px-0.5">
              <span>
                {isSearching
                  ? `Searching "${activeQuery}"...`
                  : `${results.length} ${results.length === 1 ? 'result' : 'results'} for "${activeQuery}"`}
              </span>
              {latencyMs !== null && <span>{latencyMs}ms</span>}
            </div>

            {/* Transparent Live Crawl Telemetry */}
            <CrawlProgressDrawer
              visible={showTelemetry}
              expanded={telemetryExpanded}
              onToggleExpand={() => setTelemetryExpanded((e) => !e)}
              indexStatus={indexStatus}
              discoveryMetrics={discoveryMetrics}
              crawlItems={crawlItems}
              isSearching={isSearching}
            />

            {/* Skeletons while awaiting first result */}
            {isSearching && results.length === 0 && (
              <div className="space-y-3" aria-hidden="true">
                {[1, 2, 3].map((k) => (
                  <div
                    key={k}
                    className="surface-panel rounded-xl p-5 space-y-2.5 animate-pulse"
                  >
                    <div className="h-3 w-36 bg-white/[0.06] rounded" />
                    <div className="h-4 w-3/4 bg-white/[0.09] rounded" />
                    <div className="h-3 w-full bg-white/[0.05] rounded" />
                  </div>
                ))}
              </div>
            )}

            {/* Empty State */}
            {!isSearching && results.length === 0 && (
              <div className="surface-panel rounded-xl p-8 text-center">
                <p className="text-sm font-medium text-primary-theme mb-1">
                  No documents found for &ldquo;{activeQuery}&rdquo;
                </p>
                <p className="text-xs text-muted-theme">
                  Try shorter technical terms or broaden your search keywords.
                </p>
              </div>
            )}

            {/* Editorial Results Feed */}
            {results.length > 0 && (
              <ul role="list" className="space-y-3">
                {results.map((item, idx) => (
                  <ResultCard
                    key={item.url}
                    item={item}
                    query={activeQuery}
                    index={idx}
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

        {/* Quiet Editorial Footer */}
        <footer className="border-t border-white/[0.06] py-4 px-4 sm:px-6 text-xs text-muted-theme">
          <div className="max-w-5xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-2">
            <div className="inline-flex items-center space-x-2">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
              <span>Zero tracking, cookies, or telemetry</span>
            </div>
            <div className="flex items-center space-x-5 font-mono text-[11px]">
              <a href="/privacy" className="hover:text-primary-theme transition-colors">
                Privacy
              </a>
              <a
                href="/docs"
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-primary-theme transition-colors"
              >
                API Docs
              </a>
              <a
                href="/health"
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-primary-theme transition-colors"
              >
                Status
              </a>
              <a
                href="https://github.com/fahiiim/Neutron-Web-Crawler"
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-primary-theme transition-colors"
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

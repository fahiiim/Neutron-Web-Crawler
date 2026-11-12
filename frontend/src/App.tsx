import { useCallback, useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { Header } from "./components/Header";
import { SearchBar } from "./components/SearchBar";
import { AnswerCard } from "./components/AnswerCard";
import { ResultCard } from "./components/ResultCard";
import {
  CrawlProgressDrawer,
  type CrawlItemStatus,
} from "./components/CrawlProgressDrawer";
import { StatsDrawer } from "./components/StatsDrawer";
import { DocumentModal, type ReaderTarget } from "./components/DocumentModal";
import type {
  EngineStats,
  GroundedAnswer,
  SearchMode,
  SearchResult,
} from "./types";
import { apiUrl, setApiBaseUrl } from "./utils/api";

const SEARCH_MODES: { id: SearchMode; label: string }[] = [
  { id: "all", label: "All" },
  { id: "encyclopedia", label: "Encyclopedia" },
  { id: "papers", label: "Papers" },
  { id: "code", label: "Code" },
  { id: "discussions", label: "Discussions" },
];

const EXAMPLE_QUERIES = [
  "how does crispr work",
  "rust ownership model",
  "who wrote harry potter",
  "latest james webb discoveries",
];

const RECENT_KEY = "neutron_recent_queries_v1";
const SESSION_CACHE_PREFIX = "neutron_scache_v1:";
const SESSION_CACHE_TTL_MS = 5 * 60 * 1000;

interface CachedSearchEntry {
  ts: number;
  results: SearchResult[];
  answer: GroundedAnswer | null;
}

function loadCachedSearch(q: string, m: SearchMode): CachedSearchEntry | null {
  try {
    const raw = sessionStorage.getItem(`${SESSION_CACHE_PREFIX}${m}:${q.toLowerCase()}`);
    if (!raw) return null;
    const parsed: CachedSearchEntry = JSON.parse(raw);
    if (!parsed || Date.now() - parsed.ts > SESSION_CACHE_TTL_MS) return null;
    return parsed;
  } catch {
    return null;
  }
}

function saveCachedSearch(
  q: string,
  m: SearchMode,
  results: SearchResult[],
  answer: GroundedAnswer | null,
): void {
  if (!results.length) return;
  try {
    const entry: CachedSearchEntry = { ts: Date.now(), results, answer };
    sessionStorage.setItem(
      `${SESSION_CACHE_PREFIX}${m}:${q.toLowerCase()}`,
      JSON.stringify(entry),
    );
  } catch {
    // Ignore storage quota errors
  }
}

function loadRecent(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed)
      ? parsed.filter((s): s is string => typeof s === "string").slice(0, 8)
      : [];
  } catch {
    return [];
  }
}

export function App() {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("all");
  const [searched, setSearched] = useState(false);
  const [activeQuery, setActiveQuery] = useState("");

  const [results, setResults] = useState<SearchResult[]>([]);
  const [answer, setAnswer] = useState<GroundedAnswer | null>(null);
  const [loading, setLoading] = useState(false);
  const [slowWake, setSlowWake] = useState(false);
  const [crawling, setCrawling] = useState(false);
  const [statusText, setStatusText] = useState("");
  const [crawlItems, setCrawlItems] = useState<CrawlItemStatus[]>([]);
  const [elapsedMs, setElapsedMs] = useState<number | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const [recentQueries, setRecentQueries] = useState<string[]>(loadRecent);
  const [trendingQueries, setTrendingQueries] = useState<string[]>(EXAMPLE_QUERIES);
  const [selectedIdx, setSelectedIdx] = useState(-1);
  const [readerTarget, setReaderTarget] = useState<ReaderTarget | null>(null);
  const [statsOpen, setStatsOpen] = useState(false);
  const [stats, setStats] = useState<EngineStats | null>(null);

  const searchInputRef = useRef<HTMLInputElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  const saveRecent = useCallback((q: string) => {
    setRecentQueries((prev) => {
      const next = [q, ...prev.filter((item) => item !== q)].slice(0, 8);
      try {
        localStorage.setItem(RECENT_KEY, JSON.stringify(next));
      } catch {
        // Ignore storage quota issues
      }
      return next;
    });
  }, []);

  const clearRecent = useCallback(() => {
    setRecentQueries([]);
    try {
      localStorage.removeItem(RECENT_KEY);
    } catch {
      // Ignore storage errors
    }
  }, []);

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch(apiUrl("/stats"));
      if (!res.ok) return;
      const data = await res.json();
      setStats(data);
    } catch {
      // Keep UI quiet on transient stats failure
    }
  }, []);

  const fetchTrending = useCallback(async () => {
    try {
      const res = await fetch(apiUrl("/trending"));
      if (!res.ok) return;
      const data = await res.json();
      const rows = Array.isArray(data?.trending) ? data.trending : [];
      const topics = rows
        .map((r: { topic?: string; term?: string }) => (r.topic || r.term || "").trim())
        .filter(Boolean)
        .slice(0, 6);
      if (topics.length > 0) {
        setTrendingQueries(topics);
      }
    } catch {
      // Keep fallback example chips silently
    }
  }, []);

  useEffect(() => {
    fetchStats();
    fetchTrending();
  }, [fetchStats, fetchTrending]);

  useEffect(() => {
    if (!loading || results.length > 0) {
      setSlowWake(false);
      return;
    }
    const timer = window.setTimeout(() => setSlowWake(true), 4000);
    return () => window.clearTimeout(timer);
  }, [loading, results.length]);

  const stopStream = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  const fallbackJsonSearch = useCallback(
    async (
      cleanQuery: string,
      searchMode: SearchMode,
      t0: number,
      refresh = false,
    ) => {
      try {
        const res = await fetch(
          apiUrl(
            `/search?q=${encodeURIComponent(cleanQuery)}&mode=${encodeURIComponent(searchMode)}${
              refresh ? "&refresh=true" : ""
            }`,
          ),
        );
        const data = await res.json().catch(() => null);
        if (!res.ok) {
          throw new Error(data?.detail || `Search failed (${res.status})`);
        }
        const nextResults: SearchResult[] = Array.isArray(data?.results) ? data.results : [];
        const nextAnswer: GroundedAnswer | null = data?.answer || null;
        setResults(nextResults);
        setAnswer(nextAnswer);
        setElapsedMs(Math.round(performance.now() - t0));
        saveCachedSearch(cleanQuery, searchMode, nextResults, nextAnswer);
      } catch (err) {
        setErrorMsg(
          err instanceof Error ? err.message : "Search request failed",
        );
      } finally {
        setLoading(false);
        setCrawling(false);
      }
    },
    [],
  );

  const runSearch = useCallback(
    (
      rawQuery: string,
      targetMode: SearchMode = mode,
      pushUrl = true,
      refresh = false,
    ) => {
      const cleanQuery = rawQuery.trim();
      if (!cleanQuery) return;

      stopStream();
      const t0 = performance.now();

      setQuery(cleanQuery);
      setActiveQuery(cleanQuery);
      setMode(targetMode);
      setSearched(true);
      setCrawling(false);
      setStatusText("");
      setCrawlItems([]);
      setErrorMsg(null);
      setSelectedIdx(-1);

      saveRecent(cleanQuery);

      if (pushUrl) {
        const params = new URLSearchParams();
        params.set("q", cleanQuery);
        if (targetMode !== "all") params.set("mode", targetMode);
        window.history.pushState(null, "", `?${params.toString()}`);
      }

      if (!refresh) {
        const cached = loadCachedSearch(cleanQuery, targetMode);
        if (cached) {
          setResults(cached.results);
          setAnswer(cached.answer);
          setElapsedMs(Math.max(1, Math.round(performance.now() - t0)));
          setLoading(false);
          return;
        }
      }

      setLoading(true);
      setResults([]);
      setAnswer(null);
      setElapsedMs(null);

      const streamUrl = apiUrl(
        `/search/stream?q=${encodeURIComponent(cleanQuery)}&mode=${encodeURIComponent(targetMode)}${
          refresh ? "&refresh=true" : ""
        }`,
      );
      const es = new EventSource(streamUrl);
      eventSourceRef.current = es;
      let finished = false;
      let latestResults: SearchResult[] = [];
      let latestAnswer: GroundedAnswer | null = null;

      es.addEventListener("cached_results", (ev: MessageEvent) => {
        try {
          const payload = JSON.parse(ev.data);
          if (Array.isArray(payload?.results)) {
            latestResults = payload.results;
            setResults(payload.results);
          }
          if (typeof payload?.duration_ms === "number") {
            setElapsedMs(payload.duration_ms);
          }
        } catch {
          // Ignore malformed event
        }
      });

      es.addEventListener("status", (ev: MessageEvent) => {
        try {
          const payload = JSON.parse(ev.data);
          setCrawling(true);
          if (payload?.message) setStatusText(String(payload.message));
        } catch {
          // Ignore
        }
      });

      es.addEventListener("discovery_start", () => {
        setCrawling(true);
      });

      es.addEventListener("crawl_start", (ev: MessageEvent) => {
        try {
          const payload = JSON.parse(ev.data);
          setCrawling(true);
          if (!payload?.url) return;
          setCrawlItems((prev) => {
            if (prev.some((i) => i.url === payload.url)) return prev;
            return [
              ...prev,
              {
                url: payload.url,
                domain: payload.domain || payload.url,
                status: "pending",
              },
            ];
          });
        } catch {
          // Ignore
        }
      });

      es.addEventListener("crawl_success", (ev: MessageEvent) => {
        try {
          const payload = JSON.parse(ev.data);
          setCrawlItems((prev) =>
            prev.map((item) =>
              item.url === payload.url
                ? {
                    ...item,
                    status: "success",
                    title: payload.title,
                    durationMs: payload.duration_ms,
                  }
                : item,
            ),
          );
        } catch {
          // Ignore
        }
      });

      es.addEventListener("crawl_blocked", (ev: MessageEvent) => {
        try {
          const payload = JSON.parse(ev.data);
          setCrawlItems((prev) =>
            prev.map((item) =>
              item.url === payload.url
                ? { ...item, status: "blocked", detail: payload.reason }
                : item,
            ),
          );
        } catch {
          // Ignore
        }
      });

      es.addEventListener("crawl_error", (ev: MessageEvent) => {
        try {
          const payload = JSON.parse(ev.data);
          setCrawlItems((prev) =>
            prev.map((item) =>
              item.url === payload.url
                ? { ...item, status: "error", detail: payload.error }
                : item,
            ),
          );
        } catch {
          // Ignore
        }
      });

      es.addEventListener("live_result", (ev: MessageEvent) => {
        try {
          const doc: SearchResult = JSON.parse(ev.data);
          const idx = latestResults.findIndex((r) => r.url === doc.url);
          if (idx >= 0) {
            latestResults = latestResults.map((r, i) => (i === idx ? doc : r));
          } else {
            latestResults = [...latestResults, doc];
          }
          setResults((prev) => {
            const prevIdx = prev.findIndex((r) => r.url === doc.url);
            if (prevIdx >= 0) {
              return prev.map((r, i) => (i === prevIdx ? doc : r));
            }
            return [...prev, doc];
          });
        } catch {
          // Ignore
        }
      });

      es.addEventListener("answer", (ev: MessageEvent) => {
        try {
          const parsed: GroundedAnswer = JSON.parse(ev.data);
          latestAnswer = parsed;
          setAnswer(parsed);
        } catch {
          // Ignore
        }
      });

      es.addEventListener("backend_error", (ev: MessageEvent) => {
        try {
          const payload = JSON.parse(ev.data);
          setErrorMsg(
            payload?.detail ||
              "Search services are waking up or temporarily unavailable. Please retry in a few seconds.",
          );
        } catch {
          setErrorMsg(
            "Search services are waking up or temporarily unavailable. Please retry in a few seconds.",
          );
        }
      });

      es.addEventListener("done", () => {
        finished = true;
        setLoading(false);
        setCrawling(false);
        setElapsedMs(Math.round(performance.now() - t0));
        saveCachedSearch(cleanQuery, targetMode, latestResults, latestAnswer);
        es.close();
        eventSourceRef.current = null;
        fetchStats();
      });

      es.onerror = () => {
        es.close();
        eventSourceRef.current = null;
        if (!finished) {
          fallbackJsonSearch(cleanQuery, targetMode, t0, refresh);
        }
      };
    },
    [mode, stopStream, saveRecent, fetchStats, fallbackJsonSearch],
  );

  // Sync URL query parameters on mount and back/forward navigation
  useEffect(() => {
    const syncFromUrl = () => {
      const params = new URLSearchParams(window.location.search);
      const apiOverride = (params.get("api") || "").trim();
      if (apiOverride) {
        setApiBaseUrl(apiOverride);
        fetchStats();
      }
      const q = (params.get("q") || "").trim();
      const m = (params.get("mode") || "all") as SearchMode;
      const validMode = SEARCH_MODES.some((sm) => sm.id === m) ? m : "all";
      if (q) {
        runSearch(q, validMode, false);
      } else {
        stopStream();
        setSearched(false);
        setQuery("");
        setActiveQuery("");
        setResults([]);
        setAnswer(null);
      }
    };
    syncFromUrl();
    window.addEventListener("popstate", syncFromUrl);
    return () => {
      window.removeEventListener("popstate", syncFromUrl);
      stopStream();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keyboard shortcuts: / or Ctrl+K to focus, j/k to navigate results
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      const isTyping = tag === "INPUT" || tag === "TEXTAREA";

      if ((e.key === "/" && !isTyping) || ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k")) {
        e.preventDefault();
        searchInputRef.current?.focus();
        return;
      }

      if (isTyping || readerTarget || statsOpen || !searched || results.length === 0) {
        return;
      }

      if (e.key === "j") {
        e.preventDefault();
        setSelectedIdx((prev) => Math.min(results.length - 1, prev + 1));
      } else if (e.key === "k") {
        e.preventDefault();
        setSelectedIdx((prev) => Math.max(0, prev - 1));
      } else if (e.key === "Enter" && selectedIdx >= 0 && results[selectedIdx]) {
        e.preventDefault();
        window.open(results[selectedIdx].url, "_blank", "noopener,noreferrer");
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [searched, results, selectedIdx, readerTarget, statsOpen]);

  const handleGoHome = () => {
    stopStream();
    setSearched(false);
    setQuery("");
    setActiveQuery("");
    setResults([]);
    setAnswer(null);
    setErrorMsg(null);
    setLoading(false);
    setCrawling(false);
    window.history.pushState(null, "", window.location.pathname);
  };

  const handleModeChange = (nextMode: SearchMode) => {
    setMode(nextMode);
    if (searched && activeQuery) {
      runSearch(activeQuery, nextMode, true);
    }
  };

  return (
    <div className="min-h-screen bg-black text-white flex flex-col">
      <Header
        onGoHome={handleGoHome}
        onOpenStats={() => setStatsOpen(true)}
        pagesIndexed={stats?.pages_indexed}
      />

      {!searched ? (
        <main className="flex-1 flex flex-col items-center justify-center px-4 pb-20">
          <div className="w-full max-w-2xl flex flex-col items-center">
            <h1 className="text-4xl sm:text-5xl font-semibold tracking-tight text-white mb-7">
              Neutron
            </h1>

            <SearchBar
              query={query}
              onChange={setQuery}
              onSubmit={(q) => runSearch(q, mode)}
              loading={loading}
              recentQueries={recentQueries}
              onClearRecent={clearRecent}
              inputRef={searchInputRef}
            />

            <div className="mt-4 flex flex-wrap items-center justify-center gap-1.5">
              {SEARCH_MODES.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => handleModeChange(m.id)}
                  className={`px-3 py-1 rounded-md text-xs font-medium transition-colors cursor-pointer ${
                    mode === m.id
                      ? "bg-white text-black"
                      : "text-neutral-400 hover:text-white hover:bg-white/[0.06]"
                  }`}
                >
                  {m.label}
                </button>
              ))}
            </div>

            <div className="mt-7 flex flex-wrap items-center justify-center gap-2">
              {trendingQueries.map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => runSearch(example, mode)}
                  className="px-3 py-1 rounded-full border border-white/10 hover:border-white/30 text-xs text-neutral-400 hover:text-white transition-colors cursor-pointer"
                >
                  {example}
                </button>
              ))}
            </div>
          </div>
        </main>
      ) : (
        <main className="flex-1 w-full">
          <div className="border-b border-white/10 bg-black">
            <div className="max-w-4xl mx-auto px-4 sm:px-6 pt-4 pb-3 space-y-3">
              <SearchBar
                query={query}
                onChange={setQuery}
                onSubmit={(q) => runSearch(q, mode)}
                loading={loading}
                compact
                recentQueries={recentQueries}
                onClearRecent={clearRecent}
                inputRef={searchInputRef}
              />

              <div className="flex items-center gap-1.5 overflow-x-auto pb-0.5">
                {SEARCH_MODES.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => handleModeChange(m.id)}
                    className={`px-2.5 py-1 rounded-md text-xs font-medium whitespace-nowrap transition-colors cursor-pointer ${
                      mode === m.id
                        ? "bg-white text-black"
                        : "text-neutral-400 hover:text-white hover:bg-white/[0.06]"
                    }`}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="max-w-3xl mx-auto px-4 sm:px-6 pt-5 pb-16">
            <div className="flex items-center justify-between text-xs text-neutral-500 mb-3">
              <span>
                {loading && results.length === 0
                  ? slowWake
                    ? "Waking backend services..."
                    : "Searching..."
                  : `${results.length} ${results.length === 1 ? "result" : "results"}${
                      elapsedMs !== null ? ` · ${(elapsedMs / 1000).toFixed(2)}s` : ""
                    }`}
              </span>
              {activeQuery && !loading && (
                <button
                  type="button"
                  onClick={() => runSearch(activeQuery, mode, false, true)}
                  className="inline-flex items-center gap-1.5 text-neutral-500 hover:text-white transition-colors cursor-pointer"
                  title="Re-crawl live sources and refresh summary"
                >
                  <RefreshCw className="w-3 h-3" />
                  <span>Refresh</span>
                </button>
              )}
            </div>

            <CrawlProgressDrawer
              active={crawling}
              statusText={statusText}
              items={crawlItems}
            />

            {errorMsg && (
              <div className="surface-card rounded-lg p-4 mb-5 text-sm text-neutral-300">
                {errorMsg}
              </div>
            )}

            {answer && (
              <AnswerCard
                answer={answer}
                results={results}
                onOpenReader={(target) => setReaderTarget(target)}
              />
            )}

            {results.length > 0 ? (
              <div>
                {results.map((result, idx) => (
                  <ResultCard
                    key={`${result.url}-${idx}`}
                    result={result}
                    index={idx}
                    query={activeQuery}
                    selected={idx === selectedIdx}
                    onOpenReader={(target) => setReaderTarget(target)}
                  />
                ))}
              </div>
            ) : !loading ? (
              <div className="py-16 text-center">
                <p className="text-sm text-neutral-300">
                  No matching pages found for &ldquo;{activeQuery}&rdquo;.
                </p>
                <div className="mt-4 flex items-center justify-center gap-3 text-xs">
                  {mode !== "all" && (
                    <button
                      type="button"
                      onClick={() => handleModeChange("all")}
                      className="px-3 py-1.5 rounded-md border border-white/15 hover:border-white/35 text-white transition-colors cursor-pointer"
                    >
                      Search all sources
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => runSearch(activeQuery, mode)}
                    className="px-3 py-1.5 rounded-md bg-white text-black font-medium hover:bg-neutral-200 transition-colors cursor-pointer"
                  >
                    Retry
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        </main>
      )}

      <footer className="border-t border-white/[0.08] py-4 px-4 sm:px-6 text-center text-xs text-neutral-500">
        <span>Neutron</span>
        <span className="mx-2 text-neutral-700">·</span>
        <a href={apiUrl("/privacy")} className="hover:text-neutral-300 transition-colors">
          Privacy
        </a>
        <span className="mx-2 text-neutral-700">·</span>
        <a
          href={apiUrl("/docs")}
          target="_blank"
          rel="noreferrer"
          className="hover:text-neutral-300 transition-colors"
        >
          API
        </a>
      </footer>

      <DocumentModal
        target={readerTarget}
        onClose={() => setReaderTarget(null)}
      />

      <StatsDrawer
        open={statsOpen}
        onClose={() => setStatsOpen(false)}
        stats={stats}
        onRefresh={fetchStats}
      />
    </div>
  );
}

export default App;

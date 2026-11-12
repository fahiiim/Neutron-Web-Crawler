import React, { useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Cpu,
  Database,
  FileDown,
  GitBranch,
  Globe,
  Layers,
  Lock,
  Server,
  Sparkles,
  Zap,
} from "lucide-react";

interface ArchitectureViewProps {
  onBackToSearch: () => void;
  pagesIndexed?: number;
}

type ArchTab = "cloud" | "hld" | "lld" | "schema";

interface NodeSpec {
  id: string;
  title: string;
  layer: string;
  accent: string;
  logos: { src: string; alt: string }[];
  file: string;
  summary: string;
  bullets: string[];
}

const BASE = import.meta.env.BASE_URL || "/";
const logo = (name: string) => `${BASE}logos/${name}.svg`;

const STACK_LOGOS = [
  { name: "React 18", src: logo("react") },
  { name: "TypeScript", src: logo("typescript") },
  { name: "Vite 6", src: logo("vite") },
  { name: "Tailwind v4", src: logo("tailwindcss") },
  { name: "FastAPI", src: logo("fastapi") },
  { name: "Python 3.12", src: logo("python") },
  { name: "ConnectRPC", src: logo("connectrpc") },
  { name: "Turso LibSQL", src: logo("turso") },
  { name: "SQLite FTS5", src: logo("sqlite") },
  { name: "Render Free", src: logo("render_dark") },
  { name: "GitHub Pages", src: logo("github_light") },
  { name: "Gemini 2.5", src: logo("gemini") },
];

const CLOUD_NODES: NodeSpec[] = [
  {
    id: "edge",
    title: "GitHub Pages · Browser SPA",
    layer: "Edge Presentation",
    accent: "border-blue-500/40 bg-blue-500/[0.04]",
    logos: [
      { src: logo("github_light"), alt: "GitHub Pages" },
      { src: logo("react"), alt: "React" },
      { src: logo("typescript"), alt: "TypeScript" },
    ],
    file: "frontend/src/App.tsx · .github/workflows/deploy_pages.yml",
    summary:
      "Static React 18 + Tailwind v4 client pre-connecting TLS to Render, caching hot queries in sessionStorage (5m TTL), and sanitizing Reader Markdown via marked + DOMPurify.",
    bullets: [
      "Zero external tracking scripts, zero cookies, zero referrer leaks",
      "SSE EventSource streaming with automatic JSON fallback & backend_error recovery",
      "Safe <mark> React highlighting + safeHttpUrl anchor guard",
    ],
  },
  {
    id: "gateway",
    title: "Render · neutron-gateway",
    layer: "Public Edge Coordinator",
    accent: "border-indigo-500/40 bg-indigo-500/[0.04]",
    logos: [
      { src: logo("render_dark"), alt: "Render" },
      { src: logo("fastapi"), alt: "FastAPI" },
      { src: logo("connectrpc"), alt: "ConnectRPC" },
    ],
    file: "services/gateway/app.py · services/common/config.py",
    summary:
      "Public REST, SSE, and GatewayService edge router coordinating SearchService and CrawlerService over pyqwest HTTPTransport + certifi TLS roots.",
    bullets: [
      "Bounded _TTLCache: 256 query slots (300s) + connected stats (30s)",
      "slowapi volatile IP rate limits (30/min search, 15/min stream, 20/min research)",
      "X-Request-Id tracing, 55s cold-start RPC envelope & 180s throttled warm-up",
    ],
  },
  {
    id: "search",
    title: "Render · neutron-search",
    layer: "Index Query & AI Synthesis",
    accent: "border-cyan-500/40 bg-cyan-500/[0.04]",
    logos: [
      { src: logo("fastapi"), alt: "FastAPI" },
      { src: logo("python"), alt: "Python" },
      { src: logo("gemini"), alt: "Gemini 2.5" },
    ],
    file: "services/search/app.py · spaces/crawler/synthesis.py",
    summary:
      "ConnectRPC SearchService executing wide-pool stemmed FTS5 lookups, multi-signal concept re-ranking, Zstd payload hydration, and cited answer generation.",
    bullets: [
      "MetadataInterceptor enforcing constant-time hmac.compare_digest Bearer auth",
      "Fetches 3x FTS candidates in filtered modes so vertical recall stays high",
      "Gemini 2.5 Flash REST (4.5s timeout) with seamless extractive citation fallback",
    ],
  },
  {
    id: "crawler",
    title: "Render · neutron-crawler",
    layer: "Live Discovery & Ingestion",
    accent: "border-emerald-500/40 bg-emerald-500/[0.04]",
    logos: [
      { src: logo("curl"), alt: "curl_cffi" },
      { src: logo("python"), alt: "Python" },
      { src: logo("connectrpc"), alt: "StreamCrawl" },
    ],
    file: "services/crawler/app.py · spaces/crawler/discovery.py",
    summary:
      "Server-streaming CrawlerService running 6 discovery adapters concurrently, Chrome 124 TLS-impersonated fetches, Selectolax parsing, and deduplication.",
    bullets: [
      "Strict 8.5s JIT batch deadline with clean task cancellation on client disconnect",
      "robots.txt (NeutronBot/3.0, 24h TTL) & 24h WAF cooldown domain filtering",
      "1M-slot mmh3 Bloom filter + 12KB bounded Charikar SimHash (Hamming <= 3)",
    ],
  },
  {
    id: "turso",
    title: "Turso LibSQL · FTS5 & Zstd Store",
    layer: "Serverless Persistence",
    accent: "border-amber-500/40 bg-amber-500/[0.04]",
    logos: [
      { src: logo("turso"), alt: "Turso" },
      { src: logo("sqlite"), alt: "SQLite FTS5" },
    ],
    file: "migrations/03_turso_fts5_schema.sql · spaces/crawler/db_turso.py",
    summary:
      "Single-DB serverless LibSQL store unifying relational index catalog, Porter unicode61 FTS5 triggers, Zstd level-3 page Markdown blobs, and frontier queues.",
    bullets: [
      "Signed 64-bit xxHash64 keys serialized as strings past JS 2^53 - 1 safety",
      "BM25 (4.0 title, 1.5 snippet, 0.5 URL) + >= 70% multi-term quorum fallback",
      "Atomic batch writes across domains, search_index, and page_payloads",
    ],
  },
  {
    id: "web",
    title: "6 Open-Web Discovery Adapters",
    layer: "Live Data Acquisition",
    accent: "border-white/20 bg-white/[0.03]",
    logos: [
      { src: logo("duckduckgo"), alt: "DuckDuckGo" },
      { src: logo("wikipedia_light"), alt: "Wikipedia" },
      { src: logo("arxiv"), alt: "arXiv" },
      { src: logo("github_light"), alt: "GitHub" },
      { src: logo("reddit"), alt: "Reddit" },
      { src: logo("hackernews"), alt: "HackerNews" },
    ],
    file: "spaces/crawler/discovery.py · spaces/crawler/parser.py",
    summary:
      "Two-pass domain diversity scheduler querying public APIs & HTML engines concurrently, plus optional Brave Search when configured.",
    bullets: [
      "Pass 1 enforces 1 URL per domain; Pass 2 backfills multi-article hubs cleanly",
      "Extracts __NEXT_DATA__ SSR props, JSON-LD metadata & up to 80 clean links",
      "Zero browser-side third-party requests — all crawling happens server-side",
    ],
  },
];

const SCHEMA_TABLES = [
  {
    name: "search_index",
    role: "Core URL catalog, OPIC authority & SimHash",
    cols: ["PK url_hash (INT64)", "domain_hash", "canonical_url", "title", "snippet", "opic_authority", "simhash", "crawled_at"],
    color: "border-amber-500/35",
  },
  {
    name: "search_fts",
    role: "Porter unicode61 FTS5 virtual table (AI/AD/AU triggers)",
    cols: ["rowid = url_hash", "title (weight 4.0)", "snippet (weight 1.5)", "canonical_url (weight 0.5)"],
    color: "border-cyan-500/35",
  },
  {
    name: "page_payloads",
    role: "Zstandard level-3 compressed full-page Markdown",
    cols: ["PK/FK url_hash -> search_index", "compressed_text (BLOB)", "updated_at (ON DELETE CASCADE)"],
    color: "border-indigo-500/35",
  },
  {
    name: "domains",
    role: "Per-host politeness & exponential backoff state",
    cols: ["PK domain_hash", "hostname (UNIQUE)", "crawl_delay_ms", "next_fetch_at", "total_crawled", "is_blacklisted"],
    color: "border-emerald-500/35",
  },
  {
    name: "frontier_queue",
    role: "Leased background & sitemap discovery queue",
    cols: ["PK url_hash", "FK domain_hash -> domains", "url", "priority_score", "status (0..3)", "lease_expires_at"],
    color: "border-blue-500/35",
  },
  {
    name: "hot_topics",
    role: "Anonymous search frequency counters for trending & suggest",
    cols: ["PK term (<= 40 chars)", "frequency", "last_searched_at (No user/IP fields)"],
    color: "border-white/20",
  },
];

export const ArchitectureView: React.FC<ArchitectureViewProps> = ({
  onBackToSearch,
  pagesIndexed,
}) => {
  const [tab, setTab] = useState<ArchTab>("cloud");
  const [selectedNodeId, setSelectedNodeId] = useState<string>("gateway");
  const selectedNode =
    CLOUD_NODES.find((n) => n.id === selectedNodeId) || CLOUD_NODES[0];

  const tabs: { id: ArchTab; label: string; icon: React.ReactNode }[] = [
    { id: "cloud", label: "Cloud Architecture", icon: <Globe className="w-3.5 h-3.5" /> },
    { id: "hld", label: "High-Level Design", icon: <Layers className="w-3.5 h-3.5" /> },
    { id: "lld", label: "Low-Level Internals", icon: <Cpu className="w-3.5 h-3.5" /> },
    { id: "schema", label: "Schema & Budgets", icon: <Database className="w-3.5 h-3.5" /> },
  ];

  return (
    <main className="flex-1 w-full bg-black text-white">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 pt-6 pb-20 space-y-8">
        {/* Top Action Strip */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <button
            type="button"
            onClick={onBackToSearch}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-white/15 hover:border-white/35 text-xs text-neutral-300 hover:text-white transition-colors cursor-pointer"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>Back to Search</span>
          </button>

          <div className="flex flex-wrap items-center gap-2.5">
            <a
              href={`${BASE}Neutron_Architecture_Whitepaper.pdf`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-white text-black text-xs font-medium hover:bg-neutral-200 transition-colors"
            >
              <FileDown className="w-3.5 h-3.5" />
              <span>LaTeX Whitepaper (PDF)</span>
            </a>
            <a
              href="https://github.com/fahiiim/Neutron-Web-Crawler/blob/main/docs/ARCHITECTURE.md"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-white/15 hover:border-white/35 text-xs text-neutral-300 hover:text-white transition-colors"
            >
              <GitBranch className="w-3.5 h-3.5" />
              <span>Docs Source</span>
            </a>
          </div>
        </div>

        {/* Hero Banner */}
        <section className="relative overflow-hidden rounded-2xl border border-white/15 bg-gradient-to-br from-[#070b14] via-[#0b1220] to-[#0a0a0a] p-6 sm:p-8">
          <div className="max-w-3xl">
            <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full border border-cyan-500/30 bg-cyan-500/10 text-[11px] font-mono-tech text-cyan-300 mb-3">
              <Sparkles className="w-3 h-3" />
              <span>SYSTEM DESIGN · HLD · LLD · CLOUD ARCHITECTURE</span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight text-white">
              Neutron v3.0 Engineering Blueprint
            </h1>
            <p className="mt-2.5 text-sm leading-relaxed text-neutral-300">
              A contract-first distributed search engine, server-streaming JIT web crawler,
              and cited synthesis platform engineered to run on{" "}
              <span className="text-white font-medium">$0/month serverless infrastructure</span>{" "}
              with zero user telemetry, sub-50 ms index lookup, and cold-start resilience.
            </p>
          </div>

          <div className="mt-6 grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="rounded-xl border border-blue-500/30 bg-black/50 p-3.5">
              <div className="text-[11px] font-mono-tech text-blue-400">CLOUD COST</div>
              <div className="mt-1 text-xl font-semibold text-white">$0 / mo</div>
              <div className="mt-0.5 text-[11px] text-neutral-400">Render Free + GH Pages</div>
            </div>
            <div className="rounded-xl border border-indigo-500/30 bg-black/50 p-3.5">
              <div className="text-[11px] font-mono-tech text-indigo-400">MICROSERVICES</div>
              <div className="mt-1 text-xl font-semibold text-white">3 RPC Nodes</div>
              <div className="mt-0.5 text-[11px] text-neutral-400">ConnectRPC / Protobuf</div>
            </div>
            <div className="rounded-xl border border-cyan-500/30 bg-black/50 p-3.5">
              <div className="text-[11px] font-mono-tech text-cyan-400">INDEXED CORPUS</div>
              <div className="mt-1 text-xl font-semibold text-white">
                {typeof pagesIndexed === "number" && pagesIndexed > 0
                  ? pagesIndexed.toLocaleString()
                  : "FTS5 + Zstd"}
              </div>
              <div className="mt-0.5 text-[11px] text-neutral-400">Turso LibSQL + 6 Adapters</div>
            </div>
            <div className="rounded-xl border border-emerald-500/30 bg-black/50 p-3.5">
              <div className="text-[11px] font-mono-tech text-emerald-400">PRIVACY</div>
              <div className="mt-1 text-xl font-semibold text-white">Zero Logs</div>
              <div className="mt-0.5 text-[11px] text-neutral-400">DOMPurify · No Cookies</div>
            </div>
          </div>

          {/* Official Stack Logos Strip */}
          <div className="mt-6 pt-5 border-t border-white/10">
            <div className="text-[11px] font-mono-tech text-neutral-500 uppercase tracking-wider mb-3">
              Verified Production Stack
            </div>
            <div className="grid grid-cols-3 sm:grid-cols-6 gap-2.5">
              {STACK_LOGOS.map((item) => (
                <div
                  key={item.name}
                  className="flex items-center gap-2 rounded-lg border border-white/10 bg-black/50 px-2.5 py-2"
                >
                  <img
                    src={item.src}
                    alt={item.name}
                    className="w-4 h-4 shrink-0 object-contain"
                  />
                  <span className="text-xs text-neutral-300 truncate">{item.name}</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Interactive Tab Selector */}
        <div className="flex flex-wrap items-center gap-2 border-b border-white/10 pb-3">
          {tabs.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
              className={`inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer ${
                tab === item.id
                  ? "bg-white text-black"
                  : "text-neutral-400 hover:text-white hover:bg-white/[0.06]"
              }`}
            >
              {item.icon}
              <span>{item.label}</span>
            </button>
          ))}
        </div>

        {/* TAB 1: CLOUD ARCHITECTURE */}
        {tab === "cloud" && (
          <section className="space-y-6">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <div className="lg:col-span-2 space-y-3">
                <div className="text-xs text-neutral-400">
                  Click any infrastructure node to inspect its contracts, timeouts, and resilience design.
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {CLOUD_NODES.map((node) => {
                    const active = node.id === selectedNode.id;
                    return (
                      <button
                        key={node.id}
                        type="button"
                        onClick={() => setSelectedNodeId(node.id)}
                        className={`text-left rounded-xl border p-4 transition-all cursor-pointer ${
                          active
                            ? `${node.accent} ring-1 ring-white/40`
                            : "border-white/10 bg-[#0a0a0a] hover:border-white/25"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2 mb-2">
                          <span className="text-[10px] font-mono-tech uppercase tracking-wider text-neutral-400">
                            {node.layer}
                          </span>
                          <div className="flex items-center gap-1.5">
                            {node.logos.map((l) => (
                              <img
                                key={l.alt}
                                src={l.src}
                                alt={l.alt}
                                title={l.alt}
                                className="w-4 h-4 object-contain"
                              />
                            ))}
                          </div>
                        </div>
                        <div className="text-sm font-medium text-white">{node.title}</div>
                        <p className="mt-1 text-xs text-neutral-400 line-clamp-2">
                          {node.summary}
                        </p>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Inspector Panel */}
              <aside className="rounded-xl border border-white/15 bg-[#0a0a0a] p-5 flex flex-col justify-between space-y-4">
                <div>
                  <div className="flex items-center gap-2 mb-3">
                    {selectedNode.logos.map((l) => (
                      <img
                        key={l.alt}
                        src={l.src}
                        alt={l.alt}
                        className="w-5 h-5 object-contain"
                      />
                    ))}
                  </div>
                  <div className="text-[11px] font-mono-tech text-cyan-400 uppercase">
                    {selectedNode.layer}
                  </div>
                  <h3 className="mt-1 text-base font-semibold text-white">
                    {selectedNode.title}
                  </h3>
                  <div className="mt-1.5 text-[11px] font-mono-tech text-neutral-500 break-all">
                    {selectedNode.file}
                  </div>
                  <p className="mt-3 text-xs leading-relaxed text-neutral-300">
                    {selectedNode.summary}
                  </p>
                  <ul className="mt-4 space-y-2 border-t border-white/10 pt-3">
                    {selectedNode.bullets.map((b) => (
                      <li key={b} className="text-xs text-neutral-300 flex items-start gap-2">
                        <span className="text-cyan-400 mt-0.5">•</span>
                        <span>{b}</span>
                      </li>
                    ))}
                  </ul>
                </div>

                <div className="rounded-lg border border-white/10 bg-black p-3 text-[11px] text-neutral-400">
                  <div className="font-medium text-white mb-0.5 flex items-center gap-1.5">
                    <Server className="w-3.5 h-3.5 text-indigo-400" />
                    <span>Render Free Cold-Start Handling</span>
                  </div>
                  Requests ping downstream `/health` (180s throttle) while `RPC_TIMEOUT_MS=55000`
                  covers cold container wake-ups safely.
                </div>
              </aside>
            </div>
          </section>
        )}

        {/* TAB 2: HIGH-LEVEL DESIGN */}
        {tab === "hld" && (
          <section className="space-y-5">
            <div className="rounded-xl border border-white/15 bg-[#0a0a0a] p-5 sm:p-6">
              <h2 className="text-base font-semibold text-white mb-1">
                Adaptive Cache-First + JIT Streaming Cascade
              </h2>
              <p className="text-xs text-neutral-400 mb-5">
                Threshold controlled by <code className="text-neutral-200">JIT_CACHE_THRESHOLD = 5</code>{" "}
                and <code className="text-neutral-200">LIVE_JIT_DEADLINE_SECONDS = 8.5s</code>.
              </p>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="rounded-xl border border-blue-500/30 bg-black p-4 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-mono-tech text-blue-400">TIER 1 · ~0 ms</span>
                    <Zap className="w-4 h-4 text-blue-400" />
                  </div>
                  <h3 className="text-sm font-medium text-white">Edge & Session Cache</h3>
                  <p className="text-xs text-neutral-400 leading-relaxed">
                    Browser <code className="text-neutral-300">sessionStorage</code> (5m TTL) and Gateway{" "}
                    <code className="text-neutral-300">_TTLCache</code> (256 entries, 300s TTL) serve
                    repeat searches instantaneously, bypassed cleanly via{" "}
                    <code className="text-neutral-300">?refresh=true</code>.
                  </p>
                </div>

                <div className="rounded-xl border border-cyan-500/30 bg-black p-4 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-mono-tech text-cyan-400">TIER 2 · Warm Index</span>
                    <Database className="w-4 h-4 text-cyan-400" />
                  </div>
                  <h3 className="text-sm font-medium text-white">QueryIndex + Synthesis</h3>
                  <p className="text-xs text-neutral-400 leading-relaxed">
                    <code className="text-neutral-300">SearchService.QueryIndex</code> runs stemmed
                    FTS5 BM25 across a 2x–3x candidate pool, hydrates top-5 Zstd payloads, and
                    generates cited summaries via Gemini 2.5 Flash or extractive fallback.
                  </p>
                </div>

                <div className="rounded-xl border border-emerald-500/30 bg-black p-4 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-mono-tech text-emerald-400">TIER 3 · Live JIT</span>
                    <Globe className="w-4 h-4 text-emerald-400" />
                  </div>
                  <h3 className="text-sm font-medium text-white">StreamCrawl Server-Stream</h3>
                  <p className="text-xs text-neutral-400 leading-relaxed">
                    If hits &lt; 5 or refreshing, <code className="text-neutral-300">CrawlerService.StreamCrawl</code>{" "}
                    fans out across 6 adapters, crawls via <code className="text-neutral-300">curl_cffi</code> Chrome124,
                    streams <code className="text-neutral-300">live_result</code> SSE cards, and re-synthesizes.
                  </p>
                </div>
              </div>

              {/* Event Pipeline Ribbon */}
              <div className="mt-5 pt-4 border-t border-white/10">
                <div className="text-[11px] font-mono-tech text-neutral-500 mb-2.5">
                  SSE STREAM EVENT LIFECYCLE (/search/stream)
                </div>
                <div className="flex flex-wrap items-center gap-2 text-xs font-mono-tech">
                  {[
                    "cached_results",
                    "discovery_start",
                    "discovery_result (x6)",
                    "crawl_start",
                    "crawl_success + live_result",
                    "answer",
                    "done (timings + X-Request-Id)",
                  ].map((ev, i, arr) => (
                    <React.Fragment key={ev}>
                      <span className="px-2.5 py-1 rounded-md border border-white/15 bg-white/[0.04] text-neutral-200">
                        {ev}
                      </span>
                      {i < arr.length - 1 && <ArrowRight className="w-3.5 h-3.5 text-neutral-600" />}
                    </React.Fragment>
                  ))}
                </div>
              </div>
            </div>
          </section>
        )}

        {/* TAB 3: LOW-LEVEL DESIGN */}
        {tab === "lld" && (
          <section className="space-y-5">
            <div className="rounded-xl border border-white/15 bg-[#0a0a0a] p-5 sm:p-6 space-y-4">
              <div>
                <h2 className="text-base font-semibold text-white">
                  Lexical Query Pipeline & Concept Re-Ranking
                </h2>
                <p className="text-xs text-neutral-400 mt-1">
                  Trace how a conversational question transforms inside{" "}
                  <code className="text-neutral-200">spaces/crawler/db_turso.py</code> before hitting SQLite FTS5.
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs font-mono-tech">
                <div className="rounded-lg border border-white/10 bg-black p-3.5">
                  <div className="text-neutral-500 mb-1">1. RAW USER QUERY</div>
                  <div className="text-white">"what is the main purpose of the joining in SQL"</div>
                </div>
                <div className="rounded-lg border border-cyan-500/30 bg-black p-3.5">
                  <div className="text-cyan-400 mb-1">2. NORMALIZED + FILLER STRIPPED</div>
                  <div className="text-neutral-200">["joining", "sql"]</div>
                </div>
                <div className="rounded-lg border border-indigo-500/30 bg-black p-3.5">
                  <div className="text-indigo-400 mb-1">3. FTS5 MORPHOLOGICAL EXPANSION</div>
                  <div className="text-neutral-200 break-all">
                    ("joining" OR "join" OR "joins" OR "joined") AND "sql"
                  </div>
                </div>
                <div className="rounded-lg border border-emerald-500/30 bg-black p-3.5">
                  <div className="text-emerald-400 mb-1">4. CONCEPT RE-RANK WEIGHTS</div>
                  <div className="text-neutral-200">
                    Title +4.0 · URL/Snippet +1.5 · Authority +1.5 · Boilerplate -4.0
                  </div>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="rounded-xl border border-white/15 bg-[#0a0a0a] p-5 space-y-2.5">
                <div className="flex items-center gap-2 text-sm font-semibold text-white">
                  <Cpu className="w-4 h-4 text-emerald-400" />
                  <span>0.1 vCPU Optimization Guarantees</span>
                </div>
                <ul className="space-y-1.5 text-xs text-neutral-300">
                  <li>• <strong>12 KB SimHash Cap:</strong> Bounds Charikar unigram + 2-gram hashing so 2 MB Wikipedia pages hash in ~15 ms instead of ~300+ ms.</li>
                  <li>• <strong>80-Link Frontier Scan Cap:</strong> Avoids canonicalizing 4,000+ navigation links per encyclopedia page.</li>
                  <li>• <strong>1M Bloom Filter:</strong> <code>mmh3</code> + <code>bitarray</code> O(1) duplicate avoidance warmed at boot.</li>
                  <li>• <strong>Zstd Level 3 Payloads:</strong> Compact binary BLOB storage inside Turso LibSQL.</li>
                </ul>
              </div>

              <div className="rounded-xl border border-white/15 bg-[#0a0a0a] p-5 space-y-2.5">
                <div className="flex items-center gap-2 text-sm font-semibold text-white">
                  <Lock className="w-4 h-4 text-rose-400" />
                  <span>Zero-Trust RPC & Browser Security</span>
                </div>
                <ul className="space-y-1.5 text-xs text-neutral-300">
                  <li>• <strong>Streaming Auth Interceptor:</strong> <code>MetadataInterceptor</code> enforces <code>hmac.compare_digest</code> across unary &amp; <code>StreamCrawl</code> RPCs.</li>
                  <li>• <strong>64-Bit Hash Safety:</strong> Signed <code>xxHash64</code> IDs serialize as strings past JS <code>2^53 - 1</code>.</li>
                  <li>• <strong>XSS &amp; Protocol Guards:</strong> Reader Markdown passes through <code>marked</code> + <code>DOMPurify</code>; result snippets render as React text; URLs pass <code>safeHttpUrl</code>.</li>
                </ul>
              </div>
            </div>
          </section>
        )}

        {/* TAB 4: STORAGE SCHEMA & LATENCY BUDGETS */}
        {tab === "schema" && (
          <section className="space-y-6">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3.5">
              {SCHEMA_TABLES.map((tbl) => (
                <div
                  key={tbl.name}
                  className={`rounded-xl border ${tbl.color} bg-[#0a0a0a] p-4 space-y-2`}
                >
                  <div className="font-mono-tech text-sm font-semibold text-white">
                    {tbl.name}
                  </div>
                  <div className="text-xs text-neutral-400">{tbl.role}</div>
                  <ul className="pt-2 border-t border-white/10 space-y-1">
                    {tbl.cols.map((col) => (
                      <li key={col} className="font-mono-tech text-[11px] text-neutral-300">
                        {col}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>

            <div className="rounded-xl border border-white/15 bg-[#0a0a0a] p-5 space-y-3">
              <div className="text-sm font-semibold text-white">
                Configured Free-Tier Execution Budgets (services/common/config.py)
              </div>
              <div className="space-y-2.5 text-xs">
                {[
                  { label: "Session / Gateway _TTLCache", ms: "~1 ms (300s TTL)", pct: "2%" },
                  { label: "Live Fetch Timeout (curl_cffi)", ms: "3.5 s", pct: "41%" },
                  { label: "Gemini 2.5 Flash Synthesis", ms: "4.5 s (extractive fallback)", pct: "53%" },
                  { label: "StreamCrawl JIT Batch Deadline", ms: "8.5 s", pct: "100%" },
                ].map((row) => (
                  <div key={row.label} className="space-y-1">
                    <div className="flex justify-between text-neutral-300">
                      <span>{row.label}</span>
                      <span className="font-mono-tech text-cyan-300">{row.ms}</span>
                    </div>
                    <div className="h-1.5 w-full rounded-full bg-white/10 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-cyan-400 to-indigo-500"
                        style={{ width: row.pct }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}
      </div>
    </main>
  );
};

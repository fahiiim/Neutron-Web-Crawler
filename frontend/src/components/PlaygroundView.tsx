import React, { useState } from "react";
import {
  ArrowLeft,
  Check,
  Code2,
  Copy,
  ExternalLink,
  Layers,
  Play,
  Sparkles,
} from "lucide-react";
import { apiUrl } from "../utils/api";

interface PlaygroundViewProps {
  onBack: () => void;
}

export const PlaygroundView: React.FC<PlaygroundViewProps> = ({ onBack }) => {
  const [query, setQuery] = useState(
    "here is a research paper on LLM agent reasoning",
  );
  const [searchType, setSearchType] = useState<"auto" | "keyword" | "neural">(
    "auto",
  );
  const [category, setCategory] = useState<string>("all");
  const [numResults, setNumResults] = useState<number>(5);
  const [subpages, setSubpages] = useState<number>(2);
  const [subpageTargets, setSubpageTargets] = useState<string>("docs, api");
  const [includeText, setIncludeText] = useState<boolean>(true);
  const [includeHighlights, setIncludeHighlights] = useState<boolean>(true);
  const [livecrawl, setLivecrawl] = useState<"fallback" | "always" | "never">(
    "fallback",
  );
  const [includeDomains, setIncludeDomains] = useState<string>("");
  const [excludeDomains, setExcludeDomains] = useState<string>("");

  const [activeCodeTab, setActiveCodeTab] = useState<
    "python" | "curl" | "typescript"
  >("python");
  const [activeViewTab, setActiveViewTab] = useState<"visual" | "json">(
    "visual",
  );
  const [copiedCode, setCopiedCode] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [responseJson, setResponseJson] = useState<any>(null);
  const [resolvedType, setResolvedType] = useState<string>("");

  const currentOrigin =
    typeof window !== "undefined"
      ? window.location.origin
      : "http://localhost:8000";

  // Build Python code snippet
  const pythonSnippet = `from exa_py import Exa

# Drop-in compatible with Exa API:
exa = Exa(api_key="your_api_key", base_url="${currentOrigin}")

response = exa.search_and_contents(
    "${query.replace(/"/g, '\\"')}",
    type="${searchType}",
    num_results=${numResults},${
      category !== "all" ? `\n    category="${category}",` : ""
    }${
      includeDomains
        ? `\n    include_domains=[${includeDomains
            .split(",")
            .map((d) => `"${d.trim()}"`)
            .join(", ")}],`
        : ""
    }${
      excludeDomains
        ? `\n    exclude_domains=[${excludeDomains
            .split(",")
            .map((d) => `"${d.trim()}"`)
            .join(", ")}],`
        : ""
    }
    text=${includeText ? "True" : "False"},
    highlights=${includeHighlights ? "True" : "False"},
    subpages=${subpages},${
      subpages > 0 && subpageTargets
        ? `\n    subpage_target=[${subpageTargets
            .split(",")
            .map((t) => `"${t.trim()}"`)
            .join(", ")}],`
        : ""
    }
    livecrawl="${livecrawl}"
)

print(f"Resolved search type: {response.resolved_search_type}")
for result in response.results:
    print(f"[{result.score:.2f}] {result.title} -> {result.url}")
    if hasattr(result, "highlights"):
        print("Highlights:", result.highlights)
    if hasattr(result, "subpages"):
        print("Subpages:", [sp.title for sp in result.subpages])
`;

  // Build cURL code snippet
  const curlSnippet = `curl -X POST "${currentOrigin}/search" \\
  -H "Content-Type: application/json" \\
  -d '{
    "query": "${query.replace(/"/g, '\\"')}",
    "type": "${searchType}",
    "numResults": ${numResults},${
      category !== "all" ? `\n    "category": "${category}",` : ""
    }${
      includeDomains
        ? `\n    "includeDomains": [${includeDomains
            .split(",")
            .map((d) => `"${d.trim()}"`)
            .join(", ")}],`
        : ""
    }${
      excludeDomains
        ? `\n    "excludeDomains": [${excludeDomains
            .split(",")
            .map((d) => `"${d.trim()}"`)
            .join(", ")}],`
        : ""
    }
    "contents": {
      "text": ${includeText},
      "highlights": ${includeHighlights},
      "subpages": ${subpages},
      "subpageTarget": [${subpageTargets
        .split(",")
        .map((t) => `"${t.trim()}"`)
        .join(", ")}],
      "livecrawl": "${livecrawl}"
    }
  }'`;

  // Build TypeScript fetch snippet
  const tsSnippet = `const res = await fetch("${currentOrigin}/search", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    query: "${query.replace(/"/g, '\\"')}",
    type: "${searchType}",
    numResults: ${numResults},${
      category !== "all" ? `\n    category: "${category}",` : ""
    }
    contents: {
      text: ${includeText},
      highlights: ${includeHighlights},
      subpages: ${subpages},
      subpageTarget: [${subpageTargets
        .split(",")
        .map((t) => `"${t.trim()}"`)
        .join(", ")}],
      livecrawl: "${livecrawl}"
    }
  })
});
const data = await res.json();
console.log(data);`;

  const getActiveCode = () => {
    switch (activeCodeTab) {
      case "python":
        return pythonSnippet;
      case "curl":
        return curlSnippet;
      case "typescript":
        return tsSnippet;
    }
  };

  const handleCopyCode = async () => {
    try {
      await navigator.clipboard.writeText(getActiveCode());
      setCopiedCode(true);
      setTimeout(() => setCopiedCode(false), 1600);
    } catch {}
  };

  const handleCopyJson = async () => {
    if (!responseJson) return;
    try {
      await navigator.clipboard.writeText(
        JSON.stringify(responseJson, null, 2),
      );
      setCopiedJson(true);
      setTimeout(() => setCopiedJson(false), 1600);
    } catch {}
  };

  const executeSearch = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setErrorMsg(null);
    try {
      const inc = includeDomains
        .split(",")
        .map((d) => d.trim())
        .filter(Boolean);
      const exc = excludeDomains
        .split(",")
        .map((d) => d.trim())
        .filter(Boolean);
      const targets = subpageTargets
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);

      const requestBody: any = {
        query: query.trim(),
        type: searchType,
        numResults,
        livecrawl,
        contents: {
          text: includeText,
          highlights: includeHighlights,
          subpages,
          subpageTarget: targets,
          livecrawl,
        },
      };
      if (category !== "all") requestBody.category = category;
      if (inc.length) requestBody.includeDomains = inc;
      if (exc.length) requestBody.excludeDomains = exc;

      const res = await fetch(apiUrl("/search"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data?.detail || `API error ${res.status}`);
      }
      setResponseJson(data);
      setResolvedType(data?.resolvedSearchType || "keyword");
    } catch (err: any) {
      setErrorMsg(err?.message || "Failed to execute playground search");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="w-full max-w-7xl mx-auto px-4 sm:px-6 py-6 pb-20">
      {/* Top Bar */}
      <div className="flex items-center justify-between pb-6 border-b border-white/[0.08] mb-8">
        <div className="flex items-center gap-4">
          <button
            type="button"
            onClick={onBack}
            className="inline-flex items-center gap-2 text-sm text-neutral-400 hover:text-white transition-colors cursor-pointer"
          >
            <ArrowLeft className="w-4 h-4" />
            <span>Search</span>
          </button>
          <div className="h-4 w-px bg-white/10" />
          <h1 className="text-lg font-medium text-white flex items-center gap-2">
            <Code2 className="w-5 h-5 text-neutral-300" />
            <span>Exa API Playground</span>
            <span className="text-[11px] font-mono-tech px-2 py-0.5 rounded bg-white/[0.08] text-neutral-300">
              v3.0 Drop-In
            </span>
          </h1>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={executeSearch}
            disabled={loading}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-white text-black hover:bg-neutral-200 font-medium text-sm transition-colors cursor-pointer disabled:opacity-50"
          >
            {loading ? (
              <span className="w-4 h-4 border-2 border-black border-t-transparent rounded-full animate-spin" />
            ) : (
              <Play className="w-4 h-4 fill-black" />
            )}
            <span>Execute Request</span>
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* Left Column: Parameters Form */}
        <section className="lg:col-span-5 space-y-6">
          <div className="rounded-xl border border-white/[0.08] bg-black/40 p-5 space-y-5">
            <h2 className="text-sm font-semibold text-neutral-200 uppercase tracking-wider font-mono-tech flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-neutral-400" />
              <span>Query &amp; Mode Routing</span>
            </h2>

            {/* Query */}
            <div>
              <label className="block text-xs font-mono-tech text-neutral-400 mb-1.5">
                QUERY STRING
              </label>
              <textarea
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                rows={2}
                className="w-full bg-neutral-900 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-neutral-500 focus:outline-none focus:border-white/30 resize-none"
                placeholder="Enter natural language query or exact keyword..."
              />
            </div>

            {/* Type & Category */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-mono-tech text-neutral-400 mb-1.5">
                  TYPE (ROUTING)
                </label>
                <select
                  value={searchType}
                  onChange={(e: any) => setSearchType(e.target.value)}
                  className="w-full bg-neutral-900 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-white/30"
                >
                  <option value="auto">auto (Heuristic Router)</option>
                  <option value="neural">neural (Semantic/Hybrid)</option>
                  <option value="keyword">keyword (Lexical FTS5)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-mono-tech text-neutral-400 mb-1.5">
                  CATEGORY FILTER
                </label>
                <select
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  className="w-full bg-neutral-900 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-white/30"
                >
                  <option value="all">all (No Filter)</option>
                  <option value="research paper">research paper (arXiv)</option>
                  <option value="github">github (Repositories)</option>
                  <option value="company">company (Corporate)</option>
                  <option value="news">news (Press / Media)</option>
                  <option value="blog">blog (Articles / Posts)</option>
                </select>
              </div>
            </div>

            {/* Sliders */}
            <div className="grid grid-cols-2 gap-4 pt-1">
              <div>
                <div className="flex justify-between text-xs font-mono-tech text-neutral-400 mb-1">
                  <span>NUM RESULTS</span>
                  <span className="text-white font-medium">{numResults}</span>
                </div>
                <input
                  type="range"
                  min="1"
                  max="20"
                  value={numResults}
                  onChange={(e) => setNumResults(Number(e.target.value))}
                  className="w-full accent-white"
                />
              </div>

              <div>
                <div className="flex justify-between text-xs font-mono-tech text-neutral-400 mb-1">
                  <span>SUBPAGES / ENTITY</span>
                  <span className="text-white font-medium">{subpages}</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="5"
                  value={subpages}
                  onChange={(e) => setSubpages(Number(e.target.value))}
                  className="w-full accent-white"
                />
              </div>
            </div>

            {/* Subpage Target Keywords */}
            {subpages > 0 && (
              <div>
                <label className="block text-xs font-mono-tech text-neutral-400 mb-1.5">
                  SUBPAGE TARGET KEYWORDS
                </label>
                <input
                  type="text"
                  value={subpageTargets}
                  onChange={(e) => setSubpageTargets(e.target.value)}
                  placeholder="docs, pricing, api, guides"
                  className="w-full bg-neutral-900 border border-white/10 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-white/30"
                />
              </div>
            )}
          </div>

          {/* Contents & Livecrawl options */}
          <div className="rounded-xl border border-white/[0.08] bg-black/40 p-5 space-y-4">
            <h2 className="text-sm font-semibold text-neutral-200 uppercase tracking-wider font-mono-tech flex items-center gap-2">
              <Layers className="w-4 h-4 text-neutral-400" />
              <span>Hydration &amp; Livecrawl</span>
            </h2>

            <div className="grid grid-cols-2 gap-3">
              <label className="flex items-center gap-2.5 text-sm text-neutral-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={includeText}
                  onChange={(e) => setIncludeText(e.target.checked)}
                  className="rounded border-white/20 bg-neutral-900 text-white accent-white"
                />
                <span>Include Clean Markdown</span>
              </label>

              <label className="flex items-center gap-2.5 text-sm text-neutral-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={includeHighlights}
                  onChange={(e) => setIncludeHighlights(e.target.checked)}
                  className="rounded border-white/20 bg-neutral-900 text-white accent-white"
                />
                <span>Extract Highlights</span>
              </label>
            </div>

            <div>
              <label className="block text-xs font-mono-tech text-neutral-400 mb-1.5">
                LIVECRAWL STRATEGY
              </label>
              <div className="grid grid-cols-3 gap-2">
                {(["fallback", "always", "never"] as const).map((strat) => (
                  <button
                    key={strat}
                    type="button"
                    onClick={() => setLivecrawl(strat)}
                    className={`py-1.5 px-3 rounded-lg text-xs font-mono-tech capitalize border transition-colors cursor-pointer ${
                      livecrawl === strat
                        ? "bg-white text-black border-white font-medium"
                        : "bg-neutral-900/60 text-neutral-400 border-white/10 hover:border-white/25"
                    }`}
                  >
                    {strat}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 pt-1">
              <div>
                <label className="block text-xs font-mono-tech text-neutral-400 mb-1">
                  INCLUDE DOMAINS
                </label>
                <input
                  type="text"
                  value={includeDomains}
                  onChange={(e) => setIncludeDomains(e.target.value)}
                  placeholder="arxiv.org, github.com"
                  className="w-full bg-neutral-900 border border-white/10 rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-white/30"
                />
              </div>

              <div>
                <label className="block text-xs font-mono-tech text-neutral-400 mb-1">
                  EXCLUDE DOMAINS
                </label>
                <input
                  type="text"
                  value={excludeDomains}
                  onChange={(e) => setExcludeDomains(e.target.value)}
                  placeholder="pinterest.com"
                  className="w-full bg-neutral-900 border border-white/10 rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-white/30"
                />
              </div>
            </div>
          </div>
        </section>

        {/* Right Column: Code Snippet & Live Response Inspector */}
        <section className="lg:col-span-7 space-y-6">
          {/* Code Generator Card */}
          <div className="rounded-xl border border-white/[0.08] bg-black/60 overflow-hidden">
            <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/[0.08] bg-neutral-950">
              <div className="flex items-center gap-2">
                {(["python", "curl", "typescript"] as const).map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    onClick={() => setActiveCodeTab(tab)}
                    className={`px-3 py-1 rounded text-xs font-mono-tech uppercase transition-colors cursor-pointer ${
                      activeCodeTab === tab
                        ? "bg-white/10 text-white font-medium"
                        : "text-neutral-400 hover:text-neutral-200"
                    }`}
                  >
                    {tab === "python"
                      ? "Python (exa-py)"
                      : tab === "curl"
                        ? "cURL"
                        : "TypeScript"}
                  </button>
                ))}
              </div>

              <button
                type="button"
                onClick={handleCopyCode}
                className="inline-flex items-center gap-1.5 text-xs font-mono-tech text-neutral-400 hover:text-white transition-colors cursor-pointer"
              >
                {copiedCode ? (
                  <>
                    <Check className="w-3.5 h-3.5 text-white" />
                    <span>COPIED</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3.5 h-3.5" />
                    <span>COPY</span>
                  </>
                )}
              </button>
            </div>

            <pre className="p-4 text-xs font-mono-tech text-neutral-300 overflow-x-auto max-h-60 leading-relaxed bg-[#0d0d0d]">
              {getActiveCode()}
            </pre>
          </div>

          {/* Response Inspector Card */}
          <div className="rounded-xl border border-white/[0.08] bg-black/60 overflow-hidden">
            <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/[0.08] bg-neutral-950">
              <div className="flex items-center gap-3">
                <span className="text-xs font-mono-tech text-neutral-400 uppercase tracking-wider">
                  Live Response
                </span>
                {resolvedType && (
                  <span className="text-[11px] font-mono-tech px-2 py-0.5 rounded bg-white/10 text-neutral-200">
                    type: {resolvedType}
                  </span>
                )}
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setActiveViewTab("visual")}
                  className={`px-2.5 py-1 rounded text-xs font-mono-tech transition-colors cursor-pointer ${
                    activeViewTab === "visual"
                      ? "bg-white/10 text-white font-medium"
                      : "text-neutral-400 hover:text-neutral-200"
                  }`}
                >
                  Visual
                </button>
                <button
                  type="button"
                  onClick={() => setActiveViewTab("json")}
                  className={`px-2.5 py-1 rounded text-xs font-mono-tech transition-colors cursor-pointer ${
                    activeViewTab === "json"
                      ? "bg-white/10 text-white font-medium"
                      : "text-neutral-400 hover:text-neutral-200"
                  }`}
                >
                  JSON
                </button>
                {responseJson && (
                  <button
                    type="button"
                    onClick={handleCopyJson}
                    className="ml-2 inline-flex items-center gap-1 text-xs font-mono-tech text-neutral-400 hover:text-white transition-colors cursor-pointer"
                  >
                    {copiedJson ? (
                      <Check className="w-3.5 h-3.5 text-white" />
                    ) : (
                      <Copy className="w-3.5 h-3.5" />
                    )}
                  </button>
                )}
              </div>
            </div>

            <div className="p-4 min-h-[320px] max-h-[540px] overflow-y-auto">
              {loading ? (
                <div className="h-64 flex flex-col items-center justify-center gap-3 text-neutral-400">
                  <div className="w-6 h-6 border-2 border-white/20 border-t-white rounded-full animate-spin" />
                  <span className="text-xs font-mono-tech">
                    Executing Exa search pipeline...
                  </span>
                </div>
              ) : errorMsg ? (
                <div className="p-4 rounded-lg bg-red-950/40 border border-red-500/20 text-xs text-red-300 font-mono-tech">
                  {errorMsg}
                </div>
              ) : !responseJson ? (
                <div className="h-64 flex flex-col items-center justify-center gap-2 text-neutral-500 text-center px-4">
                  <Play className="w-6 h-6 text-neutral-600 mb-1" />
                  <p className="text-sm text-neutral-400">
                    Playground ready. Click "Execute Request" to run.
                  </p>
                  <p className="text-xs text-neutral-600">
                    Sends official Exa-shaped POST payload with subpage
                    traversal and highlight extraction.
                  </p>
                </div>
              ) : activeViewTab === "json" ? (
                <pre className="text-xs font-mono-tech text-neutral-300 overflow-x-auto leading-relaxed">
                  {JSON.stringify(responseJson, null, 2)}
                </pre>
              ) : (
                <div className="space-y-4">
                  {responseJson.answer && (
                    <div className="p-3.5 rounded-lg bg-white/[0.04] border border-white/10 mb-4">
                      <div className="text-[11px] font-mono-tech text-neutral-400 uppercase tracking-wider mb-1">
                        Synthesized Answer
                      </div>
                      <p className="text-sm text-neutral-200 leading-relaxed">
                        {responseJson.answer}
                      </p>
                    </div>
                  )}

                  {Array.isArray(responseJson.results) &&
                  responseJson.results.length > 0 ? (
                    responseJson.results.map((res: any, idx: number) => (
                      <div
                        key={idx}
                        className="p-3.5 rounded-lg border border-white/[0.06] bg-neutral-900/40 space-y-2"
                      >
                        <div className="flex items-center justify-between text-xs text-neutral-500">
                          <span className="font-mono-tech text-[11px] text-neutral-400 truncate max-w-[80%]">
                            {res.url}
                          </span>
                          {typeof res.score === "number" && (
                            <span className="font-mono-tech text-[11px] text-neutral-400">
                              score: {res.score.toFixed(3)}
                            </span>
                          )}
                        </div>

                        <h3 className="text-sm font-medium text-white hover:underline">
                          <a
                            href={res.url}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1.5"
                          >
                            <span>{res.title || res.url}</span>
                            <ExternalLink className="w-3 h-3 text-neutral-400" />
                          </a>
                        </h3>

                        {res.highlights && res.highlights.length > 0 && (
                          <div className="space-y-1 pt-1">
                            {res.highlights.map((hl: string, hIdx: number) => (
                              <div
                                key={hIdx}
                                className="text-xs text-neutral-300 bg-white/[0.03] border-l-2 border-neutral-500 pl-2.5 py-1 italic rounded-r"
                              >
                                "{hl}"
                              </div>
                            ))}
                          </div>
                        )}

                        {res.subpages && res.subpages.length > 0 && (
                          <div className="pt-2 flex flex-wrap items-center gap-1.5">
                            <span className="text-[10px] font-mono-tech text-neutral-500 uppercase tracking-wider mr-1">
                              Subpages ({res.subpages.length}):
                            </span>
                            {res.subpages.map((sp: any, spIdx: number) => (
                              <a
                                key={spIdx}
                                href={sp.url}
                                target="_blank"
                                rel="noreferrer"
                                className="inline-flex items-center gap-1 text-[11px] font-mono-tech text-neutral-300 bg-white/[0.04] hover:bg-white/[0.08] hover:text-white px-2 py-0.5 rounded border border-white/[0.06] transition-colors"
                              >
                                <span className="truncate max-w-[180px]">
                                  {sp.title || sp.url.split("/").pop()}
                                </span>
                                <ExternalLink className="w-2.5 h-2.5 text-neutral-500" />
                              </a>
                            ))}
                          </div>
                        )}
                      </div>
                    ))
                  ) : (
                    <div className="text-xs font-mono-tech text-neutral-500 text-center py-8">
                      No results returned for this query.
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </section>
      </div>
    </main>
  );
};

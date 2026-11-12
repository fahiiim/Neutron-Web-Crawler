import React, { useEffect, useRef, useState } from "react";
import { Check, Copy, ExternalLink, Loader2, X } from "lucide-react";
import { apiUrl } from "../utils/api";

export interface ReaderTarget {
  url: string;
  urlHash?: string | number;
  title?: string;
}

interface DocumentData {
  url_hash?: string;
  url?: string;
  title?: string;
  crawled_at?: string;
  full_markdown?: string;
  source?: string;
}

interface DocumentModalProps {
  target: ReaderTarget | null;
  onClose: () => void;
}

function cleanReaderMarkdown(md: string): string {
  return md
    .replace(/\s*\[(?:\d+|citation needed|edit|update)\]/gi, "")
    .replace(/\[([^\]]+)\]\(#cite_note[^)]+\)/g, "")
    .trim();
}

function renderMarkdown(markdown: string): React.ReactNode {
  const lines = cleanReaderMarkdown(markdown).split(/\r?\n/);
  const nodes: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.trim().startsWith("```")) {
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++;
      nodes.push(
        <pre key={`pre-${i}`}>
          <code>{codeLines.join("\n")}</code>
        </pre>,
      );
      continue;
    }

    if (line.startsWith("### ")) {
      nodes.push(<h3 key={`h3-${i}`}>{line.slice(4)}</h3>);
      i++;
      continue;
    }
    if (line.startsWith("## ")) {
      nodes.push(<h2 key={`h2-${i}`}>{line.slice(3)}</h2>);
      i++;
      continue;
    }
    if (line.startsWith("# ")) {
      nodes.push(<h1 key={`h1-${i}`}>{line.slice(2)}</h1>);
      i++;
      continue;
    }

    if (line.trim().startsWith("> ")) {
      nodes.push(
        <blockquote key={`bq-${i}`}>{line.trim().slice(2)}</blockquote>,
      );
      i++;
      continue;
    }

    if (/^[-*•]\s+/.test(line.trim())) {
      const items: string[] = [];
      while (i < lines.length && /^[-*•]\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-*•]\s+/, ""));
        i++;
      }
      nodes.push(
        <ul key={`ul-${i}`}>
          {items.map((it, idx) => (
            <li key={idx}>{it}</li>
          ))}
        </ul>,
      );
      continue;
    }

    if (!line.trim()) {
      i++;
      continue;
    }

    const paraLines: string[] = [line.trim()];
    i++;
    while (
      i < lines.length &&
      lines[i].trim() &&
      !lines[i].startsWith("#") &&
      !lines[i].trim().startsWith("```") &&
      !lines[i].trim().startsWith("> ") &&
      !/^[-*•]\s+/.test(lines[i].trim())
    ) {
      paraLines.push(lines[i].trim());
      i++;
    }
    nodes.push(<p key={`p-${i}`}>{paraLines.join(" ")}</p>);
  }

  return nodes;
}

export const DocumentModal: React.FC<DocumentModalProps> = ({
  target,
  onClose,
}) => {
  const [doc, setDoc] = useState<DocumentData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [progress, setProgress] = useState(0);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!target) {
      setDoc(null);
      setError(null);
      return;
    }

    if (target.urlHash === undefined || target.urlHash === null || target.urlHash === "") {
      setDoc(null);
      setLoading(false);
      setError("Full cached snapshot unavailable for this source.");
      return;
    }

    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setProgress(0);

    fetch(apiUrl(`/doc/${encodeURIComponent(String(target.urlHash))}`), {
      signal: controller.signal,
    })
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(`Unable to load document (${res.status})`);
        }
        return res.json();
      })
      .then((data) => {
        setDoc(data);
        setLoading(false);
      })
      .catch((err) => {
        if (err?.name === "AbortError") return;
        setError(err?.message || "Failed to load page content");
        setLoading(false);
      });

    return () => controller.abort();
  }, [target]);

  useEffect(() => {
    if (!target) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [target, onClose]);

  if (!target) return null;

  const markdownContent = doc?.full_markdown || "";
  const resolvedUrl = doc?.url || target.url;

  let hostLabel = resolvedUrl;
  try {
    hostLabel = new URL(resolvedUrl).hostname.replace(/^www\./, "");
  } catch {
    hostLabel = resolvedUrl;
  }

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const max = el.scrollHeight - el.clientHeight;
    setProgress(max > 0 ? Math.min(100, Math.round((el.scrollTop / max) * 100)) : 0);
  };

  const handleCopyMarkdown = async () => {
    if (!markdownContent) return;
    try {
      await navigator.clipboard.writeText(markdownContent);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      // Ignore clipboard failures
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Reader view"
      className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-2 sm:p-6"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-3xl max-h-[90vh] bg-[#0a0a0a] border border-white/15 rounded-xl flex flex-col overflow-hidden shadow-2xl">
        <div className="h-[2px] w-full bg-white/10">
          <div
            className="h-full bg-white transition-all duration-150"
            style={{ width: `${progress}%` }}
          />
        </div>

        <div className="px-5 py-3.5 border-b border-white/10 flex items-center justify-between gap-4">
          <div className="min-w-0">
            <h2 className="text-sm font-medium text-white truncate">
              {doc?.title || target.title || resolvedUrl}
            </h2>
            <p className="text-[11px] font-mono-tech text-neutral-500 truncate mt-0.5">
              {hostLabel}
            </p>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={handleCopyMarkdown}
              disabled={!markdownContent}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border border-white/10 hover:border-white/30 text-xs text-neutral-300 hover:text-white disabled:opacity-40 transition-colors cursor-pointer"
            >
              {copied ? (
                <>
                  <Check className="w-3.5 h-3.5" />
                  <span>Copied</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5" />
                  <span className="hidden sm:inline">Copy text</span>
                </>
              )}
            </button>

            <a
              href={resolvedUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md border border-white/10 hover:border-white/30 text-xs text-neutral-300 hover:text-white transition-colors"
            >
              <span className="hidden sm:inline">Source</span>
              <ExternalLink className="w-3.5 h-3.5" />
            </a>

            <button
              type="button"
              onClick={onClose}
              aria-label="Close reader"
              className="p-1.5 rounded-md text-neutral-400 hover:text-white hover:bg-white/10 transition-colors cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="flex-1 overflow-y-auto px-5 sm:px-8 py-6"
        >
          {loading ? (
            <div className="flex items-center gap-2.5 text-sm text-neutral-400 py-12 justify-center">
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>Loading document...</span>
            </div>
          ) : error ? (
            <div className="py-10 text-center text-sm text-neutral-400">
              <p>{error}</p>
              <a
                href={resolvedUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 mt-3 text-white underline underline-offset-4"
              >
                Open source page
                <ExternalLink className="w-3.5 h-3.5" />
              </a>
            </div>
          ) : (
            <div className="markdown-prose">{renderMarkdown(markdownContent)}</div>
          )}
        </div>
      </div>
    </div>
  );
};

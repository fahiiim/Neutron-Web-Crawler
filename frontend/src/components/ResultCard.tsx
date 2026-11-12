import React, { useState } from "react";
import { BookOpen, Check, Copy, ExternalLink } from "lucide-react";
import type { SearchResult } from "../types";
import type { ReaderTarget } from "./DocumentModal";

interface ResultCardProps {
  result: SearchResult;
  index: number;
  selected?: boolean;
  onOpenReader: (target: ReaderTarget) => void;
}

function sanitizeSnippetHtml(raw: string): string {
  return raw
    .replace(/\s*\[(?:\d+|citation needed|edit|update)\]/gi, "")
    .replace(/\(\s*\/[^/\n]{2,55}\/(?:\s*(?:ⓘ|listen))?\s*[;,]?\s*/gi, "(")
    .replace(/\(\s*[;,:\s]+/g, "(")
    .replace(/\(\s*\)/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function formatRelativeAge(crawledAt?: string | null): string | null {
  if (!crawledAt) return null;
  const isoLike = crawledAt.includes("T") ? crawledAt : `${crawledAt.replace(" ", "T")}Z`;
  const ts = Date.parse(isoLike);
  if (Number.isNaN(ts)) return null;
  const diffSec = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (diffSec < 60) return "just now";
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  const days = Math.floor(diffSec / 86400);
  if (days < 365) return `${days}d ago`;
  return `${Math.floor(days / 365)}y ago`;
}

export const ResultCard: React.FC<ResultCardProps> = ({
  result,
  index,
  selected = false,
  onOpenReader,
}) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(result.url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      // Clipboard may be blocked on insecure origins
    }
  };

  let displayUrl = result.url;
  try {
    const parsed = new URL(result.url);
    const path = parsed.pathname === "/" ? "" : parsed.pathname;
    displayUrl = `${parsed.hostname.replace(/^www\./, "")}${path}`;
  } catch {
    displayUrl = result.url;
  }

  const safeSnippet = sanitizeSnippetHtml(result.snippet || "");
  const crawledAge = formatRelativeAge(result.crawled_at);

  return (
    <article
      className={`py-5 border-b border-white/[0.08] last:border-b-0 transition-colors ${
        selected ? "bg-white/[0.03] -mx-3 px-3 rounded-lg" : ""
      }`}
    >
      <div className="flex items-center gap-2 text-xs text-neutral-500 mb-1">
        <span className="font-mono-tech text-[11px] text-neutral-600">
          {index + 1}.
        </span>
        <span className="truncate font-mono-tech text-[11px] text-neutral-400">
          {displayUrl}
        </span>
        {crawledAge && (
          <span className="shrink-0 font-mono-tech text-[11px] text-neutral-600">
            · {crawledAge}
          </span>
        )}
      </div>

      <h3 className="text-[17px] font-medium leading-snug">
        <a
          href={result.url}
          target="_blank"
          rel="noreferrer"
          className="text-white hover:underline underline-offset-4 decoration-white/40"
        >
          {result.title || result.url}
        </a>
      </h3>

      {safeSnippet && (
        <p
          className="mt-1.5 text-sm leading-relaxed text-neutral-400"
          dangerouslySetInnerHTML={{ __html: safeSnippet }}
        />
      )}

      <div className="mt-2.5 flex items-center gap-4 text-xs text-neutral-500">
        <button
          type="button"
          onClick={() =>
            onOpenReader({
              url: result.url,
              urlHash: result.url_hash,
              title: result.title,
            })
          }
          className="inline-flex items-center gap-1.5 hover:text-white transition-colors cursor-pointer"
        >
          <BookOpen className="w-3.5 h-3.5" />
          <span>Reader</span>
        </button>

        <button
          type="button"
          onClick={handleCopy}
          className="inline-flex items-center gap-1.5 hover:text-white transition-colors cursor-pointer"
        >
          {copied ? (
            <>
              <Check className="w-3.5 h-3.5 text-white" />
              <span className="text-white">Copied</span>
            </>
          ) : (
            <>
              <Copy className="w-3.5 h-3.5" />
              <span>Copy link</span>
            </>
          )}
        </button>

        <a
          href={result.url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 hover:text-white transition-colors"
        >
          <span>Open</span>
          <ExternalLink className="w-3 h-3" />
        </a>
      </div>
    </article>
  );
};

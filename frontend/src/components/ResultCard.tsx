import React, { useState } from "react";
import { BookOpen, Check, Copy, ExternalLink } from "lucide-react";
import type { SearchResult } from "../types";
import type { ReaderTarget } from "./DocumentModal";
import {
  escapeRegex,
  extractHighlightTerms,
  formatRelativeTime,
  safeHttpUrl,
} from "../utils/format";

interface ResultCardProps {
  result: SearchResult;
  index: number;
  query?: string;
  selected?: boolean;
  onOpenReader: (target: ReaderTarget) => void;
}

function cleanSnippetText(raw: string): string {
  return raw
    .replace(/\s*\[(?:\d+|citation needed|edit|update)\]/gi, "")
    .replace(/\(\s*\/[^/\n]{2,55}\/(?:\s*(?:ⓘ|listen))?\s*[;,]?\s*/gi, "(")
    .replace(/\(\s*[;,:\s]+/g, "(")
    .replace(/\(\s*\)/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function renderHighlightedSnippet(text: string, query: string): React.ReactNode {
  const terms = extractHighlightTerms(query);
  if (terms.length === 0) {
    return text;
  }
  const pattern = new RegExp(`\\b(${terms.map(escapeRegex).join("|")})\\w*`, "gi");
  const parts = text.split(pattern);
  if (parts.length === 1) {
    return text;
  }
  return parts.map((part, i) =>
    i % 2 === 1 ? <mark key={i}>{part}</mark> : <React.Fragment key={i}>{part}</React.Fragment>,
  );
}

export const ResultCard: React.FC<ResultCardProps> = ({
  result,
  index,
  query = "",
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

  const safeHref = safeHttpUrl(result.url);
  const safeSnippet = cleanSnippetText(result.snippet || "");
  const crawledAge = result.crawled_at ? formatRelativeTime(result.crawled_at) : null;

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
          href={safeHref}
          target="_blank"
          rel="noreferrer"
          className="text-white hover:underline underline-offset-4 decoration-white/40"
        >
          {result.title || result.url}
        </a>
      </h3>

      {safeSnippet && (
        <p className="mt-1.5 text-sm leading-relaxed text-neutral-400">
          {renderHighlightedSnippet(safeSnippet, query)}
        </p>
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
          href={safeHref}
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

import { ArrowUpRight, BookOpen, Check, Copy, Globe } from 'lucide-react';
import { Fragment, useState } from 'react';
import { SearchResult } from '../types';
import {
  escapeRegex,
  extractDomainAndPath,
  extractHighlightTerms,
  formatRelativeTime,
  safeHttpUrl,
} from '../utils/format';

interface ResultCardProps {
  item: SearchResult;
  query: string;
  focused: boolean;
  onOpenReader: () => void;
}

function HighlightedSnippet({ text, query }: { text: string; query: string }) {
  const terms = extractHighlightTerms(query);
  if (!terms.length || !text) {
    return <>{text}</>;
  }
  const regex = new RegExp(`(${terms.map(escapeRegex).join('|')})`, 'gi');
  const termSet = new Set(terms);
  const parts = text.split(regex);

  return (
    <>
      {parts.map((part, idx) =>
        part && termSet.has(part.toLowerCase()) ? (
          <mark
            key={idx}
            className="bg-emerald-500/15 text-glow-green font-semibold px-1 rounded"
          >
            {part}
          </mark>
        ) : (
          <Fragment key={idx}>{part}</Fragment>
        )
      )}
    </>
  );
}

export function ResultCard({
  item,
  query,
  focused,
  onOpenReader,
}: ResultCardProps) {
  const [copied, setCopied] = useState(false);
  const [faviconBroken, setFaviconBroken] = useState(false);

  const safeUrl = safeHttpUrl(item.url);
  const { domain, path } = extractDomainAndPath(safeUrl);
  const freshness = item.isLive ? 'Just now' : formatRelativeTime(item.crawled_at);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(safeUrl);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // ignore
    }
  };

  return (
    <li
      role="listitem"
      className={`surface-interactive rounded-xl p-4 sm:p-5 ${
        focused ? 'border-emerald-400/70 ring-1 ring-emerald-400/25' : ''
      }`}
    >
      {/* Top Meta Row */}
      <div className="flex items-center justify-between gap-3 mb-2">
        <div className="flex items-center space-x-2 min-w-0 text-xs font-mono text-white">
          {!faviconBroken ? (
            <img
              src={`https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=32`}
              alt=""
              width={16}
              height={16}
              onError={() => setFaviconBroken(true)}
              className="w-4 h-4 rounded-sm shrink-0 bg-white/10"
            />
          ) : (
            <Globe className="w-3.5 h-3.5 text-white shrink-0" />
          )}
          <span className="font-medium text-white truncate">{domain}</span>
          {path && <span className="text-white/80 truncate hidden sm:inline">{path}</span>}
        </div>

        <div className="flex items-center space-x-2 shrink-0 text-[11px] font-mono">
          <span className="text-white/90">{freshness}</span>
          <span
            className={`px-2 py-0.5 rounded-md border ${
              item.isLive
                ? 'bg-emerald-500/10 text-glow-green border-emerald-400/40'
                : 'bg-white/[0.04] text-white border-white/20'
            }`}
          >
            {item.isLive ? 'Live' : 'Indexed'}
          </span>
        </div>
      </div>

      {/* Title */}
      <h2 className="font-varsity text-[15px] sm:text-[16px] text-white mb-2 leading-snug">
        <a
          href={safeUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="hover:text-[#4ade80] transition-colors"
        >
          {item.title || safeUrl}
        </a>
      </h2>

      {/* Classic Serif Snippet */}
      <p className="font-classic text-[14px] text-white/95 leading-relaxed line-clamp-3 mb-3.5">
        <HighlightedSnippet
          text={item.snippet || 'No preview available for this document.'}
          query={query}
        />
      </p>

      {/* Actions */}
      <div className="flex items-center space-x-5 pt-2.5 border-t border-white/[0.1] text-xs font-classic text-white">
        <button
          type="button"
          onClick={onOpenReader}
          className="inline-flex items-center space-x-1.5 text-glow-green hover:opacity-85 font-semibold transition-opacity"
        >
          <BookOpen className="w-3.5 h-3.5" />
          <span>Reader</span>
        </button>

        <button
          type="button"
          onClick={handleCopy}
          className="inline-flex items-center space-x-1.5 text-white hover:text-[#4ade80] transition-colors"
        >
          {copied ? (
            <>
              <Check className="w-3.5 h-3.5 text-emerald-400" />
              <span className="text-glow-green">Copied</span>
            </>
          ) : (
            <>
              <Copy className="w-3.5 h-3.5" />
              <span>Copy URL</span>
            </>
          )}
        </button>

        <a
          href={safeUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center space-x-1 text-white hover:text-[#4ade80] transition-colors ml-auto"
        >
          <span>Open</span>
          <ArrowUpRight className="w-3.5 h-3.5" />
        </a>
      </div>
    </li>
  );
}

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
  index: number;
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
            className="bg-sky-500/15 text-primary-theme font-medium px-0.5 rounded"
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
  index,
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
      // ignore clipboard permission failure
    }
  };

  return (
    <li
      role="listitem"
      style={{ animationDelay: `${Math.min(index * 55, 360)}ms` }}
      className={`animate-result-in surface-interactive rounded-xl p-4 sm:p-5 ${
        focused ? 'border-sky-400/50 ring-1 ring-sky-400/20' : ''
      }`}
    >
      {/* Top Meta Row */}
      <div className="flex items-center justify-between gap-3 mb-2">
        <div className="flex items-center space-x-2 min-w-0 text-xs font-mono">
          {!faviconBroken ? (
            <img
              src={`https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=32`}
              alt=""
              width={16}
              height={16}
              onError={() => setFaviconBroken(true)}
              className="w-4 h-4 rounded-sm shrink-0 bg-white/5"
            />
          ) : (
            <Globe className="w-3.5 h-3.5 text-muted-theme shrink-0" />
          )}
          <span className="text-secondary-theme font-medium truncate">{domain}</span>
          {path && <span className="text-muted-theme truncate hidden sm:inline">{path}</span>}
        </div>

        <div className="flex items-center space-x-2 shrink-0 text-[11px] font-mono">
          <span className="text-muted-theme">{freshness}</span>
          <span
            className={`px-2 py-0.5 rounded-md border ${
              item.isLive
                ? 'bg-sky-500/10 text-sky-400 border-sky-400/25'
                : 'bg-white/[0.03] text-muted-theme border-white/[0.07]'
            }`}
          >
            {item.isLive ? 'Live' : 'Indexed'}
          </span>
        </div>
      </div>

      {/* Title */}
      <h2 className="text-[16px] sm:text-[17px] font-semibold tracking-tight text-primary-theme mb-1.5 leading-snug">
        <a
          href={safeUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="hover:text-sky-400 transition-colors"
        >
          {item.title || safeUrl}
        </a>
      </h2>

      {/* Snippet */}
      <p className="text-[13.5px] sm:text-[14px] text-secondary-theme leading-relaxed line-clamp-3 mb-3.5">
        <HighlightedSnippet
          text={item.snippet || 'No preview available for this document.'}
          query={query}
        />
      </p>

      {/* Quiet Actions */}
      <div className="flex items-center space-x-4 pt-2.5 border-t border-white/[0.06] text-xs text-muted-theme">
        <button
          type="button"
          onClick={onOpenReader}
          className="inline-flex items-center space-x-1.5 text-sky-400 hover:text-sky-300 font-medium transition-colors"
        >
          <BookOpen className="w-3.5 h-3.5" />
          <span>Reader</span>
        </button>

        <button
          type="button"
          onClick={handleCopy}
          className="inline-flex items-center space-x-1.5 hover:text-primary-theme transition-colors"
        >
          {copied ? (
            <>
              <Check className="w-3.5 h-3.5 text-emerald-400" />
              <span className="text-emerald-400">Copied</span>
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
          className="inline-flex items-center space-x-1 hover:text-primary-theme transition-colors ml-auto"
        >
          <span>Open</span>
          <ArrowUpRight className="w-3.5 h-3.5" />
        </a>
      </div>
    </li>
  );
}

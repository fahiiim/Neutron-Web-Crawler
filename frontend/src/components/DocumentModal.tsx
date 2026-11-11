import DOMPurify from 'dompurify';
import hljs from 'highlight.js/lib/core';
import bash from 'highlight.js/lib/languages/bash';
import javascript from 'highlight.js/lib/languages/javascript';
import json from 'highlight.js/lib/languages/json';
import python from 'highlight.js/lib/languages/python';
import rust from 'highlight.js/lib/languages/rust';
import sql from 'highlight.js/lib/languages/sql';
import 'highlight.js/styles/github-dark.css';
import {
  ArrowUpRight,
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  FileText,
  Loader2,
  Share2,
  X,
} from 'lucide-react';
import { marked } from 'marked';
import { useEffect, useMemo, useRef, useState } from 'react';
import { safeHttpUrl } from '../utils/format';

hljs.registerLanguage('python', python);
hljs.registerLanguage('javascript', javascript);
hljs.registerLanguage('rust', rust);
hljs.registerLanguage('bash', bash);
hljs.registerLanguage('sql', sql);
hljs.registerLanguage('json', json);

interface TocEntry {
  id: string;
  text: string;
  level: number;
}

interface DocumentModalProps {
  open: boolean;
  urlHash: string | null;
  initialTitle: string;
  initialUrl?: string;
  canPrev: boolean;
  canNext: boolean;
  onPrev: () => void;
  onNext: () => void;
  onClose: () => void;
}

export function DocumentModal({
  open,
  urlHash,
  initialTitle,
  initialUrl,
  canPrev,
  canNext,
  onPrev,
  onNext,
  onClose,
}: DocumentModalProps) {
  const [loading, setLoading] = useState(false);
  const [title, setTitle] = useState(initialTitle);
  const [docUrl, setDocUrl] = useState(initialUrl || '');
  const [rawMarkdown, setRawMarkdown] = useState('');
  const [scrollPct, setScrollPct] = useState(0);
  const [toc, setToc] = useState<TocEntry[]>([]);
  const [copiedMd, setCopiedMd] = useState(false);
  const [shared, setShared] = useState(false);

  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const articleRef = useRef<HTMLElement>(null);
  const closeBtnRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open || urlHash === null) return;
    setTitle(initialTitle || 'Document Reader');
    setDocUrl(initialUrl || '');
    setRawMarkdown('');
    setScrollPct(0);
    setToc([]);
    setLoading(true);
    closeBtnRef.current?.focus();

    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/doc/${encodeURIComponent(String(urlHash))}`);
        if (cancelled) return;
        if (!res.ok) {
          setRawMarkdown('Unable to load document payload.');
          return;
        }
        const data = await res.json();
        if (cancelled) return;
        if (data.title) setTitle(data.title);
        if (data.url) setDocUrl(data.url);
        setRawMarkdown(data.full_markdown || 'No content available.');
      } catch {
        if (!cancelled) setRawMarkdown('Connection error while reading document.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [open, urlHash, initialTitle, initialUrl]);

  const sanitizedHtml = useMemo(() => {
    if (!rawMarkdown) return '';
    const html = marked.parse(rawMarkdown, { breaks: true, gfm: true }) as string;
    return DOMPurify.sanitize(html);
  }, [rawMarkdown]);

  useEffect(() => {
    if (!articleRef.current || !sanitizedHtml) {
      setToc([]);
      return;
    }
    articleRef.current.querySelectorAll('pre code').forEach((block) => {
      hljs.highlightElement(block as HTMLElement);
    });

    const headings = Array.from(
      articleRef.current.querySelectorAll('h1, h2, h3, h4')
    );
    const items: TocEntry[] = headings.map((el, idx) => {
      const id = `doc-heading-${idx}`;
      el.id = id;
      return {
        id,
        text: el.textContent || '',
        level: Number(el.tagName.replace('H', '')) || 1,
      };
    });
    setToc(items);
    if (scrollAreaRef.current) {
      scrollAreaRef.current.scrollTop = 0;
    }
  }, [sanitizedHtml]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      else if (e.key === 'ArrowLeft' && canPrev) onPrev();
      else if (e.key === 'ArrowRight' && canNext) onNext();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, canPrev, canNext, onPrev, onNext, onClose]);

  if (!open) return null;

  const handleScroll = () => {
    const el = scrollAreaRef.current;
    if (!el) return;
    const max = el.scrollHeight - el.clientHeight;
    setScrollPct(max > 0 ? Math.min(100, Math.round((el.scrollTop / max) * 100)) : 100);
  };

  const handleCopyMd = async () => {
    if (!rawMarkdown) return;
    await navigator.clipboard.writeText(rawMarkdown);
    setCopiedMd(true);
    window.setTimeout(() => setCopiedMd(false), 1500);
  };

  const handleShare = async () => {
    if (urlHash === null) return;
    const url = `${window.location.origin}/?doc=${encodeURIComponent(String(urlHash))}`;
    await navigator.clipboard.writeText(url);
    setShared(true);
    window.setTimeout(() => setShared(false), 1500);
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="reader-modal-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      className="fixed inset-0 z-50 bg-black/85 backdrop-blur-md flex items-center justify-center sm:p-5"
    >
      <div className="surface-solid w-full h-full sm:h-[86vh] sm:max-w-5xl sm:rounded-2xl flex flex-col overflow-hidden shadow-2xl">
        {/* Glowy Green Progress Line */}
        <div className="w-full h-[2px] bg-white/10 shrink-0">
          <div
            className="h-full bg-emerald-400 shadow-[0_0_8px_#4ade80] transition-all duration-100"
            style={{ width: `${scrollPct}%` }}
          />
        </div>

        {/* Header */}
        <div className="px-4 sm:px-6 py-3.5 border-b border-white/[0.12] flex items-center justify-between gap-3 shrink-0">
          <div className="flex items-center space-x-2.5 min-w-0">
            <FileText className="w-4 h-4 text-emerald-400 shrink-0" />
            <h2
              id="reader-modal-title"
              className="font-varsity text-sm sm:text-base text-white truncate"
            >
              {title}
            </h2>
          </div>

          <div className="flex items-center space-x-1.5 shrink-0">
            <button
              type="button"
              disabled={!canPrev}
              onClick={onPrev}
              aria-label="Previous result"
              className="p-1.5 rounded-lg border border-white/15 text-white hover:text-[#4ade80] disabled:opacity-30 transition-colors"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              type="button"
              disabled={!canNext}
              onClick={onNext}
              aria-label="Next result"
              className="p-1.5 rounded-lg border border-white/15 text-white hover:text-[#4ade80] disabled:opacity-30 transition-colors"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
            <button
              ref={closeBtnRef}
              type="button"
              onClick={onClose}
              aria-label="Close reader"
              className="p-1.5 rounded-lg text-white hover:bg-white/[0.08] transition-colors ml-1"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Body + TOC */}
        <div className="flex-1 flex overflow-hidden">
          {toc.length > 0 && (
            <aside className="hidden md:block w-60 border-r border-white/[0.1] p-4 overflow-y-auto shrink-0">
              <div className="font-varsity text-[11px] tracking-wider text-glow-green mb-3">
                CONTENTS
              </div>
              <ul className="space-y-1.5 text-xs font-classic">
                {toc.map((entry) => (
                  <li key={entry.id}>
                    <button
                      type="button"
                      onClick={() =>
                        document
                          .getElementById(entry.id)
                          ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                      }
                      style={{ paddingLeft: `${Math.max(0, entry.level - 1) * 10}px` }}
                      className="w-full text-left text-white/90 hover:text-[#4ade80] truncate transition-colors py-0.5"
                    >
                      {entry.text}
                    </button>
                  </li>
                ))}
              </ul>
            </aside>
          )}

          <div
            ref={scrollAreaRef}
            onScroll={handleScroll}
            className="flex-1 p-5 sm:p-8 overflow-y-auto"
          >
            {loading ? (
              <div className="flex items-center space-x-2 text-xs font-mono text-glow-green">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Decompressing document from Turso LibSQL...</span>
              </div>
            ) : (
              <article
                ref={articleRef}
                className="markdown-prose max-w-3xl text-[15px]"
                dangerouslySetInnerHTML={{ __html: sanitizedHtml }}
              />
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="px-4 sm:px-6 py-3 border-t border-white/[0.12] flex flex-wrap items-center justify-between gap-2 text-xs shrink-0">
          <div className="flex items-center space-x-2">
            <button
              type="button"
              onClick={handleCopyMd}
              className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg border border-white/20 text-white hover:border-emerald-400/50 transition-colors font-classic"
            >
              {copiedMd ? (
                <>
                  <Check className="w-3.5 h-3.5 text-emerald-400" />
                  <span className="text-glow-green">Copied</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5" />
                  <span>Copy Markdown</span>
                </>
              )}
            </button>

            <button
              type="button"
              onClick={handleShare}
              className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg border border-white/20 text-white hover:border-emerald-400/50 transition-colors font-classic"
            >
              {shared ? (
                <>
                  <Check className="w-3.5 h-3.5 text-emerald-400" />
                  <span className="text-glow-green">Link Copied</span>
                </>
              ) : (
                <>
                  <Share2 className="w-3.5 h-3.5" />
                  <span>Share</span>
                </>
              )}
            </button>

            {docUrl && safeHttpUrl(docUrl) !== '#' && (
              <a
                href={safeHttpUrl(docUrl)}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center space-x-1 px-3 py-1.5 rounded-lg border border-white/20 text-white hover:border-emerald-400/50 transition-colors font-classic"
              >
                <span>Source</span>
                <ArrowUpRight className="w-3.5 h-3.5" />
              </a>
            )}
          </div>

          <button
            type="button"
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg bg-white text-black hover:bg-emerald-300 font-classic font-semibold transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

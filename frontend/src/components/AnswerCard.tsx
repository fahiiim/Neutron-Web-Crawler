import { ArrowUpRight, BookOpen, Check, Copy, Sparkles } from 'lucide-react';
import { Fragment, useState } from 'react';
import { AnswerCitation, GroundedAnswer } from '../types';
import { safeHttpUrl } from '../utils/format';

interface AnswerCardProps {
  answer: GroundedAnswer;
  onOpenCitation: (citation: AnswerCitation) => void;
}

export function AnswerCard({ answer, onOpenCitation }: AnswerCardProps) {
  const [copied, setCopied] = useState(false);

  const citationMap = new Map<number, AnswerCitation>();
  answer.citations.forEach((c) => citationMap.set(c.index, c));

  const handleCopy = async () => {
    const refs = answer.citations
      .map((c) => `[${c.index}] ${c.title} (${safeHttpUrl(c.url)})`)
      .join('\n');
    const full = `${answer.summary}\n\nSources:\n${refs}`;
    try {
      await navigator.clipboard.writeText(full);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      // ignore clipboard errors
    }
  };

  // Render inline [1] citation chips cleanly inside the prose summary
  const parts = answer.summary.split(/(\[\d+\])/g);

  return (
    <section
      aria-label="Grounded Direct Answer"
      className="w-full mb-5 rounded-xl surface-panel border-emerald-400/30 p-4 sm:p-5 shadow-[0_0_26px_-14px_rgba(74,222,128,0.35)]"
    >
      <div className="flex items-center justify-between gap-2 mb-2.5">
        <div className="inline-flex items-center space-x-2">
          <Sparkles className="w-3.5 h-3.5 text-emerald-400" />
          <span className="font-varsity text-[12px] tracking-wider text-glow-green">
            INSTANT ANSWER
          </span>
          <span className="text-[10px] font-mono text-white/60 hidden sm:inline">
            Grounded in {answer.citations.length} {answer.citations.length === 1 ? 'source' : 'sources'}
          </span>
        </div>

        <button
          type="button"
          onClick={handleCopy}
          className="inline-flex items-center space-x-1.5 text-[11px] font-mono px-2.5 py-1 rounded-md border border-white/15 text-white/90 hover:text-[#4ade80] hover:border-emerald-400/40 transition-colors"
        >
          {copied ? (
            <>
              <Check className="w-3 h-3 text-emerald-400" />
              <span className="text-glow-green">Copied Brief</span>
            </>
          ) : (
            <>
              <Copy className="w-3 h-3" />
              <span>Copy Answer</span>
            </>
          )}
        </button>
      </div>

      <p className="font-classic text-[14.5px] sm:text-[15px] text-white leading-relaxed mb-3.5">
        {parts.map((part, idx) => {
          const match = /^\[(\d+)\]$/.exec(part);
          if (match) {
            const num = Number(match[1]);
            const cite = citationMap.get(num);
            if (cite) {
              return (
                <button
                  key={idx}
                  type="button"
                  onClick={() => onOpenCitation(cite)}
                  title={`${cite.title} (${cite.domain})`}
                  className="inline-flex items-center justify-center align-baseline mx-0.5 px-1.5 py-0 rounded text-[11px] font-mono bg-emerald-500/15 text-glow-green border border-emerald-400/40 hover:bg-emerald-500/30 transition-colors"
                >
                  {num}
                </button>
              );
            }
          }
          return <Fragment key={idx}>{part}</Fragment>;
        })}
      </p>

      {answer.citations.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 pt-2.5 border-t border-white/[0.08]">
          {answer.citations.map((cite) => (
            <div
              key={cite.index}
              className="inline-flex items-center rounded-lg bg-white/[0.03] border border-white/[0.12] overflow-hidden text-[11px] font-mono"
            >
              <button
                type="button"
                onClick={() => onOpenCitation(cite)}
                className="inline-flex items-center space-x-1.5 px-2.5 py-1 text-white hover:text-[#4ade80] transition-colors"
                title={`Open "${cite.title}" in Reader`}
              >
                <span className="text-glow-green font-semibold">[{cite.index}]</span>
                <BookOpen className="w-3 h-3 text-emerald-400/80 shrink-0" />
                <span className="truncate max-w-[150px]">{cite.domain}</span>
              </button>
              <a
                href={safeHttpUrl(cite.url)}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={`Open ${cite.domain} externally`}
                className="px-1.5 py-1 border-l border-white/[0.1] text-white/70 hover:text-white transition-colors"
              >
                <ArrowUpRight className="w-3 h-3" />
              </a>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}


import React from "react";
import { ArrowUpRight } from "lucide-react";
import type { AnswerCitation, GroundedAnswer, SearchResult } from "../types";
import type { ReaderTarget } from "./DocumentModal";

interface AnswerCardProps {
  answer: GroundedAnswer;
  results: SearchResult[];
  onOpenReader: (target: ReaderTarget) => void;
}

export const AnswerCard: React.FC<AnswerCardProps> = ({
  answer,
  results,
  onOpenReader,
}) => {
  if (!answer.summary || !answer.summary.trim()) {
    return null;
  }

  const citationMap = new Map<number, AnswerCitation>();
  for (const cite of answer.citations || []) {
    citationMap.set(cite.index, cite);
  }

  const handleCitationClick = (idx: number) => {
    const cite = citationMap.get(idx);
    if (cite?.url) {
      const matched = results.find((r) => r.url === cite.url);
      onOpenReader({
        url: cite.url,
        urlHash: cite.url_hash ?? matched?.url_hash,
        title: cite.title || matched?.title,
      });
      return;
    }
    const target = results[idx - 1];
    if (target?.url) {
      onOpenReader({
        url: target.url,
        urlHash: target.url_hash,
        title: target.title,
      });
    }
  };

  const tokens = answer.summary.split(/(\[\d+\])/g);

  return (
    <section
      aria-label="Summary"
      className="surface-card rounded-xl p-5 sm:p-6 mb-6"
    >
      <div className="flex items-center justify-between gap-2 mb-3">
        <span className="text-xs font-medium tracking-wide uppercase text-neutral-400">
          Summary
        </span>
        {answer.citations && answer.citations.length > 0 && (
          <span className="font-mono-tech text-[11px] text-neutral-500">
            {answer.citations.length}{" "}
            {answer.citations.length === 1 ? "source" : "sources"}
          </span>
        )}
      </div>

      <p className="text-[15px] sm:text-[15.5px] leading-7 text-neutral-200">
        {tokens.map((tok, i) => {
          const match = /^\[(\d+)\]$/.exec(tok);
          if (!match) {
            return <React.Fragment key={i}>{tok}</React.Fragment>;
          }
          const idx = Number(match[1]);
          const cite = citationMap.get(idx);
          return (
            <button
              key={i}
              type="button"
              onClick={() => handleCitationClick(idx)}
              title={cite ? `${cite.domain} — ${cite.title}` : `Source ${idx}`}
              className="inline-flex items-center justify-center mx-0.5 px-1.5 py-0.5 text-[11px] font-mono-tech font-medium text-neutral-200 bg-white/10 hover:bg-white hover:text-black rounded transition-colors align-baseline cursor-pointer"
            >
              {idx}
            </button>
          );
        })}
      </p>

      {answer.citations && answer.citations.length > 0 && (
        <div className="mt-4 pt-3.5 border-t border-white/10 flex flex-wrap gap-2">
          {answer.citations.map((cite) => (
            <button
              key={cite.index}
              type="button"
              onClick={() => handleCitationClick(cite.index)}
              className="group inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-black border border-white/10 hover:border-white/30 text-xs text-neutral-300 hover:text-white transition-colors cursor-pointer"
              title={cite.title}
            >
              <span className="font-mono-tech text-[11px] text-neutral-500 group-hover:text-white">
                {cite.index}
              </span>
              <span className="truncate max-w-[180px]">{cite.domain}</span>
              <ArrowUpRight className="w-3 h-3 text-neutral-500 group-hover:text-white transition-colors" />
            </button>
          ))}
        </div>
      )}
    </section>
  );
};

import React, { useState } from "react";
import { Activity, ArrowUpRight, ChevronDown, ChevronUp, ShieldCheck } from "lucide-react";
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
  const [showEvalDetails, setShowEvalDetails] = useState(false);

  if (!answer.summary || !answer.summary.trim()) {
    return null;
  }

  const evalMetrics = answer.evaluation;
  const grade = evalMetrics?.relevance_grade || "Moderate";
  const confPercent =
    evalMetrics?.confidence_percent ??
    Math.round((evalMetrics?.confidence_score ?? 0.7) * 100);

  const gradeBadgeStyles =
    grade === "High"
      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
      : grade === "Low"
      ? "border-rose-500/30 bg-rose-500/10 text-rose-300"
      : "border-amber-500/30 bg-amber-500/10 text-amber-300";

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
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-medium tracking-wide uppercase text-neutral-400">
            Synthesized Answer
          </span>
          {answer.mode === "gemini_grounded" && (
            <span className="font-mono-tech text-[10px] text-neutral-500 border border-white/10 rounded px-1.5 py-0.5">
              Gemini
            </span>
          )}
          {evalMetrics && (
            <button
              type="button"
              onClick={() => setShowEvalDetails(!showEvalDetails)}
              className={`inline-flex items-center gap-1.5 px-2 py-0.5 text-[11px] font-mono-tech font-medium rounded-full border transition-colors cursor-pointer ${gradeBadgeStyles}`}
              title="Click to toggle evaluation metrics breakdown"
            >
              <ShieldCheck className="w-3 h-3" />
              <span>{confPercent}% {grade} Confidence</span>
              {showEvalDetails ? (
                <ChevronUp className="w-2.5 h-2.5 opacity-70" />
              ) : (
                <ChevronDown className="w-2.5 h-2.5 opacity-70" />
              )}
            </button>
          )}
        </div>
        {answer.citations && answer.citations.length > 0 && (
          <span className="font-mono-tech text-[11px] text-neutral-500">
            {answer.citations.length}{" "}
            {answer.citations.length === 1 ? "source" : "sources"}
          </span>
        )}
      </div>

      {showEvalDetails && evalMetrics && (
        <div className="mb-4 p-3.5 rounded-lg bg-white/[0.03] border border-white/10 text-xs text-neutral-300 space-y-2.5">
          <div className="flex items-center justify-between font-mono-tech text-[11px] text-neutral-400 pb-1.5 border-b border-white/5">
            <span className="flex items-center gap-1.5 text-neutral-300">
              <Activity className="w-3.5 h-3.5 text-neutral-400" />
              Grounded Evaluation Metrics
            </span>
            <span className="text-neutral-400">Relevance: {grade}</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-1">
            <div className="space-y-1">
              <div className="flex justify-between text-[11px]">
                <span className="text-neutral-400">Confidence</span>
                <span className="font-mono-tech text-white">{confPercent}%</span>
              </div>
              <div className="h-1.5 w-full bg-white/10 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${
                    grade === "High"
                      ? "bg-emerald-400"
                      : grade === "Low"
                      ? "bg-rose-400"
                      : "bg-amber-400"
                  }`}
                  style={{ width: `${Math.min(100, Math.max(5, confPercent))}%` }}
                />
              </div>
            </div>

            <div className="space-y-1">
              <div className="flex justify-between text-[11px]">
                <span className="text-neutral-400">Query Concept Coverage</span>
                <span className="font-mono-tech text-white">
                  {Math.round(evalMetrics.query_coverage * 100)}%
                </span>
              </div>
              <div className="h-1.5 w-full bg-white/10 rounded-full overflow-hidden">
                <div
                  className="h-full bg-cyan-400 rounded-full"
                  style={{
                    width: `${Math.min(
                      100,
                      Math.max(5, Math.round(evalMetrics.query_coverage * 100)),
                    )}%`,
                  }}
                />
              </div>
            </div>

            <div className="space-y-1">
              <div className="flex justify-between text-[11px]">
                <span className="text-neutral-400">Grounding Faithfulness</span>
                <span className="font-mono-tech text-white">
                  {Math.round(evalMetrics.grounding_faithfulness * 100)}%
                </span>
              </div>
              <div className="h-1.5 w-full bg-white/10 rounded-full overflow-hidden">
                <div
                  className="h-full bg-indigo-400 rounded-full"
                  style={{
                    width: `${Math.min(
                      100,
                      Math.max(5, Math.round(evalMetrics.grounding_faithfulness * 100)),
                    )}%`,
                  }}
                />
              </div>
            </div>
          </div>

          {(evalMetrics.matched_concepts.length > 0 ||
            evalMetrics.missing_concepts.length > 0) && (
            <div className="flex flex-wrap items-center gap-1.5 pt-1 text-[11px]">
              <span className="text-neutral-400 mr-1">Concepts:</span>
              {evalMetrics.matched_concepts.map((concept) => (
                <span
                  key={concept}
                  className="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 font-mono-tech text-[10px]"
                >
                  ✓ {concept}
                </span>
              ))}
              {evalMetrics.missing_concepts.map((concept) => (
                <span
                  key={concept}
                  className="px-1.5 py-0.5 rounded bg-rose-500/10 text-rose-300 border border-rose-500/20 font-mono-tech text-[10px]"
                >
                  ✕ {concept}
                </span>
              ))}
            </div>
          )}

          {evalMetrics.evaluation_summary && (
            <p className="text-[11px] text-neutral-400 pt-0.5 italic">
              {evalMetrics.evaluation_summary}
            </p>
          )}
        </div>
      )}

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

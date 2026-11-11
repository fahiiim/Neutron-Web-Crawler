import React, { useState } from "react";
import { Check, ChevronDown, ChevronUp, Loader2, Minus } from "lucide-react";

export interface CrawlItemStatus {
  url: string;
  domain: string;
  title?: string;
  status: "pending" | "success" | "blocked" | "error";
  durationMs?: number;
  detail?: string;
}

interface CrawlProgressDrawerProps {
  active: boolean;
  statusText: string;
  items: CrawlItemStatus[];
}

export const CrawlProgressDrawer: React.FC<CrawlProgressDrawerProps> = ({
  active,
  statusText,
  items,
}) => {
  const [expanded, setExpanded] = useState(false);

  if (!active && items.length === 0) {
    return null;
  }

  const completedCount = items.filter((i) => i.status !== "pending").length;

  return (
    <div className="mb-4">
      <div className="flex items-center justify-between gap-3 text-xs text-neutral-400 py-1">
        <div className="flex items-center gap-2 min-w-0">
          {active && <Loader2 className="w-3.5 h-3.5 animate-spin text-white shrink-0" />}
          <span className="truncate">
            {active
              ? statusText || "Checking live web pages..."
              : `Checked ${completedCount} live ${completedCount === 1 ? "source" : "sources"}`}
          </span>
        </div>

        {items.length > 0 && (
          <button
            type="button"
            onClick={() => setExpanded((prev) => !prev)}
            className="inline-flex items-center gap-1 text-neutral-500 hover:text-white transition-colors shrink-0 cursor-pointer"
          >
            <span>{expanded ? "Hide" : "Details"}</span>
            {expanded ? (
              <ChevronUp className="w-3.5 h-3.5" />
            ) : (
              <ChevronDown className="w-3.5 h-3.5" />
            )}
          </button>
        )}
      </div>

      {expanded && items.length > 0 && (
        <div className="surface-card rounded-lg p-3 mt-1.5 space-y-2 max-h-56 overflow-y-auto">
          {items.map((item) => (
            <div
              key={item.url}
              className="flex items-center justify-between gap-3 text-xs"
            >
              <div className="flex items-center gap-2 min-w-0">
                {item.status === "pending" && (
                  <Loader2 className="w-3 h-3 animate-spin text-neutral-400 shrink-0" />
                )}
                {item.status === "success" && (
                  <Check className="w-3 h-3 text-white shrink-0" />
                )}
                {(item.status === "blocked" || item.status === "error") && (
                  <Minus className="w-3 h-3 text-neutral-600 shrink-0" />
                )}
                <span className="font-mono-tech text-[11px] text-neutral-300 truncate">
                  {item.domain}
                </span>
                {item.title && (
                  <span className="text-neutral-500 truncate hidden sm:inline">
                    {item.title}
                  </span>
                )}
              </div>
              <span className="font-mono-tech text-[11px] text-neutral-500 shrink-0">
                {item.status === "pending"
                  ? "fetching"
                  : item.durationMs
                    ? `${item.durationMs}ms`
                    : item.status}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

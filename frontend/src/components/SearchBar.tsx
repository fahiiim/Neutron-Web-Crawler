import React, { useEffect, useRef, useState } from "react";
import { ArrowRight, History, Loader2, Search, X } from "lucide-react";

interface SearchBarProps {
  query: string;
  onChange: (value: string) => void;
  onSubmit: (query: string) => void;
  loading?: boolean;
  compact?: boolean;
  recentQueries?: string[];
  onClearRecent?: () => void;
  inputRef?: React.RefObject<HTMLInputElement>;
}

export const SearchBar: React.FC<SearchBarProps> = ({
  query,
  onChange,
  onSubmit,
  loading = false,
  compact = false,
  recentQueries = [],
  onClearRecent,
  inputRef: externalRef,
}) => {
  const internalRef = useRef<HTMLInputElement>(null);
  const resolvedRef = externalRef || internalRef;
  const containerRef = useRef<HTMLDivElement | null>(null);

  const [focused, setFocused] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [activeIndex, setActiveIndex] = useState(-1);

  useEffect(() => {
    const handleOutside = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setFocused(false);
      }
    };
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, []);

  useEffect(() => {
    const trimmed = query.trim();
    if (!focused || trimmed.length < 2) {
      setSuggestions([]);
      return;
    }

    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const res = await fetch(
          `/suggest?q=${encodeURIComponent(trimmed)}&limit=6`,
          { signal: controller.signal },
        );
        if (!res.ok) return;
        const data = await res.json();
        const items: string[] = Array.isArray(data?.suggestions)
          ? data.suggestions
          : Array.isArray(data)
            ? data
            : [];
        setSuggestions(
          items
            .filter((s) => typeof s === "string" && s.toLowerCase() !== trimmed.toLowerCase())
            .slice(0, 6),
        );
      } catch {
        // Ignore aborted or failed suggestion fetches
      }
    }, 120);

    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [query, focused]);

  const showRecent = focused && query.trim().length === 0 && recentQueries.length > 0;
  const showSuggestions = focused && suggestions.length > 0 && query.trim().length >= 2;
  const dropdownItems = showRecent
    ? recentQueries.slice(0, 5)
    : showSuggestions
      ? suggestions
      : [];

  useEffect(() => {
    setActiveIndex(-1);
  }, [query, focused]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const chosen =
      activeIndex >= 0 && dropdownItems[activeIndex]
        ? dropdownItems[activeIndex]
        : query;
    const trimmed = chosen.trim();
    if (!trimmed) return;
    setFocused(false);
    onChange(trimmed);
    onSubmit(trimmed);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (dropdownItems.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((prev) => (prev + 1) % dropdownItems.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((prev) =>
        prev <= 0 ? dropdownItems.length - 1 : prev - 1,
      );
    } else if (e.key === "Escape") {
      setFocused(false);
      resolvedRef.current?.blur();
    }
  };

  return (
    <div ref={containerRef} className="relative w-full">
      <form
        onSubmit={handleSubmit}
        className={`flex items-center gap-2.5 bg-[#0a0a0a] border transition-colors ${
          focused ? "border-white/40" : "border-white/15 hover:border-white/25"
        } ${compact ? "rounded-lg px-3 py-1.5" : "rounded-xl px-4 py-2.5"}`}
      >
        <Search
          className={`shrink-0 text-neutral-500 ${compact ? "w-4 h-4" : "w-4.5 h-4.5"}`}
        />
        <input
          ref={resolvedRef}
          type="text"
          value={query}
          onChange={(e) => onChange(e.target.value)}
          onFocus={() => setFocused(true)}
          onKeyDown={handleKeyDown}
          placeholder="Search the web..."
          aria-label="Search query"
          autoComplete="off"
          spellCheck="false"
          className={`flex-1 min-w-0 bg-transparent text-white placeholder:text-neutral-500 focus:outline-none ${
            compact ? "text-sm" : "text-[15px]"
          }`}
        />

        {query.length > 0 && (
          <button
            type="button"
            onClick={() => {
              onChange("");
              resolvedRef.current?.focus();
            }}
            aria-label="Clear query"
            className="p-1 text-neutral-500 hover:text-white transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        )}

        {!compact && query.length === 0 && (
          <kbd className="hidden sm:inline-flex items-center px-1.5 py-0.5 text-[11px] font-mono-tech text-neutral-500 border border-white/10 rounded">
            /
          </kbd>
        )}

        <button
          type="submit"
          disabled={loading || !query.trim()}
          aria-label="Submit search"
          className={`inline-flex items-center justify-center shrink-0 bg-white text-black font-medium hover:bg-neutral-200 disabled:opacity-35 disabled:cursor-not-allowed transition-colors cursor-pointer ${
            compact
              ? "rounded-md px-2.5 py-1 text-xs"
              : "rounded-lg px-3.5 py-1.5 text-xs"
          }`}
        >
          {loading ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : compact ? (
            <ArrowRight className="w-3.5 h-3.5" />
          ) : (
            "Search"
          )}
        </button>
      </form>

      {dropdownItems.length > 0 && (
        <div className="absolute left-0 right-0 mt-1.5 bg-[#0a0a0a] border border-white/15 rounded-xl overflow-hidden shadow-2xl z-40">
          {showRecent && (
            <div className="flex items-center justify-between px-3.5 py-2 border-b border-white/10 text-[11px] text-neutral-500">
              <span>Recent</span>
              {onClearRecent && (
                <button
                  type="button"
                  onClick={onClearRecent}
                  className="hover:text-white transition-colors cursor-pointer"
                >
                  Clear
                </button>
              )}
            </div>
          )}
          <ul role="listbox" className="py-1">
            {dropdownItems.map((item, idx) => (
              <li key={item}>
                <button
                  type="button"
                  onMouseDown={(e) => {
                    e.preventDefault();
                    setFocused(false);
                    onChange(item);
                    onSubmit(item);
                  }}
                  className={`w-full flex items-center gap-2.5 px-3.5 py-2 text-left text-sm transition-colors cursor-pointer ${
                    idx === activeIndex
                      ? "bg-white/10 text-white"
                      : "text-neutral-300 hover:bg-white/[0.06] hover:text-white"
                  }`}
                >
                  {showRecent ? (
                    <History className="w-3.5 h-3.5 text-neutral-500 shrink-0" />
                  ) : (
                    <Search className="w-3.5 h-3.5 text-neutral-500 shrink-0" />
                  )}
                  <span className="truncate">{item}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

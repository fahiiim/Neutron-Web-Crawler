import { ArrowRight, Clock, Search, Trash2, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

interface SearchBarProps {
  query: string;
  onQueryChange: (val: string) => void;
  onSubmit: (q: string) => void;
  recentSearches: string[];
  onClearRecent: () => void;
  compact: boolean;
  inputRef: React.RefObject<HTMLInputElement>;
}

export function SearchBar({
  query,
  onQueryChange,
  onSubmit,
  recentSearches,
  onClearRecent,
  compact,
  inputRef,
}: SearchBarProps) {
  const [focused, setFocused] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [activeIdx, setActiveIdx] = useState(-1);
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < 2) {
      setSuggestions([]);
      return;
    }
    const timer = window.setTimeout(async () => {
      try {
        const res = await fetch(`/suggest?q=${encodeURIComponent(trimmed)}`);
        if (res.ok) {
          const data = await res.json();
          const remote: string[] = Array.isArray(data.suggestions) ? data.suggestions : [];
          setSuggestions(
            remote.filter((s) => s.toLowerCase() !== trimmed.toLowerCase()).slice(0, 5)
          );
        }
      } catch {
        setSuggestions([]);
      }
    }, 220);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    const onOutside = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setFocused(false);
      }
    };
    document.addEventListener('mousedown', onOutside);
    return () => document.removeEventListener('mousedown', onOutside);
  }, []);

  const trimmed = query.trim().toLowerCase();
  const matchingRecent = recentSearches
    .filter((r) => (!trimmed ? true : r.toLowerCase().includes(trimmed) && r.toLowerCase() !== trimmed))
    .slice(0, 4);

  const dropdownItems: Array<{ label: string; type: 'recent' | 'suggest' }> = [
    ...matchingRecent.map((label) => ({ label, type: 'recent' as const })),
    ...suggestions
      .filter((s) => !matchingRecent.some((r) => r.toLowerCase() === s.toLowerCase()))
      .map((label) => ({ label, type: 'suggest' as const })),
  ].slice(0, 6);

  const showDropdown = focused && dropdownItems.length > 0;

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!showDropdown) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIdx((i) => Math.min(dropdownItems.length - 1, i + 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIdx((i) => Math.max(-1, i - 1));
    } else if (e.key === 'Enter' && activeIdx >= 0 && dropdownItems[activeIdx]) {
      e.preventDefault();
      const chosen = dropdownItems[activeIdx].label;
      onQueryChange(chosen);
      setFocused(false);
      setActiveIdx(-1);
      onSubmit(chosen);
    } else if (e.key === 'Escape') {
      setFocused(false);
      setActiveIdx(-1);
    }
  };

  return (
    <div ref={wrapperRef} className="w-full relative">
      <form
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          const clean = query.trim();
          if (!clean) return;
          setFocused(false);
          onSubmit(clean);
        }}
      >
        <div
          className={`surface-panel flex items-center w-full transition-all duration-200 ${
            compact ? 'rounded-xl px-3 py-1.5' : 'rounded-2xl px-3.5 py-2 shadow-2xl'
          } ${
            focused
              ? 'border-emerald-400/70 ring-1 ring-emerald-400/25 shadow-[0_0_24px_rgba(74,222,128,0.16)]'
              : 'hover:border-white/25'
          }`}
        >
          <Search className="w-4 h-4 sm:w-[18px] sm:h-[18px] text-emerald-400 shrink-0 ml-1 mr-2.5" />
          <label htmlFor="neutron-search-input" className="sr-only">
            Search the open web
          </label>
          <input
            ref={inputRef}
            id="neutron-search-input"
            type="text"
            value={query}
            onChange={(e) => {
              onQueryChange(e.target.value);
              setActiveIdx(-1);
            }}
            onFocus={() => setFocused(true)}
            onKeyDown={handleKeyDown}
            placeholder="Search web, papers, docs, or code..."
            autoComplete="off"
            className={`w-full bg-transparent font-classic text-white placeholder:text-white/60 focus:outline-none ${
              compact ? 'text-sm py-1.5' : 'text-[15px] sm:text-base py-2'
            }`}
          />
          {query && (
            <button
              type="button"
              onClick={() => {
                onQueryChange('');
                inputRef.current?.focus();
              }}
              aria-label="Clear query"
              className="p-1.5 text-white/80 hover:text-white transition-colors mr-1"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
          <div className="hidden md:flex items-center space-x-1 mr-2.5 text-[11px] font-mono text-white/80 select-none">
            <kbd className="px-1.5 py-0.5 rounded border border-white/20 bg-white/[0.05]">
              /
            </kbd>
          </div>
          <button
            type="submit"
            aria-label="Submit search"
            className={`shrink-0 inline-flex items-center justify-center font-classic font-semibold rounded-lg transition-all active:scale-[0.98] bg-white text-black hover:bg-emerald-300 ${
              compact ? 'px-3 py-1.5 text-xs' : 'px-4 py-2 text-sm'
            }`}
          >
            <span className="hidden sm:inline mr-1.5">Search</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </form>

      {showDropdown && (
        <div
          role="listbox"
          className="absolute left-0 right-0 mt-2 rounded-xl surface-solid shadow-2xl overflow-hidden z-30"
        >
          {matchingRecent.length > 0 && !trimmed && (
            <div className="flex items-center justify-between px-3.5 py-2 border-b border-white/[0.1] text-[11px] font-mono text-white">
              <span>Recent searches</span>
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={onClearRecent}
                className="inline-flex items-center space-x-1 text-glow-green hover:opacity-80 transition-opacity"
              >
                <Trash2 className="w-3 h-3" />
                <span>Clear</span>
              </button>
            </div>
          )}
          <ul className="divide-y divide-white/[0.06]">
            {dropdownItems.map((item, idx) => (
              <li key={`${item.type}-${item.label}`}>
                <button
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => {
                    onQueryChange(item.label);
                    setFocused(false);
                    onSubmit(item.label);
                  }}
                  className={`w-full px-3.5 py-2.5 text-left text-[13px] font-classic flex items-center space-x-2.5 transition-colors ${
                    idx === activeIdx
                      ? 'bg-emerald-500/15 text-glow-green'
                      : 'text-white hover:bg-white/[0.06]'
                  }`}
                >
                  {item.type === 'recent' ? (
                    <Clock className="w-3.5 h-3.5 text-white/80 shrink-0" />
                  ) : (
                    <Search className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                  )}
                  <span className="truncate">{item.label}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

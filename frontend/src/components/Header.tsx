import React, { useState } from "react";
import { Menu, X } from "lucide-react";

interface HeaderProps {
  onGoHome: () => void;
  onOpenStats: () => void;
  pagesIndexed?: number;
}

export const Header: React.FC<HeaderProps> = ({
  onGoHome,
  onOpenStats,
  pagesIndexed,
}) => {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <header className="sticky top-0 z-30 border-b border-white/10 bg-black/95 backdrop-blur-sm">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
        <button
          type="button"
          onClick={() => {
            setMobileOpen(false);
            onGoHome();
          }}
          className="inline-flex items-center gap-2.5 text-white hover:opacity-80 transition-opacity cursor-pointer"
        >
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            aria-hidden="true"
            className="text-white"
          >
            <circle
              cx="12"
              cy="12"
              r="9"
              stroke="currentColor"
              strokeWidth="1.75"
            />
            <circle cx="12" cy="12" r="2.75" fill="currentColor" />
          </svg>
          <span className="text-[15px] font-semibold tracking-tight">
            Neutron
          </span>
        </button>

        <nav className="hidden sm:flex items-center gap-6 text-xs text-neutral-400">
          <button
            type="button"
            onClick={onOpenStats}
            className="hover:text-white transition-colors cursor-pointer inline-flex items-center gap-1.5"
          >
            <span>Index</span>
            {typeof pagesIndexed === "number" && pagesIndexed > 0 && (
              <span className="font-mono-tech text-[11px] text-neutral-500">
                {pagesIndexed.toLocaleString()}
              </span>
            )}
          </button>
          <a href="/privacy" className="hover:text-white transition-colors">
            Privacy
          </a>
          <a
            href="/docs"
            target="_blank"
            rel="noreferrer"
            className="hover:text-white transition-colors"
          >
            API
          </a>
        </nav>

        <button
          type="button"
          onClick={() => setMobileOpen((prev) => !prev)}
          aria-label="Toggle navigation"
          className="sm:hidden p-1.5 text-neutral-400 hover:text-white transition-colors cursor-pointer"
        >
          {mobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
        </button>
      </div>

      {mobileOpen && (
        <div className="sm:hidden border-t border-white/10 bg-black px-4 py-3 flex flex-col gap-3 text-sm text-neutral-300">
          <button
            type="button"
            onClick={() => {
              setMobileOpen(false);
              onOpenStats();
            }}
            className="text-left hover:text-white py-1 cursor-pointer"
          >
            Index status
            {typeof pagesIndexed === "number" && pagesIndexed > 0
              ? ` (${pagesIndexed.toLocaleString()})`
              : ""}
          </button>
          <a
            href="/privacy"
            onClick={() => setMobileOpen(false)}
            className="hover:text-white py-1"
          >
            Privacy
          </a>
          <a
            href="/docs"
            target="_blank"
            rel="noreferrer"
            onClick={() => setMobileOpen(false)}
            className="hover:text-white py-1"
          >
            API Reference
          </a>
        </div>
      )}
    </header>
  );
};

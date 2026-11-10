import { BarChart3, Code2, Github, Menu, X } from 'lucide-react';
import { useState } from 'react';

interface HeaderProps {
  onOpenStats: () => void;
  onResetHome: () => void;
  compact: boolean;
}

export function Header({ onOpenStats, onResetHome, compact }: HeaderProps) {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <header
      className={`sticky top-0 z-40 transition-colors ${
        compact
          ? 'surface-panel border-x-0 border-t-0'
          : 'border-b border-white/[0.1] bg-black/70 backdrop-blur-md'
      }`}
    >
      <div className="max-w-5xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
        <button
          type="button"
          onClick={onResetHome}
          className="flex items-center space-x-2.5 text-left group focus:outline-none"
        >
          <svg
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            className="text-white transition-transform duration-500 group-hover:rotate-45"
            aria-hidden="true"
          >
            <circle cx="12" cy="12" r="2.4" fill="currentColor" />
            <ellipse
              cx="12"
              cy="12"
              rx="9.5"
              ry="4"
              transform="rotate(-25 12 12)"
              stroke="#4ade80"
              strokeWidth="1.25"
            />
            <line
              x1="7.5"
              y1="2.5"
              x2="16.5"
              y2="21.5"
              stroke="currentColor"
              strokeWidth="1.15"
              strokeOpacity="0.7"
            />
          </svg>
          <span className="font-varsity text-[18px] text-white">NEUTRON</span>
          <span className="text-[11px] font-mono text-glow-green hidden sm:inline">
            v3
          </span>
        </button>

        {/* Desktop Nav */}
        <nav
          className="hidden sm:flex items-center space-x-2 text-[13px] font-classic"
          aria-label="Primary"
        >
          <span className="inline-flex items-center space-x-1.5 px-2.5 py-1 rounded-md text-glow-green font-mono text-[11px] mr-1">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shadow-[0_0_8px_#4ade80]" />
            <span>Operational</span>
          </span>
          <button
            type="button"
            onClick={onOpenStats}
            className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-white hover:bg-white/[0.07] transition-colors"
          >
            <BarChart3 className="w-3.5 h-3.5 text-emerald-400" />
            <span>Stats</span>
          </button>
          <a
            href="/docs"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-white hover:bg-white/[0.07] transition-colors"
          >
            <Code2 className="w-3.5 h-3.5" />
            <span>API</span>
          </a>
          <a
            href="https://github.com/fahiiim/Neutron-Web-Crawler"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-white hover:bg-white/[0.07] transition-colors"
          >
            <Github className="w-3.5 h-3.5" />
            <span>Source</span>
          </a>
        </nav>

        {/* Mobile Controls */}
        <div className="flex sm:hidden items-center">
          <button
            type="button"
            onClick={() => setMobileOpen((v) => !v)}
            aria-label="Toggle navigation menu"
            aria-expanded={mobileOpen}
            className="p-2 rounded-lg text-white"
          >
            {mobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>
      </div>

      {mobileOpen && (
        <div className="sm:hidden surface-panel border-x-0 px-4 py-3 flex items-center justify-between text-xs font-classic text-white">
          <button
            type="button"
            onClick={() => {
              setMobileOpen(false);
              onOpenStats();
            }}
            className="inline-flex items-center space-x-1.5 px-2.5 py-1.5 rounded-lg surface-interactive text-white"
          >
            <BarChart3 className="w-3.5 h-3.5 text-emerald-400" />
            <span>Stats</span>
          </button>
          <a
            href="/docs"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center space-x-1.5 px-2.5 py-1.5 rounded-lg surface-interactive text-white"
          >
            <Code2 className="w-3.5 h-3.5" />
            <span>API Docs</span>
          </a>
          <a
            href="https://github.com/fahiiim/Neutron-Web-Crawler"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center space-x-1.5 px-2.5 py-1.5 rounded-lg surface-interactive text-white"
          >
            <Github className="w-3.5 h-3.5" />
            <span>Source</span>
          </a>
        </div>
      )}
    </header>
  );
}

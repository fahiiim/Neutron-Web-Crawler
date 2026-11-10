import { BarChart3, Code2, Github, Menu, Moon, Sun, X } from 'lucide-react';
import { useState } from 'react';

interface HeaderProps {
  lightMode: boolean;
  onToggleTheme: () => void;
  onOpenStats: () => void;
  onResetHome: () => void;
  compact: boolean;
}

export function Header({
  lightMode,
  onToggleTheme,
  onOpenStats,
  onResetHome,
  compact,
}: HeaderProps) {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <header
      className={`sticky top-0 z-40 transition-colors ${
        compact ? 'surface-panel border-x-0 border-t-0' : 'border-b border-white/[0.06]'
      }`}
    >
      <div className="max-w-5xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
        <button
          type="button"
          onClick={onResetHome}
          className="flex items-center space-x-2.5 text-left group focus:outline-none"
        >
          {/* Minimalist geometric pulsar emblem */}
          <svg
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            className="text-sky-400 transition-transform duration-500 group-hover:rotate-45"
            aria-hidden="true"
          >
            <circle cx="12" cy="12" r="2.2" fill="currentColor" />
            <ellipse
              cx="12"
              cy="12"
              rx="9.5"
              ry="4"
              transform="rotate(-25 12 12)"
              stroke="currentColor"
              strokeWidth="1.25"
              strokeOpacity="0.65"
            />
            <line
              x1="7.5"
              y1="2.5"
              x2="16.5"
              y2="21.5"
              stroke="currentColor"
              strokeWidth="1.15"
              strokeOpacity="0.45"
            />
          </svg>
          <span className="font-semibold text-[16px] tracking-tight text-primary-theme">
            Neutron
          </span>
          <span className="text-[11px] font-mono text-muted-theme hidden sm:inline">
            v3
          </span>
        </button>

        {/* Desktop Nav */}
        <nav className="hidden sm:flex items-center space-x-1 text-[13px]" aria-label="Primary">
          <span className="inline-flex items-center space-x-1.5 px-2.5 py-1 rounded-md text-secondary-theme font-mono text-[11px] mr-1">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
            <span>Operational</span>
          </span>
          <button
            type="button"
            onClick={onOpenStats}
            className="inline-flex items-center space-x-1.5 px-2.5 py-1.5 rounded-lg text-secondary-theme hover:text-primary-theme hover:bg-white/[0.05] transition-colors"
          >
            <BarChart3 className="w-3.5 h-3.5" />
            <span>Stats</span>
          </button>
          <a
            href="/docs"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center space-x-1.5 px-2.5 py-1.5 rounded-lg text-secondary-theme hover:text-primary-theme hover:bg-white/[0.05] transition-colors"
          >
            <Code2 className="w-3.5 h-3.5" />
            <span>API</span>
          </a>
          <a
            href="https://github.com/fahiiim/Neutron-Web-Crawler"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center space-x-1.5 px-2.5 py-1.5 rounded-lg text-secondary-theme hover:text-primary-theme hover:bg-white/[0.05] transition-colors"
          >
            <Github className="w-3.5 h-3.5" />
            <span>Source</span>
          </a>
          <button
            type="button"
            onClick={onToggleTheme}
            aria-label="Toggle color theme"
            className="p-2 rounded-lg text-secondary-theme hover:text-primary-theme hover:bg-white/[0.05] transition-colors ml-1"
          >
            {lightMode ? <Moon className="w-4 h-4" /> : <Sun className="w-4 h-4" />}
          </button>
        </nav>

        {/* Mobile Controls */}
        <div className="flex sm:hidden items-center space-x-1">
          <button
            type="button"
            onClick={onToggleTheme}
            aria-label="Toggle color theme"
            className="p-2 rounded-lg text-secondary-theme hover:text-primary-theme"
          >
            {lightMode ? <Moon className="w-4 h-4" /> : <Sun className="w-4 h-4" />}
          </button>
          <button
            type="button"
            onClick={() => setMobileOpen((v) => !v)}
            aria-label="Toggle navigation menu"
            aria-expanded={mobileOpen}
            className="p-2 rounded-lg text-secondary-theme hover:text-primary-theme"
          >
            {mobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>
      </div>

      {mobileOpen && (
        <div className="sm:hidden surface-panel border-x-0 px-4 py-3 flex items-center justify-between text-xs">
          <button
            type="button"
            onClick={() => {
              setMobileOpen(false);
              onOpenStats();
            }}
            className="inline-flex items-center space-x-1.5 px-2.5 py-1.5 rounded-lg surface-interactive text-secondary-theme"
          >
            <BarChart3 className="w-3.5 h-3.5" />
            <span>Stats</span>
          </button>
          <a
            href="/docs"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center space-x-1.5 px-2.5 py-1.5 rounded-lg surface-interactive text-secondary-theme"
          >
            <Code2 className="w-3.5 h-3.5" />
            <span>API Docs</span>
          </a>
          <a
            href="https://github.com/fahiiim/Neutron-Web-Crawler"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center space-x-1.5 px-2.5 py-1.5 rounded-lg surface-interactive text-secondary-theme"
          >
            <Github className="w-3.5 h-3.5" />
            <span>Source</span>
          </a>
        </div>
      )}
    </header>
  );
}

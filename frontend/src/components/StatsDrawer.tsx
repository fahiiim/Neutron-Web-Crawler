import { RefreshCw, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { EngineStats } from '../types';

interface StatsDrawerProps {
  open: boolean;
  onClose: () => void;
}

export function StatsDrawer({ open, onClose }: StatsDrawerProps) {
  const [stats, setStats] = useState<EngineStats | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchStats = async () => {
    setLoading(true);
    try {
      const res = await fetch('/stats');
      if (res.ok) {
        setStats(await res.json());
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) fetchStats();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const formatUptime = (sec?: number) => {
    if (!sec && sec !== 0) return '—';
    const mins = Math.floor(sec / 60);
    if (mins < 60) return `${mins}m`;
    const hrs = Math.floor(mins / 60);
    return `${hrs}h ${mins % 60}m`;
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="stats-drawer-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex justify-end"
    >
      <div className="surface-solid w-full max-w-sm h-full p-6 flex flex-col justify-between shadow-2xl border-y-0 border-r-0">
        <div>
          <div className="flex items-center justify-between pb-4 mb-5 border-b border-white/[0.12]">
            <div>
              <h2
                id="stats-drawer-title"
                className="font-varsity text-base text-white"
              >
                CLUSTER TELEMETRY
              </h2>
              <p className="text-xs font-classic text-white/85 mt-0.5">
                Live Turso LibSQL &amp; Frontier Metrics
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close telemetry panel"
              className="p-1.5 rounded-lg text-white hover:bg-white/[0.08]"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="grid grid-cols-2 gap-3 font-mono">
            <div className="p-3.5 rounded-xl bg-white/[0.03] border border-white/[0.1]">
              <div className="text-[11px] text-white/85 mb-1">Pages Indexed</div>
              <div className="text-xl font-semibold text-glow-green">
                {stats ? stats.pages_indexed.toLocaleString() : '—'}
              </div>
            </div>
            <div className="p-3.5 rounded-xl bg-white/[0.03] border border-white/[0.1]">
              <div className="text-[11px] text-white/85 mb-1">Domains</div>
              <div className="text-xl font-semibold text-white">
                {stats ? stats.domains_covered.toLocaleString() : '—'}
              </div>
            </div>
            <div className="p-3.5 rounded-xl bg-white/[0.03] border border-white/[0.1]">
              <div className="text-[11px] text-white/85 mb-1">Frontier Queue</div>
              <div className="text-xl font-semibold text-white">
                {stats ? stats.frontier_pending.toLocaleString() : '—'}
              </div>
            </div>
            <div className="p-3.5 rounded-xl bg-white/[0.03] border border-white/[0.1]">
              <div className="text-[11px] text-white/85 mb-1">Stored Blobs</div>
              <div className="text-xl font-semibold text-glow-green">
                {stats ? stats.payloads_stored.toLocaleString() : '—'}
              </div>
            </div>
          </div>

          <div className="mt-4 p-4 rounded-xl bg-white/[0.03] border border-white/[0.1] space-y-2.5 text-xs font-mono">
            <div className="flex items-center justify-between">
              <span className="text-white/85">Background Politeness</span>
              <span
                className={
                  stats?.background_crawler_active
                    ? 'text-glow-green'
                    : 'text-white'
                }
              >
                {stats?.background_crawler_active ? 'Active' : 'Idle'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-white/85">Bloom Filter Entries</span>
              <span className="text-white">
                {stats?.bloom_entries !== undefined
                  ? stats.bloom_entries.toLocaleString()
                  : '—'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-white/85">Worker Uptime</span>
              <span className="text-white">{formatUptime(stats?.uptime_seconds)}</span>
            </div>
          </div>
        </div>

        <button
          type="button"
          onClick={fetchStats}
          disabled={loading}
          className="w-full py-2.5 rounded-xl bg-white text-black hover:bg-emerald-300 font-classic font-semibold text-xs inline-flex items-center justify-center space-x-2 transition-colors disabled:opacity-60"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>Refresh Telemetry</span>
        </button>
      </div>
    </div>
  );
}

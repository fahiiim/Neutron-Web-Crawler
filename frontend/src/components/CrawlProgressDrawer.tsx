import {
  Activity,
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Database,
  Globe,
  Loader2,
  ShieldBan,
} from 'lucide-react';
import { CrawlItemStatus, DiscoveryMetric } from '../types';

interface CrawlProgressDrawerProps {
  visible: boolean;
  expanded: boolean;
  onToggleExpand: () => void;
  indexStatus: { count: number; durationMs: number } | null;
  discoveryMetrics: DiscoveryMetric[];
  crawlItems: CrawlItemStatus[];
  isSearching: boolean;
}

export function CrawlProgressDrawer({
  visible,
  expanded,
  onToggleExpand,
  indexStatus,
  discoveryMetrics,
  crawlItems,
  isSearching,
}: CrawlProgressDrawerProps) {
  if (!visible) return null;

  const indexedCount = crawlItems.filter((c) => c.status === 'indexed').length;
  const blockedCount = crawlItems.filter((c) => c.status === 'blocked').length;
  const failedCount = crawlItems.filter((c) => c.status === 'error').length;

  return (
    <section
      aria-label="Live crawl telemetry"
      className="w-full mb-5 rounded-xl surface-panel overflow-hidden text-xs"
    >
      <button
        type="button"
        onClick={onToggleExpand}
        className="w-full px-4 py-2.5 flex items-center justify-between text-left hover:bg-white/[0.03] transition-colors"
      >
        <div className="flex items-center space-x-2.5">
          {isSearching ? (
            <Loader2 className="w-3.5 h-3.5 text-emerald-400 animate-spin" />
          ) : (
            <Activity className="w-3.5 h-3.5 text-emerald-400" />
          )}
          <span className="font-varsity text-[12px] text-white">
            {isSearching ? 'LIVE JIT CRAWL PIPELINE' : 'CRAWL TRACE'}
          </span>
          {crawlItems.length > 0 && (
            <span className="text-[11px] font-mono text-glow-green hidden sm:inline">
              {indexedCount} indexed &middot; {blockedCount} blocked &middot; {failedCount} skipped
            </span>
          )}
        </div>
        <div className="flex items-center space-x-1.5 text-white font-mono text-[11px]">
          <span>{expanded ? 'Collapse' : 'Inspect'}</span>
          {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        </div>
      </button>

      {expanded && (
        <div className="px-4 pb-3.5 pt-2.5 border-t border-white/[0.1] space-y-3 font-mono text-[11px]">
          {indexStatus && (
            <div className="flex items-center justify-between text-white">
              <span className="inline-flex items-center space-x-2">
                <Database className="w-3.5 h-3.5 text-emerald-400" />
                <span>Turso FTS5 index query</span>
              </span>
              <span className="text-glow-green">
                {indexStatus.count} hits ({indexStatus.durationMs}ms)
              </span>
            </div>
          )}

          {discoveryMetrics.length > 0 && (
            <div className="space-y-1.5">
              <div className="font-varsity text-[10px] tracking-wider text-white">
                Seed Discovery
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                {discoveryMetrics.map((m) => (
                  <div
                    key={m.source}
                    className="flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-white/[0.03] border border-white/[0.08]"
                  >
                    <span className="inline-flex items-center space-x-1.5 text-white">
                      <Globe className="w-3 h-3 text-emerald-400" />
                      <span>{m.source}</span>
                    </span>
                    <span className="text-white/90">
                      {m.url_count} URLs &middot; {m.duration_ms}ms
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {crawlItems.length > 0 && (
            <div className="space-y-1.5">
              <div className="font-varsity text-[10px] tracking-wider text-white">
                Live Fetches
              </div>
              <div className="max-h-36 overflow-y-auto space-y-1 pr-1">
                {crawlItems.map((item) => (
                  <div
                    key={item.url}
                    className="flex items-center justify-between gap-3 py-1 text-white"
                  >
                    <span className="inline-flex items-center space-x-2 min-w-0">
                      {item.status === 'fetching' && (
                        <Loader2 className="w-3 h-3 text-emerald-400 animate-spin shrink-0" />
                      )}
                      {item.status === 'indexed' && (
                        <CheckCircle2 className="w-3 h-3 text-emerald-400 shrink-0" />
                      )}
                      {item.status === 'blocked' && (
                        <ShieldBan className="w-3 h-3 text-white shrink-0" />
                      )}
                      {item.status === 'error' && (
                        <AlertCircle className="w-3 h-3 text-white/75 shrink-0" />
                      )}
                      <span className="truncate">{item.domain}</span>
                    </span>
                    <span
                      className={
                        item.status === 'indexed'
                          ? 'text-glow-green shrink-0'
                          : 'text-white/85 shrink-0'
                      }
                    >
                      {item.detail}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

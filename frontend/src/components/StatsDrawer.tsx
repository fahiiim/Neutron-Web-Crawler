import React, { useEffect, useState } from "react";
import { RefreshCw, X } from "lucide-react";
import type { EngineStats } from "../types";
import { getApiBaseUrl, setApiBaseUrl } from "../utils/api";

interface StatsDrawerProps {
  open: boolean;
  onClose: () => void;
  stats: EngineStats | null;
  onRefresh: () => Promise<void> | void;
}

export const StatsDrawer: React.FC<StatsDrawerProps> = ({
  open,
  onClose,
  stats,
  onRefresh,
}) => {
  const [refreshing, setRefreshing] = useState(false);
  const [endpointInput, setEndpointInput] = useState(getApiBaseUrl);
  const [savedNotice, setSavedNotice] = useState(false);

  useEffect(() => {
    if (!open) return;
    setEndpointInput(getApiBaseUrl());
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await onRefresh();
    } finally {
      window.setTimeout(() => setRefreshing(false), 300);
    }
  };

  const handleSaveEndpoint = async (e: React.FormEvent) => {
    e.preventDefault();
    setApiBaseUrl(endpointInput);
    setSavedNotice(true);
    window.setTimeout(() => setSavedNotice(false), 1600);
    await handleRefresh();
  };

  const metrics = [
    {
      label: "Indexed pages",
      value: stats?.pages_indexed?.toLocaleString() ?? "0",
    },
    {
      label: "Domains",
      value: stats?.domains_covered?.toLocaleString() ?? "0",
    },
    {
      label: "Frontier queue",
      value: stats?.frontier_pending?.toLocaleString() ?? "0",
    },
    {
      label: "Stored snapshots",
      value: stats?.payloads_stored?.toLocaleString() ?? "0",
    },
  ];

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Index overview"
      className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex justify-end"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-sm bg-[#0a0a0a] border-l border-white/10 h-full flex flex-col">
        <div className="px-5 h-14 border-b border-white/10 flex items-center justify-between">
          <h2 className="text-sm font-medium text-white">Index Overview</h2>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={handleRefresh}
              aria-label="Refresh stats"
              className="p-1.5 rounded-md text-neutral-400 hover:text-white hover:bg-white/10 transition-colors cursor-pointer"
            >
              <RefreshCw
                className={`w-4 h-4 ${refreshing ? "animate-spin text-white" : ""}`}
              />
            </button>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close panel"
              className="p-1.5 rounded-md text-neutral-400 hover:text-white hover:bg-white/10 transition-colors cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        <div className="p-5 space-y-5 flex-1 overflow-y-auto">
          <div className="grid grid-cols-2 gap-3">
            {metrics.map((m) => (
              <div
                key={m.label}
                className="bg-black border border-white/10 rounded-lg p-4"
              >
                <div className="text-xs text-neutral-500">{m.label}</div>
                <div className="mt-1.5 font-mono-tech text-xl font-medium text-white">
                  {m.value}
                </div>
              </div>
            ))}
          </div>

          <div className="bg-black border border-white/10 rounded-lg p-4 flex items-center justify-between text-xs">
            <span className="text-neutral-400">Gateway status</span>
            <span className="font-mono-tech text-neutral-200">
              {stats?.connected === false ? "Disconnected" : "Connected"}
            </span>
          </div>

          <form
            onSubmit={handleSaveEndpoint}
            className="bg-black border border-white/10 rounded-lg p-4 space-y-2.5"
          >
            <label
              htmlFor="neutron-api-endpoint"
              className="block text-xs text-neutral-400"
            >
              Backend Gateway URL
            </label>
            <input
              id="neutron-api-endpoint"
              type="url"
              value={endpointInput}
              onChange={(e) => setEndpointInput(e.target.value)}
              placeholder="https://your-gateway.leapcell.dev"
              className="w-full px-2.5 py-1.5 rounded-md bg-[#0a0a0a] border border-white/15 focus:border-white/40 focus:outline-none text-xs font-mono-tech text-white placeholder:text-neutral-600"
            />
            <div className="flex items-center justify-between gap-2 pt-1">
              <span className="text-[11px] text-neutral-500">
                {savedNotice ? "Saved" : "Leave blank for same origin"}
              </span>
              <button
                type="submit"
                className="px-2.5 py-1 rounded-md bg-white text-black text-xs font-medium hover:bg-neutral-200 transition-colors cursor-pointer"
              >
                Apply
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
};

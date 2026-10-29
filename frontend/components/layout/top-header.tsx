"use client";

import { Radio } from "lucide-react";

export function TopHeader({
  signalwireConnected = true,
  aiActive = true,
  agentCount = 1,
  transferRinging = false,
}: {
  signalwireConnected?: boolean;
  aiActive?: boolean;
  agentCount?: number;
  transferRinging?: boolean;
}) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 bg-slate-950/80 px-5 py-3 backdrop-blur-md">
      <div className="flex items-center gap-2.5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/25 lg:hidden">
          <Radio className="h-4 w-4" />
        </div>
        <h1 className="text-sm font-semibold tracking-tight text-slate-50 sm:text-base">
          Liberty Weblab{" "}
          <span className="text-emerald-400">DialerAI</span>
        </h1>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {transferRinging ? (
          <span className="inline-flex items-center gap-2 rounded-full border border-amber-500/40 bg-amber-500/15 px-3 py-1.5 text-xs font-semibold text-amber-200 animate-pulse">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-300" />
            </span>
            Transfer ringing
          </span>
        ) : null}
        <span className="inline-flex items-center gap-2 rounded-full border border-slate-800 bg-slate-900/70 px-3 py-1.5 text-xs text-slate-300">
          <span
            className={`h-2 w-2 rounded-full ${
              signalwireConnected
                ? "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]"
                : "bg-rose-400"
            }`}
          />
          {signalwireConnected
            ? "Connected to SignalWire API"
            : "SignalWire disconnected"}
        </span>
        <span className="inline-flex items-center gap-2 rounded-full border border-slate-800 bg-slate-900/70 px-3 py-1.5 text-xs text-slate-300">
          AI Status:{" "}
          <span className={aiActive ? "font-medium text-emerald-400" : "text-slate-400"}>
            {aiActive ? `Active (${agentCount} Agent${agentCount === 1 ? "" : "s"})` : "Idle"}
          </span>
        </span>
      </div>
    </header>
  );
}

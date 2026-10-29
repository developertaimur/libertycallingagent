"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Activity, DollarSign, Mic, Volume2 } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";

type Summary = {
  calls?: number;
  avg_stt_latency_ms?: number;
  avg_tts_ttfb_ms?: number;
  total_cost_usd?: number;
};

type VoiceRow = {
  call_sid?: string;
  avg_stt_latency_ms?: number;
  avg_tts_ttfb_ms?: number;
  barge_ins?: number;
  costs?: { total_usd?: number; deepgram_usd?: number; cartesia_usd?: number };
  live?: boolean;
};

export function VoiceLatencyCard() {
  const [summary, setSummary] = useState<Summary>({});
  const [live, setLive] = useState<VoiceRow[]>([]);
  const [recent, setRecent] = useState<VoiceRow[]>([]);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const data = await api.voiceMetrics(12);
      setSummary(data.summary || {});
      setLive((data.live || []) as VoiceRow[]);
      setRecent((data.recent || []) as VoiceRow[]);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Voice metrics unavailable");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh().catch(() => undefined), 4000);
    return () => window.clearInterval(id);
  }, [refresh]);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Activity className="h-4 w-4 text-emerald-400" />
          Streaming Voice Latency & Cost
        </CardTitle>
        <CardDescription>
          Deepgram Nova-2 STT · Cartesia Sonic TTS · barge-in VAD
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {error ? (
          <p className="text-xs text-amber-200/90">{error}</p>
        ) : null}

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Metric
            icon={<Mic className="h-3.5 w-3.5" />}
            label="Avg STT"
            value={`${Math.round(summary.avg_stt_latency_ms || 0)} ms`}
          />
          <Metric
            icon={<Volume2 className="h-3.5 w-3.5" />}
            label="TTS TTFB"
            value={`${Math.round(summary.avg_tts_ttfb_ms || 0)} ms`}
          />
          <Metric
            icon={<DollarSign className="h-3.5 w-3.5" />}
            label="Est. cost"
            value={`$${(summary.total_cost_usd || 0).toFixed(3)}`}
          />
          <Metric
            icon={<Activity className="h-3.5 w-3.5" />}
            label="Tracked calls"
            value={String(summary.calls || 0)}
          />
        </div>

        {live.length > 0 ? (
          <div>
            <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wider text-emerald-400/80">
              Live
            </p>
            <ul className="space-y-1.5 text-xs text-slate-300">
              {live.map((row) => (
                <li
                  key={row.call_sid || Math.random()}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-2.5 py-1.5"
                >
                  <span className="font-mono text-[11px] text-slate-400">
                    {(row.call_sid || "").slice(0, 18)}
                  </span>
                  <span>
                    STT {Math.round(row.avg_stt_latency_ms || 0)}ms · TTFB{" "}
                    {Math.round(row.avg_tts_ttfb_ms || 0)}ms · barge {row.barge_ins || 0}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {recent.length > 0 ? (
          <div>
            <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wider text-slate-500">
              Recent
            </p>
            <ul className="max-h-36 space-y-1 overflow-y-auto text-xs text-slate-400">
              {recent.slice(0, 6).map((row) => (
                <li
                  key={`${row.call_sid}-${row.avg_tts_ttfb_ms}`}
                  className="flex flex-wrap justify-between gap-2 border-b border-slate-800/80 py-1"
                >
                  <span className="font-mono text-[11px]">
                    {(row.call_sid || "").slice(0, 16)}
                  </span>
                  <span>
                    ${Number(row.costs?.total_usd || 0).toFixed(4)} · STT{" "}
                    {Math.round(row.avg_stt_latency_ms || 0)}ms · TTFB{" "}
                    {Math.round(row.avg_tts_ttfb_ms || 0)}ms
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-xs text-slate-500">
            No streaming calls yet. Set DEEPGRAM_API_KEY + CARTESIA_API_KEY and
            USE_STREAMING_VOICE=true, then re-dial.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function Metric({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/50 px-3 py-2">
      <p className="mb-1 flex items-center gap-1 text-[10px] uppercase tracking-wider text-slate-500">
        {icon}
        {label}
      </p>
      <p className="text-sm font-semibold tabular-nums text-slate-100">{value}</p>
    </div>
  );
}

"use client";

import { PhoneForwarded, PhoneOff, Timer } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Waveform } from "@/components/dashboard/waveform";
import type { ActiveCall } from "@/lib/types";
import { formatDuration } from "@/lib/utils";

export function ActiveDialCard({
  active,
  hangingUp,
  onTransfer,
  onEndCall,
}: {
  active: ActiveCall | null;
  hangingUp?: boolean;
  onTransfer: () => void;
  onEndCall: () => void;
}) {
  const live = Boolean(active?.active && active.call_sid);
  const name = active?.lead_name || "Prospect";
  const phone = active?.phone || "";
  const status = active?.status || "Idle";

  return (
    <Card className="h-full">
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0 pb-3">
        <div className="min-w-0">
          <CardTitle className="text-xs font-medium uppercase tracking-wider text-slate-500">
            Active Dialing Campaign
          </CardTitle>
          <p className="mt-1.5 truncate text-sm font-semibold text-slate-50">
            {live ? (
              <>
                Dialing:{" "}
                <span className="text-cyan-300">{phone || "…"}</span>
                {name ? (
                  <span className="text-slate-400"> ({name})</span>
                ) : null}
              </>
            ) : (
              <span className="text-slate-400">No active dial</span>
            )}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5 rounded-lg bg-slate-950/70 px-2.5 py-1.5 font-mono text-sm tabular-nums text-emerald-300 ring-1 ring-slate-800">
          <Timer className="h-3.5 w-3.5" />
          {formatDuration(live ? active?.duration_seconds || 0 : 0)}
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-2">
          <Badge tone="blue">Voice Mode: AI Agent Natasha</Badge>
          <Badge tone={live ? "green" : "slate"}>
            {live
              ? status.toLowerCase().includes("ring")
                ? "Detecting: Ringing"
                : "Detecting: Natural Human Voice"
              : "Standby"}
          </Badge>
          {active?.transfer_ringing ? (
            <Badge tone="yellow">Desk ringing · expert alert</Badge>
          ) : null}
          {active?.service_type ? (
            <Badge tone="slate">Pitch: {active.service_type}</Badge>
          ) : null}
        </div>

        <Waveform active={live} />

        <div className="space-y-2">
          <p className="text-xs text-slate-500">
            Natasha auto-transfers interested callers to an expert in the first
            15–30s. Use the button only to force a desk ring while testing.
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            <Button
              className="w-full bg-blue-600 text-white hover:bg-blue-500"
              disabled={!live}
              onClick={onTransfer}
              title="Manual test only — agent transfers automatically"
            >
              <PhoneForwarded className="h-4 w-4" />
              Manual Transfer (Test)
            </Button>
            <Button
              variant="danger"
              className="w-full"
              disabled={!live || hangingUp}
              onClick={onEndCall}
            >
              <PhoneOff className="h-4 w-4" />
              End Call
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

"use client";

import { PhoneOff, Timer, UserRound } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { ActiveCall } from "@/lib/types";
import { formatDuration } from "@/lib/utils";

export function LiveCallMonitor({
  active,
  onHangup,
  hangingUp,
}: {
  active: ActiveCall | null;
  onHangup: () => void;
  hangingUp?: boolean;
}) {
  const live = Boolean(active?.active && active.call_sid);

  return (
    <Card className={live ? "border-cyan-500/40 shadow-[0_0_40px_-20px_rgba(34,211,238,0.8)]" : ""}>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle>Live Call Monitor</CardTitle>
        {live ? (
          <Badge tone="blue">{active?.status || "Calling"}</Badge>
        ) : (
          <Badge tone="slate">Idle</Badge>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {live ? (
          <>
            <div className="flex items-start gap-3">
              <div className="rounded-xl bg-slate-800 p-3 text-cyan-300 ring-1 ring-slate-700">
                <UserRound className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-base font-semibold text-slate-50">
                  {active?.lead_name || "Prospect"}
                </p>
                <p className="font-mono text-sm text-slate-400">
                  {active?.phone || "—"}
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  Pitching:{" "}
                  <span className="text-slate-300">
                    {active?.service_type || "General"}
                  </span>
                </p>
              </div>
              <div className="flex items-center gap-1.5 rounded-lg bg-slate-950/60 px-2.5 py-1.5 font-mono text-sm text-cyan-300 ring-1 ring-slate-800">
                <Timer className="h-3.5 w-3.5" />
                {formatDuration(active?.duration_seconds || 0)}
              </div>
            </div>
            <Button
              variant="danger"
              className="w-full"
              disabled={hangingUp}
              onClick={onHangup}
            >
              <PhoneOff className="h-4 w-4" />
              Take Over Call / Emergency Hangup
            </Button>
          </>
        ) : (
          <p className="py-6 text-center text-sm text-slate-500">
            No active call. Start the campaign or place a test dial.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

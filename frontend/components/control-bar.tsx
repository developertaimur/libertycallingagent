"use client";

import { Pause, Play, Radio } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { CampaignStatus } from "@/lib/types";

export function ControlBar({
  campaign,
  loading,
  onStart,
  onPause,
}: {
  campaign: CampaignStatus | null;
  loading?: boolean;
  onStart: () => void;
  onPause: () => void;
}) {
  const running = Boolean(campaign?.running);

  return (
    <div className="flex flex-col gap-4 rounded-2xl border border-slate-800 bg-slate-900/60 p-5 backdrop-blur-md sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-cyan-500/10 text-cyan-300 ring-1 ring-cyan-500/25">
          <Radio className="h-5 w-5" />
        </div>
        <div>
          <h1 className="text-base font-semibold tracking-tight text-slate-50 sm:text-lg">
            Liberty Weblab Dialer
          </h1>
          <p className="text-xs text-slate-400">
            Natasha AI cold-calling campaign control
          </p>
        </div>
        <Badge tone={running ? "green" : "slate"} className="ml-2">
          {running ? "Live" : "Paused"}
        </Badge>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="success"
          size="lg"
          disabled={loading || running}
          onClick={onStart}
        >
          <Play className="h-4 w-4" />
          Start Campaign
        </Button>
        <Button
          variant="danger"
          size="lg"
          disabled={loading || !running}
          onClick={onPause}
        >
          <Pause className="h-4 w-4" />
          Pause Campaign
        </Button>
      </div>
    </div>
  );
}

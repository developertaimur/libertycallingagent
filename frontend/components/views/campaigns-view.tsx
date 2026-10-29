"use client";

import { Pause, Play, RefreshCw } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { ActiveCall, CampaignStatus, Metrics } from "@/lib/types";

export function CampaignsView({
  campaign,
  active,
  metrics,
  busy,
  running,
  onStart,
  onPause,
  onRefresh,
}: {
  campaign: CampaignStatus | null;
  active: ActiveCall | null;
  metrics: Metrics;
  busy: boolean;
  running: boolean;
  onStart: () => void;
  onPause: () => void;
  onRefresh: () => void;
}) {
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-slate-50">Campaigns</h2>
        <p className="mt-1 text-sm text-slate-400">
          Start or pause the Natasha outbound dialer queue.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Status</CardTitle>
            <CardDescription>Live campaign worker</CardDescription>
          </CardHeader>
          <CardContent>
            <Badge tone={running ? "green" : campaign?.paused ? "yellow" : "slate"}>
              {running ? "Running" : campaign?.paused ? "Paused" : "Idle"}
            </Badge>
            {campaign?.last_error ? (
              <p className="mt-3 text-xs text-rose-300">{campaign.last_error}</p>
            ) : null}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Calls placed</CardTitle>
            <CardDescription>This session</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-semibold text-slate-50">
              {campaign?.calls_placed ?? 0}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Queue</CardTitle>
            <CardDescription>Pending / follow-ups</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-semibold text-slate-50">
              {metrics.pending_leads}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {metrics.followups_triggered} follow-ups triggered
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Controls</CardTitle>
          <CardDescription>
            Active leg:{" "}
            {active?.active
              ? `${active.lead_name || "Lead"} · ${active.phone || active.call_sid || ""}`
              : "None"}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Button disabled={busy || running} onClick={onStart}>
            <Play className="h-4 w-4" />
            Start Campaign
          </Button>
          <Button
            variant="secondary"
            disabled={busy || !running}
            onClick={onPause}
          >
            <Pause className="h-4 w-4" />
            Pause
          </Button>
          <Button variant="outline" disabled={busy} onClick={onRefresh}>
            <RefreshCw className="h-4 w-4" />
            Refresh status
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

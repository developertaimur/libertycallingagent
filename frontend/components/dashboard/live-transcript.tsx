"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ActiveCall } from "@/lib/types";
import { cn } from "@/lib/utils";

export function LiveTranscript({
  active,
  handoffSummary,
}: {
  active: ActiveCall | null;
  /** Same AI summary shown after Take over — kept in sync with the ring overlay */
  handoffSummary?: string;
}) {
  const live = Boolean(active?.active && active.call_sid);
  const summary = (
    handoffSummary ||
    active?.conversation_summary ||
    ""
  ).trim();

  return (
    <Card className="flex h-full min-h-[280px] flex-col">
      <CardHeader className="pb-2">
        <CardTitle className="text-xs font-medium uppercase tracking-wider text-slate-500">
          Call Conversation Summary
        </CardTitle>
        {live ? (
          <p className="mt-1 text-[11px] text-slate-500">
            {active?.transfer_ringing
              ? "Live transfer ringing — this summary is what the expert sees on Take over."
              : "Updates when Natasha qualifies the lead or requests an expert."}
          </p>
        ) : null}
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col">
        <div
          className={cn(
            "flex-1 overflow-y-auto rounded-xl border border-slate-800 bg-slate-950/50 p-3",
            "text-sm leading-relaxed text-slate-300 whitespace-pre-wrap",
          )}
        >
          {!live && !summary ? (
            <p className="text-slate-500">
              Waiting for an active call. Conversation summary appears here while
              Natasha is talking, and the same summary is shown when a human takes
              over.
            </p>
          ) : summary ? (
            summary
          ) : (
            <p className="text-slate-500">
              Connected — building summary for{" "}
              <span className="text-slate-300">
                {active?.lead_name || "lead"}
              </span>
              …
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

"use client";

import { useMemo } from "react";
import { LeadQueueTable } from "@/components/dashboard/lead-queue-table";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { Lead } from "@/lib/types";

export function CallLogsView({
  leads,
  onToast,
  onDispatched,
}: {
  leads: Lead[];
  onToast?: (msg: string) => void;
  onDispatched?: () => void;
}) {
  const stats = useMemo(() => {
    const withRecording = leads.filter((l) => l.recording_url).length;
    const withSms = leads.filter((l) => l.sent_sms_content).length;
    const withReply = leads.filter((l) => l.customer_reply).length;
    const dialed = leads.filter((l) => {
      const s = (l.status || "").toLowerCase();
      return s && s !== "pending";
    }).length;
    return { withRecording, withSms, withReply, dialed };
  }, [leads]);

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-slate-50">Call Logs & Records</h2>
        <p className="mt-1 text-sm text-slate-400">
          Recordings, AI summaries, follow-up SMS, voice notes, and customer replies.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-4">
        {[
          { label: "Dialed", value: stats.dialed },
          { label: "Recordings", value: stats.withRecording },
          { label: "SMS sent", value: stats.withSms },
          { label: "Replies", value: stats.withReply },
        ].map((item) => (
          <Card key={item.label}>
            <CardHeader className="pb-1">
              <CardDescription>{item.label}</CardDescription>
              <CardTitle className="text-2xl">{item.value}</CardTitle>
            </CardHeader>
            <CardContent className="pt-0" />
          </Card>
        ))}
      </div>

      <LeadQueueTable
        leads={leads}
        onToast={onToast}
        onDispatched={onDispatched}
      />
    </div>
  );
}

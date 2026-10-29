"use client";

import { useEffect, useMemo, useState } from "react";
import { FileText, Pause, Play } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SummaryModal } from "@/components/summary-modal";
import { DispatchActionButtons } from "@/components/dispatch-actions";
import type { Lead } from "@/lib/types";
import {
  displayOrBlank,
  formatStatusLabel,
  leadId,
  leadName,
  leadPhone,
  leadService,
  leadStatus,
  type LeadLike,
} from "@/lib/leads";
import { statusTone, type BadgeTone } from "@/lib/status";
import { cn } from "@/lib/utils";

function outcomeFor(lead: LeadLike): string {
  const status = leadStatus(lead).toLowerCase();
  if (lead.meeting_booked) return "Meeting Booked";
  if (status.includes("transfer")) return "Transferred to Human";
  if (["calling", "ringing", "in_progress", "in-progress", "running"].some((s) => status.includes(s))) {
    return "AI Engaged";
  }
  if (
    ["no-answer", "no_answer", "unanswered", "busy", "machine", "follow-up"].some((s) =>
      status.includes(s),
    )
  ) {
    return "SMS/VM Sent";
  }
  if (["completed", "answered", "done"].some((s) => status.includes(s))) {
    return "AI Engaged";
  }
  if (status.includes("pending")) return "Queued";
  const summary = displayOrBlank(String(lead.summary || ""));
  if (summary.toLowerCase().includes("sms") || summary.toLowerCase().includes("follow")) {
    return "Sent Follow-up SMS";
  }
  return displayOrBlank(lead.interest_level as string) || formatStatusLabel(status);
}

function queueTone(status: string): BadgeTone {
  const s = status.toLowerCase().replace(/\s+/g, "_");
  if (["calling", "ringing", "running", "in_progress", "in-progress"].some((x) => s.includes(x))) {
    return "green";
  }
  if (["completed", "answered", "done", "booked"].some((x) => s.includes(x))) {
    return "green";
  }
  if (["pending", "queued"].some((x) => s.includes(x))) return "yellow";
  if (["no-answer", "no_answer", "busy", "failed", "unanswered"].some((x) => s.includes(x))) {
    return "red";
  }
  return statusTone(status);
}

function trunc(text: string, n = 72): string {
  const t = text.trim();
  if (!t) return "";
  return t.length > n ? `${t.slice(0, n)}…` : t;
}

function looksLikeUrl(value: string): boolean {
  return /^https?:\/\//i.test(value.trim());
}

export function LeadQueueTable({
  leads,
  onToast,
  onDispatched,
}: {
  leads: Lead[];
  onToast?: (msg: string) => void;
  onDispatched?: () => void;
}) {
  const [selected, setSelected] = useState<Lead | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  /** Optimistic status overrides after Re-dial (cleared when parent refreshes). */
  const [statusOverride, setStatusOverride] = useState<Record<string, string>>({});

  const sorted = useMemo(
    () => [...leads],
    [leads],
  );

  // Drop overrides once live lead status catches up (or changes away from Calling).
  useEffect(() => {
    setStatusOverride((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const [id, override] of Object.entries(prev)) {
        const live = leads.find((l, i) => leadId(l as LeadLike, i) === id);
        if (!live) continue;
        const liveStatus = leadStatus(live as LeadLike);
        if (liveStatus && liveStatus !== override) {
          delete next[id];
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [leads]);

  function markCalling(lead: Lead) {
    const id = leadId(lead as LeadLike);
    setStatusOverride((prev) => ({ ...prev, [id]: "Calling" }));
    setSelected((cur) =>
      cur && leadId(cur as LeadLike) === id
        ? {
            ...cur,
            status: "Calling",
            summary: "",
            error: null,
            last_error: "",
          }
        : cur,
    );
  }

  return (
    <>
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-semibold text-slate-100">
            Real-time Lead Queue & Call Logs
          </CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto px-0 pb-2 sm:px-2">
          <table className="w-full min-w-[1400px] border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-[11px] uppercase tracking-wider text-slate-500">
                <th className="px-4 py-3 font-medium">Lead Name</th>
                <th className="px-4 py-3 font-medium">Phone</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Outcome</th>
                <th className="px-4 py-3 font-medium">📩 Sent SMS</th>
                <th className="px-4 py-3 font-medium">🎙️ Voice Note</th>
                <th className="px-4 py-3 font-medium">💬 Reply</th>
                <th className="px-4 py-3 font-medium">Recording</th>
                <th className="px-4 py-3 font-medium">Transcript Summary</th>
                <th className="px-4 py-3 font-medium">Action</th>
              </tr>
            </thead>
            <tbody>
              {sorted.length === 0 ? (
                <tr>
                  <td colSpan={10} className="px-4 py-12 text-center text-slate-500">
                    No leads in queue — upload a CSV or sync Google Sheets.
                  </td>
                </tr>
              ) : (
                sorted.map((lead, index) => {
                  const row = lead as LeadLike;
                  const id = leadId(row, index);
                  const name = displayOrBlank(leadName(row));
                  const phone = displayOrBlank(leadPhone(row));
                  const status = statusOverride[id] || leadStatus(row);
                  const tone = queueTone(status);
                  const displayLead = {
                    ...lead,
                    status,
                    summary: statusOverride[id] === "Calling" ? "" : lead.summary,
                    ...(statusOverride[id] === "Calling"
                      ? { error: null, last_error: "" }
                      : {}),
                  };
                  const outcome = outcomeFor(displayLead as LeadLike);
                  const summary = trunc(
                    displayOrBlank(String(displayLead.summary || "")).replace(/^\{[\s\S]*\}$/, "") ||
                      displayOrBlank(leadService(row)),
                  );
                  const completed = ["completed", "answered", "done"].some((s) =>
                    status.toLowerCase().includes(s),
                  );
                  const sentSms = displayOrBlank(lead.sent_sms_content || "");
                  const voiceNote = displayOrBlank(lead.voice_note_script_url || "");
                  const reply = displayOrBlank(lead.customer_reply || "");

                  return (
                    <tr
                      key={id}
                      className={cn(
                        "border-b border-slate-800/70 hover:bg-slate-800/30",
                        completed && "bg-cyan-500/[0.04]",
                        reply && "bg-emerald-500/[0.06]",
                      )}
                    >
                      <td className="px-4 py-3 align-middle font-medium text-slate-100">
                        {name}
                      </td>
                      <td className="px-4 py-3 align-middle font-mono text-xs text-slate-400">
                        {phone}
                      </td>
                      <td className="px-4 py-3 align-middle">
                        <Badge tone={tone}>{formatStatusLabel(status)}</Badge>
                      </td>
                      <td className="px-4 py-3 align-middle text-slate-300">
                        {outcome}
                      </td>
                      <td className="max-w-[180px] px-4 py-3 align-middle text-slate-400">
                        <span className="line-clamp-2" title={sentSms}>
                          {trunc(sentSms, 64) || (
                            <span className="text-slate-600">—</span>
                          )}
                        </span>
                      </td>
                      <td className="max-w-[160px] px-4 py-3 align-middle text-slate-400">
                        {voiceNote ? (
                          looksLikeUrl(voiceNote) ? (
                            <a
                              href={voiceNote}
                              target="_blank"
                              rel="noreferrer"
                              className="line-clamp-2 break-all text-cyan-400 hover:underline"
                            >
                              Audio link
                            </a>
                          ) : (
                            <span className="line-clamp-2" title={voiceNote}>
                              {trunc(voiceNote, 48)}
                            </span>
                          )
                        ) : (
                          <span className="text-slate-600">—</span>
                        )}
                      </td>
                      <td className="max-w-[160px] px-4 py-3 align-middle">
                        {reply ? (
                          <span
                            className="line-clamp-2 font-medium text-emerald-400"
                            title={reply}
                          >
                            {trunc(reply, 48)}
                          </span>
                        ) : (
                          <span className="text-slate-600">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 align-middle">
                        {lead.recording_url ? (
                          <Button
                            size="sm"
                            variant="secondary"
                            className="h-8 rounded-full px-3"
                            onClick={() =>
                              setPlaying((p) => (p === id ? null : id))
                            }
                          >
                            {playing === id ? (
                              <Pause className="h-3.5 w-3.5" />
                            ) : (
                              <Play className="h-3.5 w-3.5 fill-current" />
                            )}
                            Play
                          </Button>
                        ) : (
                          <span className="text-slate-600"> </span>
                        )}
                        {playing === id && lead.recording_url ? (
                          <audio
                            className="mt-2 block w-40"
                            controls
                            autoPlay
                            src={lead.recording_url}
                            onEnded={() => setPlaying(null)}
                          />
                        ) : null}
                      </td>
                      <td className="max-w-[200px] px-4 py-3 align-middle text-slate-400">
                        <span className="line-clamp-2">{summary}</span>
                      </td>
                      <td className="px-4 py-3 align-middle">
                        <div className="flex min-w-[200px] flex-col gap-1.5">
                          <DispatchActionButtons
                            lead={displayLead}
                            compact
                            onToast={onToast}
                            onDispatched={onDispatched}
                            onCalling={markCalling}
                          />
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-8 justify-start"
                            onClick={() => setSelected(displayLead)}
                          >
                            <FileText className="h-3.5 w-3.5" />
                            Summary
                          </Button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <SummaryModal
        lead={selected}
        open={Boolean(selected)}
        onClose={() => setSelected(null)}
        onToast={onToast}
        onCalling={markCalling}
        onDispatched={onDispatched}
      />
    </>
  );
}

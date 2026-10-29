"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { MessageSquare, Mic, Pause, Play, RefreshCw, Reply } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DispatchActionButtons } from "@/components/dispatch-actions";
import { NotificationSettings } from "@/components/NotificationSettings";
import { api } from "@/lib/api";
import type { BadgeTone } from "@/lib/status";
import type { Lead } from "@/lib/types";
import { displayOrBlank, leadId, leadName, leadPhone, type LeadLike } from "@/lib/leads";

export type SmsLogRow = {
  recipient_name?: string;
  phone?: string;
  sent_sms_content?: string;
  delivery_status?: string;
  followup_sent_time?: string;
  sms_sid?: string | null;
  dispatch_source?: string;
};

export type VoiceLogRow = {
  recipient_name?: string;
  phone?: string;
  voice_note_script_or_url?: string;
  status?: string;
  followup_sent_time?: string;
  voice_sid?: string | null;
  playable?: boolean;
  dispatch_source?: string;
};

export type ReplyRow = {
  from: string;
  to?: string;
  body: string;
  message_sid?: string;
  received_at?: string;
  recipient_name?: string;
};

function trunc(text: string, n = 90): string {
  const t = (text || "").trim();
  if (!t) return "—";
  return t.length > n ? `${t.slice(0, n)}…` : t;
}

function looksLikeUrl(value: string): boolean {
  return /^https?:\/\//i.test((value || "").trim());
}

function deliveryTone(status: string): BadgeTone {
  const s = (status || "").toLowerCase();
  if (["sent", "initiated", "delivered", "queued"].some((x) => s.includes(x))) {
    return "green";
  }
  if (["failed", "undelivered", "error"].some((x) => s.includes(x))) return "red";
  if (s.includes("skip")) return "slate";
  return "yellow";
}

function sourceTone(source: string): BadgeTone {
  return /manual/i.test(source || "") ? "blue" : "yellow";
}

export function SmsVoiceNotesView({
  leads = [],
  onToast,
  onSettingsSaved,
}: {
  leads?: Lead[];
  onToast?: (msg: string) => void;
  onSettingsSaved?: () => void;
}) {
  const [smsRows, setSmsRows] = useState<SmsLogRow[]>([]);
  const [voiceRows, setVoiceRows] = useState<VoiceLogRow[]>([]);
  const [replies, setReplies] = useState<ReplyRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [playing, setPlaying] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [log, replyRes] = await Promise.all([
        api.listFollowupLog(100),
        api.listSmsReplies(100),
      ]);
      setSmsRows(log.sms || []);
      setVoiceRows(log.voice_notes || []);
      setReplies(replyRes.replies || log.replies || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load outreach logs");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh().catch(() => undefined), 8000);
    return () => window.clearInterval(id);
  }, [refresh]);

  const dispatchLeads = useMemo(() => leads.slice(0, 25), [leads]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-50">SMS & Voice Notes</h2>
          <p className="mt-1 text-sm text-slate-400">
            Automated unanswered follow-ups and manual one-click dispatches.
          </p>
        </div>
        <Button variant="outline" disabled={loading} onClick={() => void refresh()}>
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {error ? (
        <p className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          {error}
        </p>
      ) : null}

      <NotificationSettings
        onSaved={() => {
          onToast?.("Outreach settings saved");
          onSettingsSaved?.();
        }}
      />

      <div className="grid gap-3 sm:grid-cols-3">
        <Card>
          <CardHeader className="pb-1">
            <CardDescription className="flex items-center gap-1.5">
              <MessageSquare className="h-3.5 w-3.5" /> Outbound SMS
            </CardDescription>
            <CardTitle className="text-2xl">{smsRows.length}</CardTitle>
          </CardHeader>
          <CardContent className="pt-0" />
        </Card>
        <Card>
          <CardHeader className="pb-1">
            <CardDescription className="flex items-center gap-1.5">
              <Mic className="h-3.5 w-3.5" /> Voice notes
            </CardDescription>
            <CardTitle className="text-2xl">{voiceRows.length}</CardTitle>
          </CardHeader>
          <CardContent className="pt-0" />
        </Card>
        <Card>
          <CardHeader className="pb-1">
            <CardDescription className="flex items-center gap-1.5">
              <Reply className="h-3.5 w-3.5" /> Customer replies
            </CardDescription>
            <CardTitle className="text-2xl">{replies.length}</CardTitle>
          </CardHeader>
          <CardContent className="pt-0" />
        </Card>
      </div>

      {/* Manual one-click dispatch */}
      <Card>
        <CardHeader>
          <CardTitle>Manual one-click dispatch</CardTitle>
          <CardDescription>
            Send SMS or voice note to any lead now — logged as Manual (User Action)
          </CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto px-0 pb-2 sm:px-2">
          {dispatchLeads.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-slate-500">
              Load leads from Sheets/CSV to enable manual dispatch here.
            </p>
          ) : (
            <table className="w-full min-w-[720px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-[11px] uppercase tracking-wider text-slate-500">
                  <th className="px-4 py-3 font-medium">Lead</th>
                  <th className="px-4 py-3 font-medium">Phone</th>
                  <th className="px-4 py-3 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {dispatchLeads.map((lead, index) => {
                  const row = lead as LeadLike;
                  return (
                    <tr
                      key={leadId(row, index)}
                      className="border-b border-slate-800/70 hover:bg-slate-800/30"
                    >
                      <td className="px-4 py-3 font-medium text-slate-100">
                        {displayOrBlank(leadName(row))}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-400">
                        {displayOrBlank(leadPhone(row))}
                      </td>
                      <td className="px-4 py-3">
                        <DispatchActionButtons
                          lead={lead}
                          onToast={onToast}
                          onDispatched={() => void refresh()}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {/* a. Outbound SMS Logs */}
      <Card>
        <CardHeader>
          <CardTitle>Outbound SMS Logs</CardTitle>
          <CardDescription>Automated + manual SMS with delivery status</CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto px-0 pb-2 sm:px-2">
          <table className="w-full min-w-[980px] border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-[11px] uppercase tracking-wider text-slate-500">
                <th className="px-4 py-3 font-medium">Recipient Name</th>
                <th className="px-4 py-3 font-medium">Phone Number</th>
                <th className="px-4 py-3 font-medium">Sent SMS Content</th>
                <th className="px-4 py-3 font-medium">Delivery Status</th>
                <th className="px-4 py-3 font-medium">Source</th>
                <th className="px-4 py-3 font-medium">Sent Time</th>
              </tr>
            </thead>
            <tbody>
              {smsRows.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-slate-500">
                    No outbound SMS yet — unanswered or manual sends appear here.
                  </td>
                </tr>
              ) : (
                smsRows.map((row, i) => (
                  <tr
                    key={`${row.sms_sid || row.phone}-${i}`}
                    className="border-b border-slate-800/70 hover:bg-slate-800/30"
                  >
                    <td className="px-4 py-3 font-medium text-slate-100">
                      {row.recipient_name || "—"}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-400">
                      {row.phone || "—"}
                    </td>
                    <td className="max-w-[360px] px-4 py-3 text-slate-300">
                      <span className="line-clamp-3" title={row.sent_sms_content || ""}>
                        {trunc(row.sent_sms_content || "", 140)}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <Badge tone={deliveryTone(row.delivery_status || "")}>
                        {row.delivery_status || "unknown"}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      <Badge tone={sourceTone(row.dispatch_source || "")}>
                        {row.dispatch_source || "Automated (Unanswered)"}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-400">
                      {row.followup_sent_time || "—"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {/* b. Voice Note Deliveries */}
      <Card>
        <CardHeader>
          <CardTitle>Voice Note Deliveries</CardTitle>
          <CardDescription>TTS script or MP3 URL — automated and manual</CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto px-0 pb-2 sm:px-2">
          <table className="w-full min-w-[1040px] border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-[11px] uppercase tracking-wider text-slate-500">
                <th className="px-4 py-3 font-medium">Recipient Name</th>
                <th className="px-4 py-3 font-medium">Phone Number</th>
                <th className="px-4 py-3 font-medium">Voice Note Script / Audio URL</th>
                <th className="px-4 py-3 font-medium">Play Audio</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Source</th>
              </tr>
            </thead>
            <tbody>
              {voiceRows.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-slate-500">
                    No voice notes yet.
                  </td>
                </tr>
              ) : (
                voiceRows.map((row, i) => {
                  const id = `${row.voice_sid || row.phone}-${i}`;
                  const media = (row.voice_note_script_or_url || "").trim();
                  const canPlay = looksLikeUrl(media);
                  return (
                    <tr
                      key={id}
                      className="border-b border-slate-800/70 hover:bg-slate-800/30"
                    >
                      <td className="px-4 py-3 font-medium text-slate-100">
                        {row.recipient_name || "—"}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-400">
                        {row.phone || "—"}
                      </td>
                      <td className="max-w-[360px] px-4 py-3 text-slate-300">
                        {canPlay ? (
                          <a
                            href={media}
                            target="_blank"
                            rel="noreferrer"
                            className="break-all text-cyan-400 hover:underline"
                          >
                            {trunc(media, 80)}
                          </a>
                        ) : (
                          <span className="line-clamp-3" title={media}>
                            {trunc(media, 140)}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {canPlay ? (
                          <div>
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
                            {playing === id ? (
                              <audio
                                className="mt-2 block w-44"
                                controls
                                autoPlay
                                src={media}
                                onEnded={() => setPlaying(null)}
                              />
                            ) : null}
                          </div>
                        ) : (
                          <span className="text-xs text-slate-600">TTS only</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <Badge tone={deliveryTone(row.status || "")}>
                          {row.status || "unknown"}
                        </Badge>
                      </td>
                      <td className="px-4 py-3">
                        <Badge tone={sourceTone(row.dispatch_source || "")}>
                          {row.dispatch_source || "Automated (Unanswered)"}
                        </Badge>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {/* c. Inbound Customer Replies */}
      <Card>
        <CardHeader>
          <CardTitle>Inbound Customer Replies</CardTitle>
          <CardDescription>Prospect SMS replies captured by the messaging webhook</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {replies.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-500">
              No customer replies yet. Point SignalWire SMS webhook to{" "}
              <span className="font-mono text-xs text-slate-400">
                /api/messaging/inbound-sms
              </span>
              .
            </p>
          ) : (
            replies.map((r, i) => (
              <div
                key={`${r.message_sid || r.from}-${i}`}
                className="rounded-xl border border-emerald-700/40 bg-emerald-950/35 px-4 py-3"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-medium text-emerald-100">
                    {r.recipient_name || r.from}
                  </p>
                  <p className="font-mono text-[11px] text-emerald-400/80">
                    {r.received_at || ""}
                  </p>
                </div>
                <p className="mt-0.5 font-mono text-xs text-emerald-400/70">{r.from}</p>
                <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-emerald-50">
                  {r.body}
                </p>
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}

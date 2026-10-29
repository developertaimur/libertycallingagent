"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Sidebar, type NavId } from "@/components/layout/sidebar";
import { TopHeader } from "@/components/layout/top-header";
import { KpiStrip, type DashboardMetrics } from "@/components/dashboard/kpi-strip";
import { ActionToolbar } from "@/components/dashboard/action-toolbar";
import { ActiveDialCard } from "@/components/dashboard/active-dial-card";
import { LiveTranscript } from "@/components/dashboard/live-transcript";
import { LeadQueueTable } from "@/components/dashboard/lead-queue-table";
import { VoiceLatencyCard } from "@/components/dashboard/voice-latency-card";
import { TransferRingOverlay } from "@/components/dashboard/transfer-ring-overlay";
import {
  SyncSheetsDialog,
  UploadCsvDialog,
} from "@/components/dashboard/import-dialogs";
import { CampaignsView } from "@/components/views/campaigns-view";
import { LeadsView } from "@/components/views/leads-view";
import { CallLogsView } from "@/components/views/call-logs-view";
import { SmsVoiceNotesView } from "@/components/views/sms-voice-notes-view";
import { KnowledgeView } from "@/components/views/knowledge-view";
import { VoicesView } from "@/components/views/voices-view";
import { api } from "@/lib/api";
import type { ActiveCall, CampaignStatus, Lead, Metrics } from "@/lib/types";

const EMPTY_METRICS: Metrics = {
  total_leads: 0,
  pending_leads: 0,
  calls_completed: 0,
  meetings_booked: 0,
  followups_triggered: 0,
};

const SHEETS_ID_HINT = "GOOGLE_SHEETS_SPREADSHEET_ID";

function isSheetsConfigError(message: string): boolean {
  return message.includes(SHEETS_ID_HINT) || /spreadsheet.?id/i.test(message);
}

export default function DashboardPage() {
  const [nav, setNav] = useState<NavId>("dashboard");
  const [leads, setLeads] = useState<Lead[]>([]);
  const [metrics, setMetrics] = useState<Metrics>(EMPTY_METRICS);
  const [spreadsheetId, setSpreadsheetId] = useState("");
  const [campaign, setCampaign] = useState<CampaignStatus | null>(null);
  const [active, setActive] = useState<ActiveCall | null>(null);
  const [busy, setBusy] = useState(false);
  const [hangingUp, setHangingUp] = useState(false);
  const [toast, setToast] = useState("");
  const [error, setError] = useState("");
  const [sheetsWarning, setSheetsWarning] = useState("");
  const [sheetsWarningDismissed, setSheetsWarningDismissed] = useState(false);
  const [csvOpen, setCsvOpen] = useState(false);
  const [sheetsOpen, setSheetsOpen] = useState(false);
  const [apiHealthy, setApiHealthy] = useState(true);
  const [handoffSummary, setHandoffSummary] = useState("");
  const [deskRinging, setDeskRinging] = useState(false);

  const applyLeadsPayload = useCallback(
    (data: {
      leads?: Lead[];
      metrics?: Metrics;
      spreadsheet_id?: string;
      error?: string | null;
    }) => {
      setLeads(data.leads || []);
      setMetrics(data.metrics || EMPTY_METRICS);
      const sid = data.spreadsheet_id || "";
      setSpreadsheetId(sid);

      if (sid) {
        setSheetsWarning("");
        setSheetsWarningDismissed(false);
        return;
      }

      const msg = (data.error || "").trim();
      if (msg && isSheetsConfigError(msg)) {
        if (!sheetsWarningDismissed) setSheetsWarning(msg);
      } else if (msg) {
        setError(msg);
      }
    },
    [sheetsWarningDismissed],
  );

  const refreshLeads = useCallback(async () => {
    const data = await api.listLeads();
    let merged = data.leads || [];
    try {
      const [repliesRes, followupsRes] = await Promise.all([
        api.listSmsReplies(50),
        api.listFollowupLog(50),
      ]);
      const digits = (p: string) => p.replace(/\D/g, "");
      const replyByPhone = new Map<string, string>();
      for (const r of repliesRes.replies || []) {
        const key = digits(r.from || "");
        if (key && r.body && !replyByPhone.has(key)) {
          replyByPhone.set(key, r.body);
        }
      }
      const followByPhone = new Map<
        string,
        { sms?: string; voice?: string; at?: string; status?: string }
      >();
      for (const f of followupsRes.followups || []) {
        const key = digits(f.phone || "");
        if (!key || followByPhone.has(key)) continue;
        followByPhone.set(key, {
          sms: f.sms_body || "",
          voice: f.voice_note_script_or_url || "",
          at: f.followup_sent_time || "",
          status: f.lead_status || "",
        });
      }
      for (const s of followupsRes.sms || []) {
        const key = digits(s.phone || "");
        if (!key) continue;
        const prev = followByPhone.get(key) || {};
        if (!prev.sms && s.sent_sms_content) {
          followByPhone.set(key, {
            ...prev,
            sms: s.sent_sms_content,
            at: prev.at || s.followup_sent_time || "",
          });
        }
      }
      for (const v of followupsRes.voice_notes || []) {
        const key = digits(v.phone || "");
        if (!key) continue;
        const prev = followByPhone.get(key) || {};
        if (!prev.voice && v.voice_note_script_or_url) {
          followByPhone.set(key, {
            ...prev,
            voice: v.voice_note_script_or_url,
            at: prev.at || v.followup_sent_time || "",
          });
        }
      }
      merged = merged.map((lead) => {
        const key = digits(lead.phone || "");
        const reply = lead.customer_reply || (key && replyByPhone.get(key)) || "";
        const fu = key ? followByPhone.get(key) : undefined;
        const stuckCalling = /^calling$/i.test(lead.status || "");
        return {
          ...lead,
          status:
            stuckCalling && fu?.status
              ? fu.status
              : lead.status,
          customer_reply: reply,
          sent_sms_content: lead.sent_sms_content || fu?.sms || "",
          voice_note_script_url: lead.voice_note_script_url || fu?.voice || "",
          followup_sent_time: lead.followup_sent_time || fu?.at || "",
        };
      });
    } catch {
      /* messaging endpoints optional while API restarts */
    }
    applyLeadsPayload({ ...data, leads: merged });
  }, [applyLeadsPayload]);

  const refreshLive = useCallback(async () => {
    const [c, a] = await Promise.all([
      api.campaignStatus(),
      api.activeCall(),
    ]);
    setCampaign(c);
    setActive(a);
    const liveSummary = (a?.conversation_summary || "").trim();
    if (liveSummary) setHandoffSummary(liveSummary);
    else if (!a?.active) setHandoffSummary("");
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        await Promise.all([refreshLeads(), refreshLive()]);
        setApiHealthy(true);
        setError("");
      } catch (e) {
        setApiHealthy(false);
        const msg = e instanceof Error ? e.message : "Failed to load dashboard";
        // Browser TypeError when API is down / CORS blocked
        setError(
          /failed to fetch/i.test(msg)
            ? `API unreachable at ${api.baseUrl} — start FastAPI on port 8000, then refresh.`
            : msg,
        );
      }
    })();
  }, [refreshLeads, refreshLive]);

  useEffect(() => {
    const id = window.setInterval(() => {
      void refreshLive()
        .then(() => {
          setApiHealthy(true);
          // Clear transient "Failed to fetch" once the API is back
          setError((prev) =>
            /failed to fetch|api unreachable/i.test(prev) ? "" : prev,
          );
        })
        .catch(() => setApiHealthy(false));
    }, 2500);
    const leadsId = window.setInterval(() => {
      void refreshLeads().catch(() => undefined);
    }, 15000);
    return () => {
      window.clearInterval(id);
      window.clearInterval(leadsId);
    };
  }, [refreshLeads, refreshLive]);

  const dashMetrics: DashboardMetrics = useMemo(() => {
    const total = metrics.total_leads || leads.length;
    const completed = metrics.calls_completed || 0;
    const dialed = Math.max(completed, total - (metrics.pending_leads || 0));
    const answerRate =
      dialed > 0 ? Math.min(100, Math.round((completed / dialed) * 100)) : 0;
    const transfers = leads.filter((l) =>
      /transfer/i.test(l.status || "") ||
      /transfer/i.test(l.meeting_status || ""),
    ).length;
    return {
      total_leads: total,
      active_campaigns: campaign?.running ? 1 : 0,
      calls_dialed_today: dialed,
      answer_rate: answerRate,
      transfers,
      sms_vm_sent:
        metrics.followup_notifications_sent ||
        metrics.followups_triggered ||
        0,
    };
  }, [metrics, leads, campaign?.running]);

  async function onStart() {
    setBusy(true);
    setError("");
    try {
      const status = await api.startCampaign();
      setCampaign(status);
      setToast("Dialer campaign started");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Start failed");
    } finally {
      setBusy(false);
    }
  }

  async function onPause() {
    setBusy(true);
    setError("");
    try {
      const status = await api.pauseCampaign();
      setCampaign(status);
      setActive({ active: false });
      setToast("Calls paused");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Pause failed");
    } finally {
      setBusy(false);
    }
  }

  async function onHangup() {
    const sid = active?.call_sid;
    if (!sid) return;
    setHangingUp(true);
    try {
      await api.endCall(sid);
      setActive({ active: false });
      setToast("Call ended");
      await refreshLive();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Hangup failed");
    } finally {
      setHangingUp(false);
    }
  }

  async function onLiveTransfer() {
    const service = active?.service_type || "";
    const expert =
      /market|seo|ads|lead/i.test(service)
        ? "marketing"
        : /web|site|wordpress|e-?comm/i.test(service)
          ? "website"
          : "general";
    try {
      const res = await api.requestTransfer({
        call_sid: active?.call_sid || "",
        lead_id: active?.lead_id || "",
        lead_name: active?.lead_name || "",
        phone: active?.phone || "",
        service_type: service,
        expert_type: expert,
        reason: "Manual test transfer (dashboard)",
        ai_summary: [
          `Lead: ${active?.lead_name || "Unknown"} · ${active?.phone || ""}`,
          `Service: ${service || expert}`,
          `Route to: ${expert} expert`,
          "AI so far: Sales requested live takeover from dashboard. Introduce yourself; confirm their goal; propose next steps.",
        ].join("\n"),
        source: "dashboard",
      });
      setToast(res.message || "Ringing sales desk for live transfer");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Transfer request failed");
    }
  }

  async function onSync(url: string) {
    setSheetsWarning("");
    setSheetsWarningDismissed(false);
    const data = await api.syncSheet(url);
    applyLeadsPayload({ ...data, error: null });
    setToast(`Synced ${data.count ?? data.leads?.length ?? 0} leads`);
    setNav("leads");
  }

  async function onUpload(file: File) {
    const data = await api.uploadCsv(file);
    applyLeadsPayload(data);
    setToast(`Imported leads (${data.written ?? "ok"})`);
    setNav("leads");
  }

  const running = Boolean(campaign?.running);
  const showSheetsBanner =
    Boolean(sheetsWarning) && !spreadsheetId && !sheetsWarningDismissed;

  function handleNav(id: NavId) {
    setNav(id);
  }

  return (
    <div className="flex min-h-screen bg-slate-950 text-slate-100">
      <TransferRingOverlay
        onToast={setToast}
        onHandoffSummary={setHandoffSummary}
        onRingingChange={setDeskRinging}
        agentName="Sales Agent"
      />
      <Sidebar active={nav} onNavigate={handleNav} />

      <div className="flex min-w-0 flex-1 flex-col">
        <TopHeader
          signalwireConnected={apiHealthy}
          aiActive={running || Boolean(active?.active)}
          agentCount={1}
          transferRinging={deskRinging || Boolean(active?.transfer_ringing)}
        />

        <div className="flex-1 space-y-5 overflow-y-auto p-4 sm:p-5 lg:p-6">
          {(error || toast || showSheetsBanner) && (
            <div className="space-y-2">
              {showSheetsBanner ? (
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
                  <p>
                    <span className="font-medium text-amber-200">
                      Sheets not configured.
                    </span>{" "}
                    Sync a Google Sheet URL to load your lead queue.
                  </p>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      className="rounded-lg bg-amber-500/20 px-3 py-1.5 text-xs font-semibold ring-1 ring-amber-500/30 hover:bg-amber-500/30"
                      onClick={() => {
                        setNav("leads");
                        setSheetsOpen(true);
                      }}
                    >
                      Sync Google Sheets
                    </button>
                    <button
                      type="button"
                      className="text-xs text-amber-200/80 underline-offset-2 hover:underline"
                      onClick={() => {
                        setSheetsWarningDismissed(true);
                        setSheetsWarning("");
                      }}
                    >
                      Dismiss
                    </button>
                  </div>
                </div>
              ) : null}
              {error ? (
                <p className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
                  {error}
                  <button
                    type="button"
                    className="ml-3 text-xs underline"
                    onClick={() => setError("")}
                  >
                    dismiss
                  </button>
                </p>
              ) : null}
              {toast ? (
                <p className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
                  {toast}
                  <button
                    type="button"
                    className="ml-3 text-xs underline"
                    onClick={() => setToast("")}
                  >
                    dismiss
                  </button>
                </p>
              ) : null}
            </div>
          )}

          {nav === "dashboard" ? (
            <>
              <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
                <div className="min-w-0 flex-1">
                  <KpiStrip metrics={dashMetrics} />
                </div>
              </div>

              <ActionToolbar
                running={running}
                busy={busy}
                onUploadCsv={() => {
                  setNav("leads");
                  setCsvOpen(true);
                }}
                onSyncSheets={() => {
                  setNav("leads");
                  setSheetsOpen(true);
                }}
                onStart={onStart}
                onPause={onPause}
              />

              <div className="grid gap-4 xl:grid-cols-2">
                <ActiveDialCard
                  active={active}
                  hangingUp={hangingUp}
                  onTransfer={() => void onLiveTransfer()}
                  onEndCall={onHangup}
                />
                <LiveTranscript
                  active={active}
                  handoffSummary={handoffSummary}
                />
              </div>

              <VoiceLatencyCard />

              <LeadQueueTable
                leads={leads}
                onToast={setToast}
                onDispatched={() => void refreshLeads().catch(() => undefined)}
              />
            </>
          ) : null}

          {nav === "campaigns" ? (
            <CampaignsView
              campaign={campaign}
              active={active}
              metrics={metrics}
              busy={busy}
              running={running}
              onStart={onStart}
              onPause={onPause}
              onRefresh={() => void refreshLive()}
            />
          ) : null}

          {nav === "leads" ? (
            <LeadsView
              leads={leads}
              spreadsheetId={spreadsheetId}
              onUploadCsv={() => setCsvOpen(true)}
              onSyncSheets={() => setSheetsOpen(true)}
            />
          ) : null}

          {nav === "logs" ? (
            <CallLogsView
              leads={leads}
              onToast={setToast}
              onDispatched={() => void refreshLeads().catch(() => undefined)}
            />
          ) : null}

          {nav === "outreach" ? (
            <SmsVoiceNotesView
              leads={leads}
              onToast={setToast}
              onSettingsSaved={() => {
                void refreshLeads().catch(() => undefined);
              }}
            />
          ) : null}

          {nav === "knowledge" ? (
            <KnowledgeView onToast={setToast} />
          ) : null}

          {nav === "voices" ? <VoicesView onToast={setToast} /> : null}

          <p className="pb-1 text-center text-[11px] text-slate-600">
            API: {api.baseUrl}
          </p>
        </div>
      </div>

      <SyncSheetsDialog
        open={sheetsOpen}
        onClose={() => setSheetsOpen(false)}
        spreadsheetId={spreadsheetId}
        onSync={onSync}
      />
      <UploadCsvDialog
        open={csvOpen}
        onClose={() => setCsvOpen(false)}
        onUpload={onUpload}
      />
    </div>
  );
}

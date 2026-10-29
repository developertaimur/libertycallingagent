"use client";

import { useEffect, useState } from "react";
import { Loader2, MessageSquare, Mic, Phone, User } from "lucide-react";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import {
  displayOrBlank,
  leadId,
  leadName,
  leadPhone,
  leadService,
  type LeadLike,
} from "@/lib/leads";
import type { Lead } from "@/lib/types";

export function SendSmsModal({
  lead,
  open,
  onClose,
  onSent,
}: {
  lead: Lead | null;
  open: boolean;
  onClose: () => void;
  onSent?: (msg: string) => void;
}) {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const row = lead as LeadLike | null;
  const name = row ? displayOrBlank(leadName(row)) : "";
  const phone = row ? displayOrBlank(leadPhone(row)) : "";
  const id = row ? leadId(row) : "";

  useEffect(() => {
    if (!open || !lead) return;
    setError("");
    setBusy(false);
    setLoading(true);
    void api
      .previewSms({
        lead_id: id,
        phone,
        lead_name: name,
        name,
      })
      .then((res) => setText(res.message_text || res.message || ""))
      .catch(() =>
        setText(
          `Hi ${name || "there"}, Natasha here from Liberty Weblab. Sorry I missed you — when is a good time to connect?`,
        ),
      )
      .finally(() => setLoading(false));
  }, [open, lead, id, phone, name]);

  async function onSend() {
    if (!phone && !id) return;
    setBusy(true);
    setError("");
    try {
      await api.sendManualSms({
        lead_id: id,
        phone,
        lead_name: name,
        message: text.trim(),
      });
      onSent?.("SMS sent successfully!");
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "SMS send failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={() => {
        if (!busy) onClose();
      }}
      title="Review & Edit SMS"
      description="Confirm the message, then send now via SignalWire."
      className="max-w-md"
    >
      <div className="space-y-4">
        <div className="grid gap-2 rounded-xl border border-slate-800 bg-slate-950/50 p-3 sm:grid-cols-2">
          <div className="min-w-0">
            <p className="mb-1 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-slate-500">
              <User className="h-3 w-3" />
              Lead Name
            </p>
            <p className="truncate text-sm font-medium text-slate-100">
              {name || "—"}
            </p>
          </div>
          <div className="min-w-0">
            <p className="mb-1 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-slate-500">
              <Phone className="h-3 w-3" />
              Phone Number
            </p>
            <p className="truncate font-mono text-sm text-slate-200">
              {phone || "—"}
            </p>
          </div>
        </div>

        <div>
          <label
            htmlFor="sms-review-text"
            className="mb-1.5 block text-[11px] font-medium uppercase tracking-wider text-slate-500"
          >
            Message
          </label>
          {loading ? (
            <div className="flex min-h-[140px] items-center justify-center rounded-xl border border-slate-800 bg-slate-950/60 text-sm text-slate-400">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Loading template…
            </div>
          ) : (
            <textarea
              id="sms-review-text"
              className="min-h-[150px] w-full resize-y rounded-xl border border-slate-700 bg-slate-950/70 px-3.5 py-3 text-sm leading-relaxed text-slate-100 shadow-inner outline-none transition placeholder:text-slate-600 focus:border-emerald-500/40 focus:ring-2 focus:ring-emerald-500/20"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="SMS message"
              disabled={busy}
            />
          )}
          <p className="mt-1.5 text-[11px] text-slate-500">
            Pre-filled from your active outreach SMS template. Edit freely before send.
          </p>
        </div>

        {error ? (
          <p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            {error}
          </p>
        ) : null}

        <div className="flex items-center justify-end gap-2 border-t border-slate-800 pt-4">
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="success"
            onClick={() => void onSend()}
            disabled={busy || loading || !text.trim()}
          >
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <MessageSquare className="h-4 w-4" />
            )}
            Send Now
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

export function CallAgainButton({
  lead,
  onToast,
  onCalling,
  size = "sm",
}: {
  lead: Lead;
  onToast?: (msg: string) => void;
  onCalling?: (lead: Lead) => void;
  size?: "sm" | "default";
}) {
  const [busy, setBusy] = useState(false);
  const row = lead as LeadLike;
  const name = displayOrBlank(leadName(row));
  const phone = displayOrBlank(leadPhone(row));
  const id = leadId(row);
  const service = displayOrBlank(leadService(row));
  const displayName = name || phone || "lead";

  async function redial() {
    if (!phone) {
      onToast?.("Missing phone number for re-dial");
      return;
    }
    setBusy(true);
    onCalling?.(lead);
    try {
      await api.makeCall({
        phone,
        lead_name: name,
        lead_id: id,
        service,
        service_type: service,
      });
      onToast?.(`Outbound call queued for ${displayName}`);
    } catch (e) {
      onToast?.(e instanceof Error ? e.message : "Re-dial failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Button
      size={size}
      variant="success"
      className={size === "sm" ? "h-8" : undefined}
      disabled={busy || !phone}
      onClick={() => void redial()}
    >
      {busy ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : (
        <Phone className="h-3.5 w-3.5" />
      )}
      Call Again
    </Button>
  );
}

export function DispatchActionButtons({
  lead,
  onToast,
  onDispatched,
  onCalling,
  compact = false,
}: {
  lead: Lead;
  onToast?: (msg: string) => void;
  onDispatched?: () => void;
  onCalling?: (lead: Lead) => void;
  compact?: boolean;
}) {
  const [smsOpen, setSmsOpen] = useState(false);
  const [voiceBusy, setVoiceBusy] = useState(false);

  const row = lead as LeadLike;
  const name = displayOrBlank(leadName(row));
  const phone = displayOrBlank(leadPhone(row));
  const id = leadId(row);
  const displayName = name || phone || "lead";

  async function sendVoice() {
    if (!phone && !id) return;
    setVoiceBusy(true);
    try {
      await api.sendManualVoicenote({
        lead_id: id,
        phone,
        lead_name: name,
      });
      onToast?.(`Voice Note call queued for ${displayName}`);
      onDispatched?.();
    } catch (e) {
      onToast?.(e instanceof Error ? e.message : "Voice note failed");
    } finally {
      setVoiceBusy(false);
    }
  }

  return (
    <>
      <div className={compact ? "flex flex-col gap-1.5" : "flex flex-wrap gap-1.5"}>
        <CallAgainButton
          lead={lead}
          onToast={onToast}
          onCalling={(l) => {
            onCalling?.(l);
            onDispatched?.();
          }}
        />
        <Button
          size="sm"
          variant="secondary"
          className="h-8"
          onClick={() => setSmsOpen(true)}
        >
          <MessageSquare className="h-3.5 w-3.5" />
          Send SMS
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="h-8"
          disabled={voiceBusy}
          onClick={() => void sendVoice()}
        >
          {voiceBusy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Mic className="h-3.5 w-3.5" />
          )}
          Send Voice Note
        </Button>
      </div>
      <SendSmsModal
        lead={lead}
        open={smsOpen}
        onClose={() => setSmsOpen(false)}
        onSent={(msg) => {
          onToast?.(msg);
          onDispatched?.();
        }}
      />
    </>
  );
}

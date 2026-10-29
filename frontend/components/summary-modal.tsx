"use client";

import { Dialog } from "@/components/ui/dialog";
import { DispatchActionButtons } from "@/components/dispatch-actions";
import type { Lead } from "@/lib/types";
import {
  displayOrBlank,
  leadName,
  leadPhone,
  leadService,
  type LeadLike,
} from "@/lib/leads";

function looksLikeUrl(value: string): boolean {
  return /^https?:\/\//i.test(value.trim());
}

export function SummaryModal({
  lead,
  open,
  onClose,
  onToast,
  onCalling,
  onDispatched,
}: {
  lead: Lead | null;
  open: boolean;
  onClose: () => void;
  onToast?: (msg: string) => void;
  onCalling?: (lead: Lead) => void;
  onDispatched?: () => void;
}) {
  if (!lead) return null;

  const row = lead as LeadLike;
  const name = displayOrBlank(leadName(row)) || "Call Summary";
  const phone = displayOrBlank(leadPhone(row));
  const service = displayOrBlank(leadService(row));

  const sentSms = displayOrBlank(lead.sent_sms_content || "");
  const voiceNote = displayOrBlank(lead.voice_note_script_url || "");
  const customerReply = displayOrBlank(lead.customer_reply || "");
  const followupAt = displayOrBlank(lead.followup_sent_time || "");

  const rows: { label: string; value?: string }[] = [
    { label: "Business Name", value: lead.business_name },
    { label: "Location", value: lead.location },
    { label: "Website URL", value: lead.website_url },
    { label: "Pain Point", value: lead.pain_point },
    { label: "Email", value: lead.preferred_email },
    { label: "Meeting", value: lead.meeting_datetime || lead.meeting_status },
    { label: "Interest", value: lead.interest_level },
    { label: "Status", value: lead.status },
    { label: "Follow-up Sent", value: followupAt },
  ];

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={name}
      description={[phone, service].filter(Boolean).join(" · ") || undefined}
      className="max-w-lg"
    >
      <div className="mb-4 border-b border-slate-800 pb-4">
        <p className="mb-2 text-[11px] font-medium uppercase tracking-wider text-slate-500">
          Actions
        </p>
        <DispatchActionButtons
          lead={lead}
          onToast={onToast}
          onDispatched={onDispatched}
          onCalling={onCalling}
        />
      </div>

      <dl className="space-y-3">
        {rows.map((r) => {
          const value = displayOrBlank(r.value || "");
          if (!value) return null;
          return (
            <div key={r.label} className="grid grid-cols-3 gap-2 text-sm">
              <dt className="text-slate-500">{r.label}</dt>
              <dd className="col-span-2 break-words text-slate-200">{value}</dd>
            </div>
          );
        })}
      </dl>

      {(sentSms || voiceNote || customerReply) && (
        <div className="mt-4 space-y-3">
          {sentSms ? (
            <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                📩 Sent SMS Text
              </p>
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-200">
                {sentSms}
              </p>
            </div>
          ) : null}

          {voiceNote ? (
            <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                🎙️ Voice Note Audio / Script
              </p>
              {looksLikeUrl(voiceNote) ? (
                <a
                  href={voiceNote}
                  target="_blank"
                  rel="noreferrer"
                  className="break-all text-sm text-cyan-400 underline-offset-2 hover:underline"
                >
                  {voiceNote}
                </a>
              ) : (
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-200">
                  {voiceNote}
                </p>
              )}
            </div>
          ) : null}

          {customerReply ? (
            <div className="rounded-xl border border-emerald-700/50 bg-emerald-950/40 p-3">
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-emerald-400">
                💬 Customer Reply
              </p>
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-emerald-100">
                {customerReply}
              </p>
            </div>
          ) : null}
        </div>
      )}

      <div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/60 p-3">
        <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
          AI Summary
        </p>
        <p className="text-sm leading-relaxed text-slate-300">
          {displayOrBlank(lead.summary || "") || "No summary captured yet."}
        </p>
      </div>
    </Dialog>
  );
}

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { BellOff, PhoneForwarded, Volume2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import {
  isTransferAudioUnlocked,
  startTransferRingtone,
  stopTransferRingtone,
  unlockTransferAudio,
} from "@/lib/transfer-ringtone";
import { cn } from "@/lib/utils";

export type TransferRing = {
  id: string;
  call_sid?: string;
  lead_name?: string;
  phone?: string;
  service_type?: string;
  expert_type?: string;
  expert_label?: string;
  ai_summary?: string;
  reason?: string;
  seconds_remaining?: number;
  ringing?: boolean;
  status?: string;
};

export function TransferRingOverlay({
  onToast,
  onHandoffSummary,
  onRingingChange,
  agentName = "Sales Agent",
}: {
  onToast?: (msg: string) => void;
  /** Mirrors Take over AI summary into the dashboard Call Conversation Summary panel */
  onHandoffSummary?: (summary: string) => void;
  onRingingChange?: (ringing: boolean) => void;
  agentName?: string;
}) {
  const [ringing, setRinging] = useState<TransferRing[]>([]);
  const [claiming, setClaiming] = useState<string | null>(null);
  const [claimedSummary, setClaimedSummary] = useState<{
    summary: string;
    expert: string;
    lead: string;
  } | null>(null);
  const [soundOn, setSoundOn] = useState(true);
  const [needsUnlock, setNeedsUnlock] = useState(false);
  const activeRingId = useRef<string | null>(null);
  const notifiedIds = useRef<Set<string>>(new Set());

  const stopRing = useCallback(() => {
    stopTransferRingtone();
    activeRingId.current = null;
  }, []);

  const beginRing = useCallback(
    async (id: string) => {
      if (!soundOn) return;
      if (activeRingId.current === id) return;
      activeRingId.current = id;
      const ok = await unlockTransferAudio();
      if (!ok || !isTransferAudioUnlocked()) {
        setNeedsUnlock(true);
        return;
      }
      setNeedsUnlock(false);
      startTransferRingtone();
    },
    [soundOn],
  );

  const pushDesktopNotify = useCallback((t: TransferRing) => {
    if (typeof window === "undefined" || !("Notification" in window)) return;
    if (notifiedIds.current.has(t.id)) return;
    notifiedIds.current.add(t.id);
    const title = "Incoming live transfer";
    const body = `${t.lead_name || "Lead"} · ${t.phone || "—"} → ${
      t.expert_label || t.expert_type || "Expert"
    }`;
    const show = () => {
      try {
        new Notification(title, {
          body,
          tag: `transfer-${t.id}`,
          requireInteraction: true,
        });
      } catch {
        /* ignored */
      }
    };
    if (Notification.permission === "granted") show();
    else if (Notification.permission === "default") {
      void Notification.requestPermission().then((p) => {
        if (p === "granted") show();
      });
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const data = await api.pendingTransfers();
      const rows = (data.ringing || []) as TransferRing[];
      setRinging(rows);
      onRingingChange?.(rows.length > 0);
      if (rows.length > 0) {
        const top = rows[0];
        const s = String(top?.ai_summary || "").trim();
        if (s) onHandoffSummary?.(s);
        pushDesktopNotify(top);
        void beginRing(top.id);
      } else {
        stopRing();
      }
    } catch {
      /* API restarting */
    }
  }, [beginRing, stopRing, onHandoffSummary, onRingingChange, pushDesktopNotify]);

  // Unlock audio on first dashboard interaction (browser autoplay policy)
  useEffect(() => {
    const unlock = () => {
      void unlockTransferAudio().then((ok) => {
        if (ok) setNeedsUnlock(false);
      });
    };
    window.addEventListener("pointerdown", unlock, { once: true });
    window.addEventListener("keydown", unlock, { once: true });
    return () => {
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
    };
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), 1500);
    return () => {
      window.clearInterval(id);
      stopRing();
    };
  }, [refresh, stopRing]);

  useEffect(() => {
    if (!soundOn) stopRing();
    else if (ringing[0]?.id) void beginRing(ringing[0].id);
  }, [soundOn, ringing, beginRing, stopRing]);

  async function enableSound() {
    const ok = await unlockTransferAudio();
    setNeedsUnlock(!ok);
    setSoundOn(true);
    if (ok && ringing[0]) {
      activeRingId.current = null;
      void beginRing(ringing[0].id);
    }
    onToast?.(ok ? "Transfer ringtone enabled" : "Click again after interacting with the page");
  }

  async function onClaim(t: TransferRing) {
    setClaiming(t.id);
    try {
      const res = await api.claimTransfer(t.id, agentName);
      stopRing();
      setRinging((prev) => prev.filter((x) => x.id !== t.id));
      const summaryText = String(res.ai_summary || t.ai_summary || "");
      setClaimedSummary({
        summary: summaryText,
        expert: String(res.bridge?.expert_label || t.expert_label || "Expert"),
        lead: t.lead_name || t.phone || "Lead",
      });
      if (summaryText.trim()) onHandoffSummary?.(summaryText);
      const num = res.bridge?.expert_number;
      onToast?.(
        num
          ? `Take over claimed — bridge target ${num}. Use AI summary before speaking.`
          : "Take over claimed — open AI summary for warm handoff.",
      );
      void refresh();
    } catch (e) {
      onToast?.(e instanceof Error ? e.message : "Take over failed");
    } finally {
      setClaiming(null);
    }
  }

  const top = ringing[0];

  return (
    <>
      {top ? (
        <div
          className="fixed inset-x-0 top-0 z-50 flex justify-center p-3 pointer-events-none"
          role="alert"
          aria-live="assertive"
        >
          <div
            className={cn(
              "pointer-events-auto w-full max-w-xl overflow-hidden rounded-2xl border border-amber-400/50",
              "bg-slate-950/95 shadow-2xl shadow-amber-500/30 ring-2 ring-amber-400/40 backdrop-blur",
            )}
          >
            <div className="flex items-start gap-3 bg-gradient-to-r from-amber-500/25 to-transparent px-4 py-3">
              <div
                className={cn(
                  "mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-full",
                  "bg-amber-500/25 text-amber-300",
                  "animate-bounce",
                )}
              >
                <PhoneForwarded className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-wider text-amber-300">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="relative flex h-2 w-2">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75" />
                      <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-300" />
                    </span>
                    Ringing · {top.seconds_remaining ?? 0}s
                  </span>
                </p>
                <p className="truncate text-base font-semibold text-slate-50">
                  {top.lead_name || "Lead"} · {top.phone || "—"}
                </p>
                <p className="text-sm text-slate-300">
                  Needs:{" "}
                  <span className="font-medium text-emerald-300">
                    {top.expert_label || top.expert_type || "Specialist"}
                  </span>
                  {top.service_type ? ` · ${top.service_type}` : ""}
                </p>
                {needsUnlock ? (
                  <button
                    type="button"
                    className="mt-1 text-left text-[11px] font-medium text-amber-200 underline-offset-2 hover:underline"
                    onClick={() => void enableSound()}
                  >
                    Click to enable ringtone sound
                  </button>
                ) : null}
              </div>
              <div className="flex shrink-0 flex-col gap-1.5 sm:flex-row">
                <Button
                  size="sm"
                  variant="secondary"
                  className="px-2"
                  title={soundOn ? "Mute ring" : "Unmute ring"}
                  onClick={() => {
                    if (soundOn) {
                      setSoundOn(false);
                      stopRing();
                    } else {
                      void enableSound();
                    }
                  }}
                >
                  {soundOn ? (
                    <Volume2 className="h-4 w-4" />
                  ) : (
                    <BellOff className="h-4 w-4" />
                  )}
                </Button>
                <Button
                  size="sm"
                  variant="success"
                  disabled={claiming === top.id}
                  onClick={() => void onClaim(top)}
                >
                  Take over
                </Button>
              </div>
            </div>
            {top.ai_summary ? (
              <pre className="max-h-28 overflow-y-auto whitespace-pre-wrap border-t border-slate-800 px-4 py-2 text-[11px] leading-relaxed text-slate-400">
                {top.ai_summary}
              </pre>
            ) : null}
          </div>
        </div>
      ) : null}

      {claimedSummary ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-lg rounded-2xl border border-slate-700 bg-slate-950 p-5 shadow-2xl">
            <div className="mb-3 flex items-start justify-between gap-2">
              <div>
                <p className="text-xs uppercase tracking-wider text-emerald-400">
                  Warm handoff · {claimedSummary.expert}
                </p>
                <h3 className="text-lg font-semibold text-slate-50">
                  {claimedSummary.lead}
                </h3>
              </div>
              <button
                type="button"
                className="rounded-lg p-1 text-slate-500 hover:bg-slate-800 hover:text-slate-200"
                onClick={() => setClaimedSummary(null)}
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <p className="mb-2 text-[11px] font-medium uppercase tracking-wider text-slate-500">
              AI call summary — read before speaking
            </p>
            <pre className="max-h-64 overflow-y-auto whitespace-pre-wrap rounded-xl border border-slate-800 bg-slate-900/80 p-3 text-sm leading-relaxed text-slate-200">
              {claimedSummary.summary || "No summary provided."}
            </pre>
            <div className="mt-4 flex justify-end">
              <Button onClick={() => setClaimedSummary(null)}>Got it — I&apos;m live</Button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

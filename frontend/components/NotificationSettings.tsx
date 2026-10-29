"use client";

import { useEffect, useState } from "react";
import { BellRing, Save } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, type OutreachSettings } from "@/lib/api";
import { cn } from "@/lib/utils";

const DEFAULT_TEMPLATE =
  "Hi {name}, Natasha here from Liberty Weblab. Sorry I missed you regarding your website performance. When is a good time to connect?";

function Toggle({
  checked,
  onChange,
  id,
  label,
  description,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  id: string;
  label: string;
  description?: string;
}) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-xl border border-slate-800 bg-slate-950/40 px-4 py-3">
      <div className="min-w-0">
        <label htmlFor={id} className="text-sm font-medium text-slate-100">
          {label}
        </label>
        {description ? (
          <p className="mt-0.5 text-xs text-slate-500">{description}</p>
        ) : null}
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative h-6 w-11 shrink-0 rounded-full transition",
          checked ? "bg-emerald-500" : "bg-slate-700",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition",
            checked ? "left-5" : "left-0.5",
          )}
        />
      </button>
    </div>
  );
}

export function NotificationSettings({
  className,
  onSaved,
}: {
  className?: string;
  onSaved?: (settings: OutreachSettings) => void;
}) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");
  const [enableSms, setEnableSms] = useState(true);
  const [enableVoice, setEnableVoice] = useState(true);
  const [template, setTemplate] = useState(DEFAULT_TEMPLATE);
  const [voiceType, setVoiceType] = useState<"tts" | "audio">("tts");
  const [mediaUrl, setMediaUrl] = useState("");
  const [sentCount, setSentCount] = useState(0);

  useEffect(() => {
    void (async () => {
      try {
        const data = await api.getOutreachSettings();
        const s = data.settings;
        setEnableSms(Boolean(s.enable_unanswered_sms));
        setEnableVoice(Boolean(s.enable_unanswered_voicenote));
        setTemplate(s.sms_template_content || DEFAULT_TEMPLATE);
        setVoiceType(s.voice_note_type === "audio" ? "audio" : "tts");
        setMediaUrl(s.voice_media_url || "");
        setSentCount(
          Number(data.analytics?.followup_notifications_sent || 0),
        );
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load settings");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  async function save() {
    setSaving(true);
    setError("");
    setOk("");
    try {
      const data = await api.saveOutreachSettings({
        enable_unanswered_sms: enableSms,
        enable_unanswered_voicenote: enableVoice,
        sms_template_content: template,
        voice_note_type: voiceType,
        voice_media_url: mediaUrl,
      });
      setSentCount(
        Number(data.analytics?.followup_notifications_sent || sentCount),
      );
      setOk("Outreach settings saved");
      onSaved?.(data.settings);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <BellRing className="h-4 w-4 text-amber-300" />
          Customer Outreach Settings
        </CardTitle>
        <CardDescription>
          Automated SMS + voice-note delivery when calls go unanswered.
          {sentCount > 0 ? (
            <span className="mt-1 block text-emerald-400/90">
              Follow-up Delivered: {sentCount.toLocaleString()}
            </span>
          ) : null}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {loading ? (
          <p className="text-sm text-slate-500">Loading settings…</p>
        ) : (
          <>
            <Toggle
              id="enable_unanswered_sms"
              checked={enableSms}
              onChange={setEnableSms}
              label="Automated SMS Notification on Unanswered Status"
              description="Sends when status is no-answer, busy, failed, or machine_start."
            />
            <Toggle
              id="enable_unanswered_voicenote"
              checked={enableVoice}
              onChange={setEnableVoice}
              label="Automated Voice Note Delivery"
              description="Places a short SWML call with Natasha TTS or your MP3."
            />

            <div>
              <label
                htmlFor="sms_template_content"
                className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-slate-500"
              >
                SMS Template
              </label>
              <textarea
                id="sms_template_content"
                rows={3}
                value={template}
                onChange={(e) => setTemplate(e.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950/80 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/50"
              />
              <p className="mt-1 text-[11px] text-slate-500">
                Use {"{name}"} for the lead&apos;s first name.
              </p>
            </div>

            <div>
              <p className="mb-1.5 text-xs font-medium uppercase tracking-wider text-slate-500">
                Voice Note Type
              </p>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant={voiceType === "tts" ? "default" : "secondary"}
                  onClick={() => setVoiceType("tts")}
                >
                  Dynamic TTS Synthesis
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={voiceType === "audio" ? "default" : "secondary"}
                  onClick={() => setVoiceType("audio")}
                >
                  Audio File (MP3 URL)
                </Button>
              </div>
              {voiceType === "audio" ? (
                <Input
                  className="mt-2"
                  placeholder="https://…/voicemail.mp3"
                  value={mediaUrl}
                  onChange={(e) => setMediaUrl(e.target.value)}
                />
              ) : null}
            </div>

            <div className="flex flex-wrap items-center gap-2 pt-1">
              <Button onClick={() => void save()} disabled={saving}>
                <Save className="h-3.5 w-3.5" />
                {saving ? "Saving…" : "Save Settings"}
              </Button>
              {ok ? <span className="text-xs text-emerald-300">{ok}</span> : null}
              {error ? <span className="text-xs text-rose-300">{error}</span> : null}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

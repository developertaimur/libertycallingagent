"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, Loader2, Mic2, Upload, UserRound, Volume2 } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api, type AgentControl } from "@/lib/api";
import {
  findCatalogVoice,
  voicesByGender,
  type CatalogVoice,
  type VoiceGender,
} from "@/lib/voices";
import { cn } from "@/lib/utils";

export function VoicesView({
  onToast,
}: {
  onToast?: (msg: string) => void;
}) {
  const [tab, setTab] = useState<VoiceGender>("women");
  const [selectedId, setSelectedId] = useState("");
  const [agentName, setAgentName] = useState("Natasha");
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [previewingId, setPreviewingId] = useState<string | null>(null);
  const [cloning, setCloning] = useState(false);
  const [cloneFile, setCloneFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const objectUrlRef = useRef<string | null>(null);

  const stopPreview = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
    setPreviewingId(null);
  }, []);

  useEffect(() => () => stopPreview(), [stopPreview]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api.getAgentControl();
      const agent = (data.agent || {}) as AgentControl;
      const vid = (agent.cartesia_voice_id || "").replace(/^cartesia\./, "").split(":")[0];
      setSelectedId(vid);
      setAgentName(agent.agent_name || "Natasha");
      const known = findCatalogVoice(vid);
      if (known) setTab(known.gender);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load voices");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const list = useMemo(() => voicesByGender(tab), [tab]);

  async function playPreview(voice: CatalogVoice) {
    stopPreview();
    setPreviewingId(voice.id);
    setError("");
    try {
      const url = api.previewVoiceUrl(
        voice.id,
        `Hey, it's ${voice.name} — just calling to see if now is an okay time to chat for a minute.`,
      );
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        const detail =
          (typeof data?.detail === "string" && data.detail) ||
          `Preview failed (${res.status})`;
        throw new Error(detail);
      }
      const blob = await res.blob();
      const objectUrl = URL.createObjectURL(blob);
      objectUrlRef.current = objectUrl;
      const audio = new Audio(objectUrl);
      audioRef.current = audio;
      audio.onended = () => {
        stopPreview();
      };
      audio.onerror = () => {
        setError("Could not play preview audio");
        stopPreview();
      };
      await audio.play();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Preview failed");
      stopPreview();
    }
  }

  async function selectVoice(voice: CatalogVoice) {
    // Hear first, then save as active agent voice
    void playPreview(voice);
    setSavingId(voice.id);
    setError("");
    try {
      const data = await api.saveAgentControl({
        cartesia_voice_id: voice.id,
        tts_voice_override: "",
        tts_model: "sonic-3",
      });
      const vid = (data.agent?.cartesia_voice_id || voice.id)
        .replace(/^cartesia\./, "")
        .split(":")[0];
      setSelectedId(vid);
      onToast?.(`${voice.name} selected — playing preview`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save voice");
    } finally {
      setSavingId(null);
    }
  }

  async function onCloneUpload() {
    if (!cloneFile) {
      setError("Choose a recording first");
      return;
    }
    setCloning(true);
    setError("");
    try {
      const data = await api.cloneAgentVoice(cloneFile, {
        name: `${agentName} Personal`,
        language: "en",
      });
      const vid = (data.voice_id || "").trim();
      setSelectedId(vid);
      setCloneFile(null);
      if (fileRef.current) fileRef.current.value = "";
      onToast?.(data.message || "Personal voice cloned");
      if (vid) {
        void playPreview({
          id: vid,
          name: "Personal",
          gender: "women",
          blurb: "",
        });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Voice clone failed");
    } finally {
      setCloning(false);
    }
  }

  const selectedMeta = findCatalogVoice(selectedId);

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-slate-50">Voices</h2>
        <p className="mt-1 max-w-2xl text-sm text-slate-400">
          Tap a woman or man voice to hear a preview and set it for the next call.
        </p>
      </div>

      {error ? (
        <p className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          {error}
        </p>
      ) : null}

      <p className="rounded-xl border border-slate-800 bg-slate-900/50 px-4 py-3 text-sm text-slate-300">
        Active:{" "}
        <span className="font-medium text-emerald-300">
          {loading
            ? "…"
            : selectedMeta
              ? `${selectedMeta.name} (${selectedMeta.gender === "women" ? "Woman" : "Man"})`
              : selectedId
                ? "Personal / custom voice"
                : "None selected"}
        </span>
      </p>

      <div className="flex gap-2">
        {(
          [
            ["women", "Women"],
            ["men", "Men"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={cn(
              "rounded-lg px-4 py-2 text-sm font-medium transition",
              tab === id
                ? "bg-emerald-500/20 text-emerald-200 ring-1 ring-emerald-500/40"
                : "bg-slate-900 text-slate-400 ring-1 ring-slate-800 hover:text-slate-200",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {list.map((voice) => {
          const active = selectedId === voice.id;
          const busy = savingId === voice.id;
          const previewing = previewingId === voice.id;
          return (
            <button
              key={voice.id}
              type="button"
              disabled={loading || busy}
              onClick={() => void selectVoice(voice)}
              className={cn(
                "rounded-2xl border p-4 text-left transition",
                active
                  ? "border-emerald-500/50 bg-emerald-500/10 ring-1 ring-emerald-500/30"
                  : "border-slate-800 bg-slate-900/60 hover:border-slate-700 hover:bg-slate-900",
                (loading || busy) && "opacity-70",
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "flex h-9 w-9 items-center justify-center rounded-full",
                      previewing
                        ? "bg-emerald-500/20 text-emerald-300"
                        : "bg-slate-800 text-slate-300",
                    )}
                  >
                    {previewing ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Volume2 className="h-4 w-4" />
                    )}
                  </span>
                  <div>
                    <p className="text-sm font-semibold text-slate-50">{voice.name}</p>
                    <p className="text-[11px] uppercase tracking-wider text-slate-500">
                      {voice.gender === "women" ? "Woman" : "Man"}
                    </p>
                  </div>
                </div>
                {active ? (
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500/20 text-emerald-300">
                    <Check className="h-3.5 w-3.5" />
                  </span>
                ) : (
                  <UserRound className="h-4 w-4 text-slate-600" />
                )}
              </div>
              <p className="mt-3 text-xs leading-relaxed text-slate-400">{voice.blurb}</p>
              <p className="mt-3 text-[11px] font-medium text-slate-500">
                {previewing
                  ? "Playing preview…"
                  : busy
                    ? "Saving…"
                    : active
                      ? "Selected — tap to hear again"
                      : "Tap to hear & select"}
              </p>
            </button>
          );
        })}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Mic2 className="h-4 w-4 text-emerald-400" />
            Personal voice clone
          </CardTitle>
          <CardDescription>
            Upload 10–60s of clean speech to clone your own voice. Catalog voices above
            are the most reliable on live SignalWire calls.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <input
            ref={fileRef}
            type="file"
            accept="audio/*,.wav,.mp3,.ogg,.flac,.webm,.m4a"
            disabled={loading || cloning}
            className="block w-full text-xs text-slate-400 file:mr-3 file:rounded-lg file:border-0 file:bg-slate-800 file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-slate-100 hover:file:bg-slate-700"
            onChange={(e) => setCloneFile(e.target.files?.[0] || null)}
          />
          {cloneFile ? (
            <p className="text-[11px] text-slate-400">
              Selected: <span className="text-slate-200">{cloneFile.name}</span>
            </p>
          ) : null}
          <Button
            type="button"
            disabled={loading || cloning || !cloneFile}
            onClick={() => void onCloneUpload()}
          >
            <Upload className="h-4 w-4" />
            {cloning ? "Cloning…" : "Clone & use this voice"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

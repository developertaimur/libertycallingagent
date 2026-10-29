"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { BookOpen, RefreshCw, Save, UserRound, PhoneForwarded } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api, type AgentControl } from "@/lib/api";

const EMPTY_AGENT: AgentControl = {
  agent_name: "Natasha",
  company_name: "Liberty Weblab",
  cartesia_voice_id: "",
  tts_model: "sonic-3",
  tts_voice_override: "",
  persona_notes: "",
  greeting_with_name: "",
  greeting_anonymous: "",
  human_transfer_website: "",
  human_transfer_marketing: "",
  human_transfer_number: "",
};

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block space-y-1.5">
      <span className="text-xs font-medium text-slate-300">{label}</span>
      {children}
      {hint ? <span className="block text-[11px] text-slate-500">{hint}</span> : null}
    </label>
  );
}

const inputClass =
  "w-full rounded-lg border border-slate-800 bg-slate-950/80 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/50 disabled:opacity-60";

export function KnowledgeView({
  onToast,
}: {
  onToast?: (msg: string) => void;
}) {
  const [knowledge, setKnowledge] = useState("");
  const [agent, setAgent] = useState<AgentControl>(EMPTY_AGENT);
  const [path, setPath] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api.getAgentControl();
      setKnowledge(data.knowledge || data.content || "");
      setPath(data.knowledge_path || data.path || "");
      setAgent({ ...EMPTY_AGENT, ...(data.agent || {}) });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load agent controls");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function patchAgent(partial: Partial<AgentControl>) {
    setAgent((prev) => ({ ...prev, ...partial }));
  }

  async function onSave() {
    setSaving(true);
    setError("");
    try {
      const data = await api.saveAgentControl({
        knowledge,
        agent_name: agent.agent_name,
        company_name: agent.company_name,
        persona_notes: agent.persona_notes,
        greeting_with_name: agent.greeting_with_name,
        greeting_anonymous: agent.greeting_anonymous,
        human_transfer_website: agent.human_transfer_website,
        human_transfer_marketing: agent.human_transfer_marketing,
        human_transfer_number: agent.human_transfer_number,
      });
      setKnowledge(data.knowledge || data.content || knowledge);
      setAgent({ ...EMPTY_AGENT, ...(data.agent || agent) });
      onToast?.(data.message || "Knowledge saved");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-50">Knowledge</h2>
          <p className="mt-1 max-w-2xl text-sm text-slate-400">
            Persona, greetings, text knowledge, and expert transfer numbers. Choose man
            or woman voices under Voices.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            disabled={loading || saving}
            onClick={() => void load()}
          >
            <RefreshCw className="h-4 w-4" />
            Reload
          </Button>
          <Button
            disabled={loading || saving || !knowledge.trim()}
            onClick={() => void onSave()}
          >
            <Save className="h-4 w-4" />
            {saving ? "Saving…" : "Save all"}
          </Button>
        </div>
      </div>

      {error ? (
        <p className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          {error}
        </p>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <UserRound className="h-4 w-4 text-emerald-400" />
            Persona
          </CardTitle>
          <CardDescription>Name, company, and how the agent speaks in character</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Agent name">
              <input
                className={inputClass}
                value={agent.agent_name || ""}
                disabled={loading}
                onChange={(e) => patchAgent({ agent_name: e.target.value })}
                placeholder="Natasha"
              />
            </Field>
            <Field label="Company">
              <input
                className={inputClass}
                value={agent.company_name || ""}
                disabled={loading}
                onChange={(e) => patchAgent({ company_name: e.target.value })}
                placeholder="Liberty Weblab"
              />
            </Field>
          </div>
          <Field
            label="Persona notes"
            hint="Style, tone, and hard rules injected into the system prompt"
          >
            <textarea
              className={`${inputClass} min-h-[100px] resize-y`}
              value={agent.persona_notes || ""}
              disabled={loading}
              onChange={(e) => patchAgent({ persona_notes: e.target.value })}
            />
          </Field>
          <Field
            label="Greeting (with lead name)"
            hint="Placeholders: {name} {agent} {company}"
          >
            <input
              className={inputClass}
              value={agent.greeting_with_name || ""}
              disabled={loading}
              onChange={(e) => patchAgent({ greeting_with_name: e.target.value })}
            />
          </Field>
          <Field label="Greeting (no name)" hint="Placeholders: {agent} {company}">
            <input
              className={inputClass}
              value={agent.greeting_anonymous || ""}
              disabled={loading}
              onChange={(e) => patchAgent({ greeting_anonymous: e.target.value })}
            />
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <PhoneForwarded className="h-4 w-4 text-emerald-400" />
            Expert transfer numbers
          </CardTitle>
          <CardDescription>
            Optional overrides for live transfer. Leave blank to use .env HUMAN_TRANSFER_*.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Website expert">
              <input
                className={`${inputClass} font-mono text-xs`}
                value={agent.human_transfer_website || ""}
                disabled={loading}
                onChange={(e) => patchAgent({ human_transfer_website: e.target.value })}
                placeholder="+1…"
              />
            </Field>
            <Field label="Marketing expert">
              <input
                className={`${inputClass} font-mono text-xs`}
                value={agent.human_transfer_marketing || ""}
                disabled={loading}
                onChange={(e) => patchAgent({ human_transfer_marketing: e.target.value })}
                placeholder="+1…"
              />
            </Field>
            <Field label="Default / general">
              <input
                className={`${inputClass} font-mono text-xs`}
                value={agent.human_transfer_number || ""}
                disabled={loading}
                onChange={(e) => patchAgent({ human_transfer_number: e.target.value })}
                placeholder="+1…"
              />
            </Field>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BookOpen className="h-4 w-4 text-emerald-400" />
            Text knowledge base
          </CardTitle>
          <CardDescription>
            {path ? (
              <span className="font-mono text-[11px] text-slate-500">{path}</span>
            ) : (
              "Services, FAQs, and out-of-scope rules"
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <textarea
            value={knowledge}
            onChange={(e) => setKnowledge(e.target.value)}
            disabled={loading}
            spellCheck={false}
            className="min-h-[360px] w-full resize-y rounded-xl border border-slate-800 bg-slate-950/80 px-3 py-3 font-mono text-xs leading-relaxed text-slate-200 placeholder:text-slate-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/50 disabled:opacity-60"
            placeholder={loading ? "Loading…" : "Paste company services, FAQs, and guardrails…"}
          />
        </CardContent>
      </Card>
    </div>
  );
}

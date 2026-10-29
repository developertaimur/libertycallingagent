import type { ActiveCall, CampaignStatus, LeadsResponse } from "./types";

export type AgentControl = {
  agent_name?: string;
  company_name?: string;
  cartesia_voice_id?: string;
  tts_model?: string;
  tts_voice_override?: string;
  persona_notes?: string;
  greeting_with_name?: string;
  greeting_anonymous?: string;
  human_transfer_website?: string;
  human_transfer_marketing?: string;
  human_transfer_number?: string;
};

export type OutreachSettings = {
  enable_unanswered_sms: boolean;
  enable_unanswered_voicenote: boolean;
  sms_template_content: string;
  voice_note_type: "tts" | "audio" | string;
  voice_media_url?: string;
  voice_tts_text?: string;
  delay_seconds?: number;
};

export type OutreachSettingsResponse = {
  ok: boolean;
  settings: OutreachSettings;
  analytics?: {
    followup_notifications_sent?: number;
    sms_sent?: number;
    voicenotes_sent?: number;
  };
  defaults?: { sms_template_content?: string };
};

const API_BASE =
  (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(
    /\/$/,
    "",
  );

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const url = `${API_BASE}${path}`;
  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      headers: {
        ...(init?.body instanceof FormData
          ? {}
          : { "Content-Type": "application/json" }),
        ...(init?.headers || {}),
      },
      cache: "no-store",
    });
  } catch (e) {
    throw new Error(
      e instanceof Error
        ? `Network error calling ${url}: ${e.message}`
        : `Network error calling ${url}`,
    );
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data?.detail;
    const detail =
      (typeof d === "string" && d) ||
      (d && typeof d === "object" && typeof d.message === "string" && d.message) ||
      (d && typeof d === "object" && typeof d.error === "string" && d.error) ||
      (typeof data?.error === "string" && data.error) ||
      (typeof data?.message === "string" && data.message) ||
      data?.detail?.[0]?.msg ||
      (res.status === 404
        ? `Not Found (404) — ${url}. Restart FastAPI so /api/messaging routes are loaded.`
        : null) ||
      res.statusText ||
      "Request failed";
    throw new Error(detail);
  }
  return data as T;
}

export const api = {
  baseUrl: API_BASE,

  listLeads: () => request<LeadsResponse>("/api/leads/list"),

  syncSheet: (spreadsheet_url: string) =>
    request<LeadsResponse>("/api/leads/sync", {
      method: "POST",
      body: JSON.stringify({ spreadsheet_url }),
    }),

  uploadCsv: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<LeadsResponse & { written?: number; sheets_error?: string }>(
      "/api/leads/upload",
      { method: "POST", body: form },
    );
  },

  startCampaign: (max_calls?: number | null) =>
    request<CampaignStatus>("/api/dialer/start-campaign", {
      method: "POST",
      body: JSON.stringify({ max_calls: max_calls ?? null }),
    }),

  pauseCampaign: () =>
    request<CampaignStatus>("/api/dialer/pause-campaign", {
      method: "POST",
      body: JSON.stringify({}),
    }),

  campaignStatus: () =>
    request<CampaignStatus>("/api/dialer/campaign-status"),

  activeCall: () => request<ActiveCall>("/api/dialer/active-call"),

  makeCall: (payload: {
    phone?: string;
    to_number?: string;
    lead_name?: string;
    lead_id?: string;
    service?: string;
    service_type?: string;
  }) =>
    request<{
      status: string;
      call_sid: string;
      phone?: string;
      lead_name?: string;
    }>("/api/dialer/make-call", {
      method: "POST",
      body: JSON.stringify({
        phone: payload.phone || payload.to_number || "",
        to_number: payload.to_number || payload.phone || "",
        lead_name: payload.lead_name || "",
        lead_id: payload.lead_id || "",
        service: payload.service || payload.service_type || "",
        service_type: payload.service_type || payload.service || "",
      }),
    }),

  endCall: (call_sid: string) =>
    request<{ status: string; call_sid: string }>("/api/dialer/end-call", {
      method: "POST",
      body: JSON.stringify({ call_sid }),
    }),

  getOutreachSettings: () =>
    request<OutreachSettingsResponse>("/api/settings/outreach"),

  saveOutreachSettings: (settings: Partial<OutreachSettings>) =>
    request<OutreachSettingsResponse>("/api/settings/outreach", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),

  getAnalytics: () =>
    request<{
      ok: boolean;
      followup_notifications_sent?: number;
      sms_sent?: number;
      voicenotes_sent?: number;
    }>("/api/settings/analytics"),

  getKnowledge: () =>
    request<{ ok: boolean; content: string; path?: string }>(
      "/api/settings/knowledge",
    ),

  saveKnowledge: (content: string) =>
    request<{
      ok: boolean;
      content: string;
      path?: string;
      message?: string;
    }>("/api/settings/knowledge", {
      method: "PUT",
      body: JSON.stringify({ content }),
    }),

  getAgentControl: () =>
    request<{
      ok: boolean;
      knowledge: string;
      content?: string;
      knowledge_path?: string;
      path?: string;
      agent: AgentControl;
      resolved_tts_voice?: string;
    }>("/api/settings/agent"),

  saveAgentControl: (payload: Partial<AgentControl> & { knowledge?: string }) =>
    request<{
      ok: boolean;
      knowledge: string;
      content?: string;
      knowledge_path?: string;
      path?: string;
      agent: AgentControl;
      resolved_tts_voice?: string;
      message?: string;
    }>("/api/settings/agent", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  previewVoiceUrl: (voiceId: string, text = "") => {
    const q = new URLSearchParams({ voice_id: voiceId });
    if (text.trim()) q.set("text", text.trim());
    return `${API_BASE}/api/settings/voices/preview?${q.toString()}`;
  },

  cloneAgentVoice: async (file: File, opts?: { name?: string; language?: string }) => {
    const form = new FormData();
    form.append("file", file);
    if (opts?.name) form.append("name", opts.name);
    form.append("language", opts?.language || "en");
    form.append("apply", "true");
    return request<{
      ok: boolean;
      voice_id: string;
      cloned_name?: string;
      applied?: boolean;
      agent: AgentControl;
      resolved_tts_voice?: string;
      message?: string;
    }>("/api/settings/agent/clone-voice", {
      method: "POST",
      body: form,
    });
  },

  voiceMetrics: (limit = 20) =>
    request<{
      live: Array<Record<string, unknown>>;
      recent: Array<Record<string, unknown>>;
      summary: {
        calls?: number;
        avg_stt_latency_ms?: number;
        avg_tts_ttfb_ms?: number;
        total_cost_usd?: number;
      };
    }>(`/api/voice/metrics?limit=${limit}`),

  pendingTransfers: () =>
    request<{
      ok: boolean;
      ringing_count: number;
      ringing: Array<Record<string, unknown>>;
      transfers: Array<Record<string, unknown>>;
    }>("/api/transfer/pending"),

  requestTransfer: (payload: {
    call_sid?: string;
    lead_id?: string;
    lead_name?: string;
    phone?: string;
    service_type?: string;
    expert_type?: string;
    reason?: string;
    ai_summary?: string;
    /** Optional E.164 — rings this device instead of default expert queue */
    destination?: string;
    source?: string;
  }) =>
    request<{ ok: boolean; transfer: Record<string, unknown>; message?: string }>(
      "/api/transfer/request",
      { method: "POST", body: JSON.stringify(payload) },
    ),

  claimTransfer: (transferId: string, agent_name = "Sales Agent") =>
    request<{
      ok: boolean;
      transfer: Record<string, unknown>;
      ai_summary?: string;
      bridge?: {
        expert_number?: string;
        expert_label?: string;
        expert_type?: string;
        instruction?: string;
      };
    }>(`/api/transfer/${encodeURIComponent(transferId)}/claim`, {
      method: "POST",
      body: JSON.stringify({ agent_name, bridge: true }),
    }),

  listSmsReplies: (limit = 50) =>
    request<{
      ok: boolean;
      replies: Array<{
        from: string;
        to?: string;
        body: string;
        message_sid?: string;
        received_at?: string;
      }>;
      count: number;
    }>(`/api/messaging/replies?limit=${limit}`),

  listFollowupLog: (limit = 50) =>
    request<{
      ok: boolean;
      followups: Array<{
        phone?: string;
        lead_id?: string;
        recipient_name?: string;
        name?: string;
        sms_body?: string;
        voice_note_script_or_url?: string;
        followup_sent_time?: string;
        sms_sid?: string | null;
        voice_sid?: string | null;
        sms_delivery_status?: string;
        voice_delivery_status?: string;
        lead_status?: string;
        dispatch_source?: string;
      }>;
      sms?: Array<{
        recipient_name?: string;
        phone?: string;
        sent_sms_content?: string;
        delivery_status?: string;
        followup_sent_time?: string;
        sms_sid?: string | null;
        dispatch_source?: string;
        lead_id?: string;
      }>;
      voice_notes?: Array<{
        recipient_name?: string;
        phone?: string;
        voice_note_script_or_url?: string;
        status?: string;
        followup_sent_time?: string;
        voice_sid?: string | null;
        playable?: boolean;
        dispatch_source?: string;
        lead_id?: string;
      }>;
      replies?: Array<{
        from: string;
        to?: string;
        body: string;
        message_sid?: string;
        received_at?: string;
      }>;
      count: number;
      sms_count?: number;
      voice_count?: number;
      replies_count?: number;
    }>(`/api/messaging/followup-log?limit=${limit}`),

  previewSms: (payload: {
    lead_id?: string;
    phone?: string;
    name?: string;
    lead_name?: string;
    message?: string;
    message_text?: string;
  }) =>
    request<{
      ok: boolean;
      message_text: string;
      message?: string;
      recipient_name?: string;
      template?: string;
    }>("/api/messaging/preview-sms", {
      method: "POST",
      body: JSON.stringify({
        lead_id: payload.lead_id || "",
        phone: payload.phone || "",
        lead_name: payload.lead_name || payload.name || "",
        name: payload.name || payload.lead_name || "",
        message: payload.message || payload.message_text || "",
      }),
    }),

  sendManualSms: (payload: {
    lead_id?: string;
    phone?: string;
    lead_name?: string;
    message?: string;
    message_text?: string;
  }) =>
    request<{
      status?: string;
      ok: boolean;
      message_sid?: string;
      sms_sid?: string;
      sms_body?: string;
      phone?: string;
      dispatch_source?: string;
    }>("/api/messaging/send-manual-sms", {
      method: "POST",
      body: JSON.stringify({
        phone: payload.phone || "",
        lead_name: payload.lead_name || "",
        lead_id: payload.lead_id || "",
        message: payload.message || payload.message_text || "",
      }),
    }),

  sendManualVoicenote: (payload: {
    lead_id?: string;
    phone?: string;
    lead_name?: string;
    say_text?: string;
  }) =>
    request<{
      status?: string;
      ok: boolean;
      call_sid?: string;
      voice_sid?: string;
      voice_note_script_or_url?: string;
      phone?: string;
      dispatch_source?: string;
    }>("/api/messaging/send-manual-voicenote", {
      method: "POST",
      body: JSON.stringify({
        phone: payload.phone || "",
        lead_name: payload.lead_name || "",
        lead_id: payload.lead_id || "",
        say_text: payload.say_text || "",
      }),
    }),
};

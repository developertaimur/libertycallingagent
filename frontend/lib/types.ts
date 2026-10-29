export type Lead = {
  lead_id: string;
  name: string;
  phone: string;
  service_type: string;
  status: string;
  call_sid?: string;
  call_received?: string;
  interest_level?: string;
  meeting_booked?: boolean;
  meeting_datetime?: string;
  meeting_status?: string;
  recording_url?: string;
  summary?: string;
  business_name?: string;
  location?: string;
  website_url?: string;
  pain_point?: string;
  preferred_email?: string;
  caller_intent?: string;
  sent_sms_content?: string;
  voice_note_script_url?: string;
  customer_reply?: string;
  followup_sent_time?: string;
  row_number?: number | null;
};

export type Metrics = {
  total_leads: number;
  pending_leads: number;
  calls_completed: number;
  meetings_booked: number;
  followups_triggered: number;
  followup_notifications_sent?: number;
};

export type LeadsResponse = {
  ok: boolean;
  source?: string;
  spreadsheet_id?: string;
  error?: string | null;
  metrics: Metrics;
  leads: Lead[];
  count: number;
};

export type ActiveCall = {
  ok?: boolean;
  active: boolean;
  call_sid?: string;
  lead_id?: string;
  lead_name?: string;
  phone?: string;
  service_type?: string;
  status?: string;
  duration_seconds?: number;
  /** Live handoff notes — same text experts see on Take over */
  conversation_summary?: string;
  transfer_ringing?: boolean;
  expert_label?: string;
};

export type CampaignStatus = {
  ok?: boolean;
  running: boolean;
  paused: boolean;
  started_at?: number | null;
  calls_placed?: number;
  last_error?: string;
  active_call?: ActiveCall | null;
};

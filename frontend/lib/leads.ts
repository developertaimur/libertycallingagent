import type { Lead } from "./types";

/** Loose lead row from API / Sheets / CSV with alternate key names. */
export type LeadLike = Lead & Record<string, unknown>;

function pickString(row: LeadLike, ...keys: string[]): string {
  for (const key of keys) {
    const val = row[key];
    if (val !== undefined && val !== null && String(val).trim()) {
      return String(val).trim();
    }
  }
  return "";
}

export function leadName(lead: LeadLike): string {
  return pickString(lead, "name", "lead_name", "Lead Name", "full_name", "contact");
}

export function leadPhone(lead: LeadLike): string {
  return pickString(lead, "phone", "to_number", "Phone", "phone_number", "mobile");
}

export function leadService(lead: LeadLike): string {
  return pickString(lead, "service", "service_type", "Service", "product");
}

export function leadStatus(lead: LeadLike): string {
  return pickString(lead, "status", "Status", "lead_status") || "Pending";
}

export function leadId(lead: LeadLike, index = 0): string {
  return (
    pickString(lead, "lead_id", "id", "Lead ID") ||
    leadPhone(lead) ||
    (lead.row_number != null ? `row-${lead.row_number}` : `lead-${index}`)
  );
}

export function formatStatusLabel(status: string): string {
  const raw = (status || "Pending").trim();
  if (!raw) return "Pending";
  return raw
    .replace(/[_-]+/g, " ")
    .split(/\s+/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");
}

export function displayOrBlank(value: string): string {
  return (value || "").trim();
}

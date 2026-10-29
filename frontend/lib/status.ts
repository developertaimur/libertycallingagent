export type BadgeTone = "green" | "blue" | "yellow" | "red" | "slate";

export function statusTone(status: string): BadgeTone {
  const s = (status || "").toLowerCase().replace(/\s+/g, "_");
  if (
    [
      "completed",
      "answered",
      "done",
      "not_interested",
      "not-interested",
    ].includes(s)
  ) {
    return "green";
  }
  if (
    ["meeting_booked", "booked", "transferred", "transfer", "calling"].includes(
      s,
    ) ||
    s.includes("meeting")
  ) {
    return "blue";
  }
  if (
    [
      "no-answer",
      "no_answer",
      "unanswered",
      "pending",
      "machine_start",
      "follow_up",
      "followup",
    ].includes(s) ||
    s.includes("sms")
  ) {
    return "yellow";
  }
  if (["busy", "failed", "canceled", "cancelled", "error"].includes(s)) {
    return "red";
  }
  return "slate";
}

/** Soft glass pills — slate / emerald / rose (+ cyan & amber accents). */
export const toneClass: Record<BadgeTone, string> = {
  green: "bg-emerald-500/10 text-emerald-300/95 ring-emerald-500/20",
  blue: "bg-cyan-500/10 text-cyan-300/95 ring-cyan-500/20",
  yellow: "bg-amber-500/10 text-amber-200/95 ring-amber-500/20",
  red: "bg-rose-500/10 text-rose-300/95 ring-rose-500/20",
  slate: "bg-slate-500/10 text-slate-300 ring-slate-500/20",
};

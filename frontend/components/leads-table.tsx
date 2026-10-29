"use client";

import { useMemo, useState } from "react";
import { FileText, Pause, Play } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SummaryModal } from "@/components/summary-modal";
import type { Lead } from "@/lib/types";
import {
  displayOrBlank,
  formatStatusLabel,
  leadId,
  leadName,
  leadPhone,
  leadService,
  leadStatus,
  type LeadLike,
} from "@/lib/leads";
import { statusTone } from "@/lib/status";

function yesNo(value?: string | boolean) {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  const v = (value || "").toLowerCase();
  if (["yes", "true", "1", "y"].includes(v)) return "Yes";
  if (!v) return "";
  return "No";
}

export function LeadsTable({ leads }: { leads: Lead[] }) {
  const [selected, setSelected] = useState<Lead | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);

  const sorted = useMemo(() => {
    return [...leads].sort((a, b) =>
      leadName(a as LeadLike).localeCompare(leadName(b as LeadLike)),
    );
  }, [leads]);

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>Lead Tracking & Results</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto px-0 pb-2 sm:px-2">
          <table className="w-full min-w-[960px] border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-[11px] uppercase tracking-wider text-slate-500">
                <th className="px-4 py-3 font-medium">Lead Name</th>
                <th className="px-4 py-3 font-medium">Phone</th>
                <th className="px-4 py-3 font-medium">Service</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Call Received?</th>
                <th className="px-4 py-3 font-medium">Interest</th>
                <th className="px-4 py-3 font-medium">Meeting Booked?</th>
                <th className="px-4 py-3 font-medium">Action</th>
              </tr>
            </thead>
            <tbody>
              {sorted.length === 0 ? (
                <tr>
                  <td
                    colSpan={8}
                    className="px-4 py-10 text-center text-slate-500"
                  >
                    No leads loaded yet — sync a Sheet or upload a CSV.
                  </td>
                </tr>
              ) : (
                sorted.map((lead, index) => {
                  const row = lead as LeadLike;
                  const id = leadId(row, index);
                  const name = displayOrBlank(leadName(row));
                  const phone = displayOrBlank(leadPhone(row));
                  const service = displayOrBlank(leadService(row));
                  const status = leadStatus(row);
                  const tone = lead.meeting_booked ? "blue" : statusTone(status);
                  const interest = displayOrBlank(lead.interest_level || "");
                  const received = yesNo(lead.call_received);

                  return (
                    <tr
                      key={id}
                      className="border-b border-slate-800/80 hover:bg-slate-800/25"
                    >
                      <td className="px-4 py-3 align-middle font-medium text-slate-100">
                        {name}
                      </td>
                      <td className="px-4 py-3 align-middle font-mono text-xs text-slate-400">
                        {phone}
                      </td>
                      <td className="px-4 py-3 align-middle text-slate-300">
                        {service}
                      </td>
                      <td className="px-4 py-3 align-middle">
                        <Badge tone={tone}>{formatStatusLabel(status)}</Badge>
                      </td>
                      <td className="px-4 py-3 align-middle text-slate-300">
                        {received}
                      </td>
                      <td className="px-4 py-3 align-middle text-slate-300">
                        {interest ? formatStatusLabel(interest) : ""}
                      </td>
                      <td className="px-4 py-3 align-middle">
                        {lead.meeting_booked ? (
                          <Badge tone="blue">Booked</Badge>
                        ) : (
                          <span className="text-slate-500">No</span>
                        )}
                      </td>
                      <td className="px-4 py-3 align-middle">
                        <div className="flex flex-wrap items-center gap-2">
                          {lead.recording_url ? (
                            <Button
                              size="icon"
                              variant="secondary"
                              className="h-8 w-8 shrink-0"
                              title={
                                playing === id ? "Pause recording" : "Play recording"
                              }
                              aria-label={
                                playing === id ? "Pause recording" : "Play recording"
                              }
                              onClick={() =>
                                setPlaying((p) => (p === id ? null : id))
                              }
                            >
                              {playing === id ? (
                                <Pause className="h-3.5 w-3.5" />
                              ) : (
                                <Play className="h-3.5 w-3.5 fill-current" />
                              )}
                            </Button>
                          ) : null}
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setSelected(lead)}
                          >
                            <FileText className="h-3.5 w-3.5" />
                            View Summary
                          </Button>
                        </div>
                        {playing === id && lead.recording_url ? (
                          <audio
                            className="mt-2 w-full max-w-xs"
                            controls
                            autoPlay
                            src={lead.recording_url}
                            onEnded={() => setPlaying(null)}
                          />
                        ) : null}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <SummaryModal
        lead={selected}
        open={Boolean(selected)}
        onClose={() => setSelected(null)}
      />
    </>
  );
}

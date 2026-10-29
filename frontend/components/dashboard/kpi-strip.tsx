"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Sparkline } from "@/components/dashboard/sparkline";
import { cn } from "@/lib/utils";

export type DashboardMetrics = {
  total_leads: number;
  active_campaigns: number;
  calls_dialed_today: number;
  answer_rate: number;
  transfers: number;
  sms_vm_sent: number;
};

const CELLS: {
  key: keyof DashboardMetrics;
  label: string;
  format?: (n: number) => string;
  color: string;
}[] = [
  { key: "total_leads", label: "Total Leads", color: "#34d399" },
  { key: "active_campaigns", label: "Active Campaigns", color: "#22d3ee" },
  { key: "calls_dialed_today", label: "Calls Dialed Today", color: "#a78bfa" },
  {
    key: "answer_rate",
    label: "Answer Rate",
    format: (n) => `${Math.round(n)}%`,
    color: "#34d399",
  },
  { key: "transfers", label: "Transfers to Human", color: "#60a5fa" },
  {
    key: "sms_vm_sent",
    label: "Follow-up Delivered",
    color: "#fbbf24",
  },
];

export function KpiStrip({
  metrics,
  className,
}: {
  metrics: DashboardMetrics;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid gap-3 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-6",
        className,
      )}
    >
      {CELLS.map(({ key, label, format, color }) => {
        const value = metrics[key] ?? 0;
        return (
          <Card key={key} className="overflow-hidden">
            <CardContent className="p-4">
              <p className="text-[11px] font-medium leading-snug text-slate-400">
                {label}
              </p>
              <p className="mt-1.5 text-2xl font-semibold tabular-nums tracking-tight text-slate-50">
                {format ? format(value) : value.toLocaleString()}
              </p>
              <Sparkline seed={value + key.length * 11} color={color} />
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

"use client";

import type { ElementType } from "react";
import {
  CalendarCheck2,
  MessageSquareShare,
  PhoneCall,
  Users,
  Hourglass,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import type { Metrics } from "@/lib/types";
import { cn } from "@/lib/utils";

const items: {
  key: keyof Metrics;
  label: string;
  icon: ElementType;
  highlight?: boolean;
}[] = [
  { key: "total_leads", label: "Total Leads Loaded", icon: Users },
  { key: "calls_completed", label: "Calls Completed", icon: PhoneCall },
  {
    key: "meetings_booked",
    label: "Meetings Booked",
    icon: CalendarCheck2,
    highlight: true,
  },
  {
    key: "followups_triggered",
    label: "Follow-up SMS / VM",
    icon: MessageSquareShare,
  },
  { key: "pending_leads", label: "Pending Leads", icon: Hourglass },
];

export function KpiCards({ metrics }: { metrics: Metrics }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
      {items.map(({ key, label, icon: Icon, highlight }) => (
        <Card
          key={key}
          className={cn(
            highlight &&
              "border-emerald-500/40 bg-emerald-500/5 shadow-[0_0_32px_-16px_rgba(16,185,129,0.8)]",
          )}
        >
          <CardContent className="flex items-start justify-between gap-3 pt-5">
            <div>
              <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
                {label}
              </p>
              <p
                className={cn(
                  "mt-2 text-3xl font-bold tabular-nums tracking-tight",
                  highlight ? "text-emerald-300" : "text-slate-50",
                )}
              >
                {metrics[key] ?? 0}
              </p>
            </div>
            <div
              className={cn(
                "rounded-xl p-2.5 ring-1",
                highlight
                  ? "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30"
                  : "bg-slate-800 text-cyan-300 ring-slate-700",
              )}
            >
              <Icon className="h-5 w-5" />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

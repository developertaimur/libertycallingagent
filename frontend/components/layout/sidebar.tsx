"use client";

import {
  LayoutDashboard,
  Megaphone,
  Users,
  PhoneCall,
  MessageSquareText,
  BookOpen,
  AudioLines,
  Radio,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "campaigns", label: "Campaigns", icon: Megaphone },
  { id: "leads", label: "Leads (CSV / Sheets)", icon: Users },
  { id: "logs", label: "Call Logs & Records", icon: PhoneCall },
  { id: "outreach", label: "SMS & Voice Notes", icon: MessageSquareText },
  { id: "knowledge", label: "Knowledge", icon: BookOpen },
  { id: "voices", label: "Voices", icon: AudioLines },
] as const;

export type NavId = (typeof NAV)[number]["id"];

export function Sidebar({
  active = "dashboard",
  onNavigate,
}: {
  active?: NavId;
  onNavigate?: (id: NavId) => void;
}) {
  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-slate-800 bg-slate-950/90">
      <div className="flex items-center gap-2.5 border-b border-slate-800 px-4 py-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/30">
          <Radio className="h-4 w-4" />
        </div>
        <div className="min-w-0 leading-tight">
          <p className="truncate text-sm font-semibold text-slate-50">
            Liberty Weblab
          </p>
          <p className="text-[10px] font-medium uppercase tracking-wider text-slate-500">
            DialerAI
          </p>
        </div>
      </div>

      <nav className="flex flex-1 flex-col gap-0.5 p-2">
        {NAV.map(({ id, label, icon: Icon }) => {
          const isActive = active === id;
          return (
            <button
              key={id}
              type="button"
              onClick={() => onNavigate?.(id)}
              className={cn(
                "flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-sm transition",
                isActive
                  ? "bg-slate-800/90 text-slate-50 shadow-sm ring-1 ring-slate-700"
                  : "text-slate-400 hover:bg-slate-900 hover:text-slate-200",
              )}
            >
              <Icon
                className={cn(
                  "h-4 w-4 shrink-0",
                  isActive ? "text-emerald-400" : "text-slate-500",
                )}
              />
              <span className="truncate">{label}</span>
            </button>
          );
        })}
      </nav>

      <div className="border-t border-slate-800 p-3 text-[10px] text-slate-600">
        Natasha · Liberty Weblab
      </div>
    </aside>
  );
}

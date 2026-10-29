"use client";

import { FileUp, Pause, Play, Sheet } from "lucide-react";
import { Button } from "@/components/ui/button";

export function ActionToolbar({
  running,
  busy,
  onUploadCsv,
  onSyncSheets,
  onStart,
  onPause,
}: {
  running: boolean;
  busy?: boolean;
  onUploadCsv: () => void;
  onSyncSheets: () => void;
  onStart: () => void;
  onPause: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      <Button variant="secondary" size="sm" onClick={onUploadCsv} disabled={busy}>
        <FileUp className="h-3.5 w-3.5" />
        Upload CSV
      </Button>
      <Button
        variant="outline"
        size="sm"
        className="border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/10"
        onClick={onSyncSheets}
        disabled={busy}
      >
        <Sheet className="h-3.5 w-3.5" />
        Sync Google Sheets
      </Button>
      <Button
        variant="success"
        size="sm"
        disabled={busy || running}
        onClick={onStart}
      >
        <Play className="h-3.5 w-3.5" />
        Start Dialer Campaign
      </Button>
      <Button
        variant="danger"
        size="sm"
        disabled={busy || !running}
        onClick={onPause}
      >
        <Pause className="h-3.5 w-3.5" />
        Pause Calls
      </Button>
    </div>
  );
}

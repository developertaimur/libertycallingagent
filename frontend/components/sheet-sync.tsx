"use client";

import { useState } from "react";
import { Link2, RefreshCw } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

export function SheetSync({
  onSync,
  spreadsheetId,
  onUrlChange,
}: {
  onSync: (url: string) => Promise<void>;
  spreadsheetId?: string;
  onUrlChange?: (url: string) => void;
}) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleSync() {
    setError("");
    setBusy(true);
    try {
      await onSync(url.trim());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sync failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Link2 className="h-4 w-4 text-cyan-300" />
          Google Sheet Sync
        </CardTitle>
        <CardDescription>
          Paste a Sheet URL or ID, then sync leads into the dialer.
          {spreadsheetId ? (
            <span className="mt-1 block font-mono text-[11px] text-slate-500">
              Active: {spreadsheetId}
            </span>
          ) : null}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 sm:flex-row">
        <Input
          id="sheet-sync-input"
          placeholder="https://docs.google.com/spreadsheets/d/…"
          value={url}
          onChange={(e) => {
            const next = e.target.value;
            setUrl(next);
            onUrlChange?.(next);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && url.trim() && !busy) void handleSync();
          }}
        />
        <Button onClick={handleSync} disabled={busy || !url.trim()}>
          <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} />
          Sync Leads
        </Button>
      </CardContent>
      {error ? (
        <p className="px-5 pb-4 text-xs text-rose-300">{error}</p>
      ) : null}
    </Card>
  );
}

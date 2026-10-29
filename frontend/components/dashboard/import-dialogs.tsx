"use client";

import { useState } from "react";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { CsvUploader } from "@/components/csv-uploader";

export function SyncSheetsDialog({
  open,
  onClose,
  spreadsheetId,
  onSync,
}: {
  open: boolean;
  onClose: () => void;
  spreadsheetId?: string;
  onSync: (url: string) => Promise<void>;
}) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    setError("");
    setBusy(true);
    try {
      await onSync(url.trim());
      setUrl("");
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sync failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Sync Google Sheets"
      description="Paste a Sheet URL or spreadsheet ID to load leads."
    >
      {spreadsheetId ? (
        <p className="mb-3 font-mono text-[11px] text-slate-500">
          Active: {spreadsheetId}
        </p>
      ) : null}
      <div className="flex flex-col gap-2 sm:flex-row">
        <Input
          id="sheet-sync-input"
          placeholder="https://docs.google.com/spreadsheets/d/…"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && url.trim() && !busy) void submit();
          }}
        />
        <Button disabled={busy || !url.trim()} onClick={() => void submit()}>
          Sync Leads
        </Button>
      </div>
      {error ? <p className="mt-2 text-xs text-rose-300">{error}</p> : null}
    </Dialog>
  );
}

export function UploadCsvDialog({
  open,
  onClose,
  onUpload,
}: {
  open: boolean;
  onClose: () => void;
  onUpload: (file: File) => Promise<void>;
}) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Upload CSV Leads"
      description="Columns: name, phone, service_type (status optional)."
      className="max-w-xl"
    >
      <CsvUploader
        onUpload={async (file) => {
          await onUpload(file);
          onClose();
        }}
      />
    </Dialog>
  );
}

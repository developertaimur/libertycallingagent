"use client";

import { useCallback, useState } from "react";
import { FileUp, Upload } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function CsvUploader({
  onUpload,
}: {
  onUpload: (file: File) => Promise<void>;
}) {
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const handleFile = useCallback(
    async (file: File | undefined) => {
      if (!file) return;
      setError("");
      setMessage("");
      setBusy(true);
      try {
        await onUpload(file);
        setMessage(`Uploaded ${file.name}`);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Upload failed");
      } finally {
        setBusy(false);
      }
    },
    [onUpload],
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FileUp className="h-4 w-4 text-cyan-300" />
          CSV Lead Upload
        </CardTitle>
        <CardDescription>
          Drop a CSV with columns: name, phone, service_type (status optional).
        </CardDescription>
      </CardHeader>
      <CardContent>
        <label
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            void handleFile(e.dataTransfer.files?.[0]);
          }}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed px-4 py-10 text-center transition",
            dragging
              ? "border-cyan-400 bg-cyan-500/10"
              : "border-slate-700 bg-slate-950/40 hover:border-slate-500",
            busy && "opacity-60",
          )}
        >
          <Upload className="h-6 w-6 text-slate-400" />
          <span className="text-sm text-slate-300">
            {busy ? "Uploading…" : "Drag & drop CSV, or click to browse"}
          </span>
          <input
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            disabled={busy}
            onChange={(e) => void handleFile(e.target.files?.[0])}
          />
        </label>
        {message ? (
          <p className="mt-2 text-xs text-emerald-300">{message}</p>
        ) : null}
        {error ? <p className="mt-2 text-xs text-rose-300">{error}</p> : null}
      </CardContent>
    </Card>
  );
}

"use client";

import { FileSpreadsheet, Upload } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { LeadsTable } from "@/components/leads-table";
import type { Lead } from "@/lib/types";

export function LeadsView({
  leads,
  spreadsheetId,
  onUploadCsv,
  onSyncSheets,
}: {
  leads: Lead[];
  spreadsheetId: string;
  onUploadCsv: () => void;
  onSyncSheets: () => void;
}) {
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-slate-50">Leads</h2>
        <p className="mt-1 text-sm text-slate-400">
          Import CSV lists or sync Google Sheets into the dialer queue.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>CSV upload</CardTitle>
            <CardDescription>
              Columns: name, phone, service_type (optional lead_id)
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={onUploadCsv}>
              <Upload className="h-4 w-4" />
              Upload CSV
            </Button>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Google Sheets</CardTitle>
            <CardDescription>
              {spreadsheetId
                ? `Active sheet: ${spreadsheetId}`
                : "No spreadsheet linked yet"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="secondary" onClick={onSyncSheets}>
              <FileSpreadsheet className="h-4 w-4" />
              Sync Google Sheets
            </Button>
          </CardContent>
        </Card>
      </div>

      <LeadsTable leads={leads} />
    </div>
  );
}

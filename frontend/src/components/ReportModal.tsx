"use client";

import { useEffect } from "react";
import { X } from "lucide-react";

import type { ReportResponse } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { Markdown } from "@/lib/markdown";
import { ErrorBlock, LoadingBlock } from "@/components/primitives";

export function ReportModal({
  projectId,
  pillar,
  onClose,
}: {
  projectId: string;
  pillar: string | null;
  onClose: () => void;
}) {
  const open = pillar !== null;
  const { data, error, loading } = useApi<ReportResponse>(
    open ? `/api/projects/${projectId}/reports/${pillar}` : null,
    [pillar],
  );

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
    >
      <button
        type="button"
        className="absolute inset-0 bg-navy-950/40"
        aria-label="Закрыть отчёт"
        onClick={onClose}
      />
      <div className="relative flex max-h-[85vh] w-full max-w-2xl flex-col rounded-xl bg-white shadow-drawer">
        <header className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
          <h2 className="text-sm font-semibold text-slate-900">Отчёт</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100"
            aria-label="Закрыть"
          >
            <X className="h-5 w-5" aria-hidden />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {loading ? <LoadingBlock label="Формирование отчёта…" /> : null}
          {error ? <ErrorBlock message={error} /> : null}
          {data ? (
            <>
              <Markdown content={data.content} />
              <p className="mt-6 border-t border-slate-100 pt-3 text-xs text-slate-400">
                {data.generated_note}
              </p>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}

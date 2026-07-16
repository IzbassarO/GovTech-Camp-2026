"use client";

import { useEffect } from "react";
import { ExternalLink, X } from "lucide-react";

import type { FindingDetail } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { INFERENCE_LABEL } from "@/lib/ui";
import { DemoBanner, ErrorBlock, LoadingBlock, SeverityBadge } from "@/components/primitives";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{label}</p>
      <div className="mt-1 text-sm leading-relaxed text-slate-700">{children}</div>
    </div>
  );
}

export function EvidenceDrawer({
  projectId,
  findingId,
  onClose,
}: {
  projectId: string;
  findingId: string | null;
  onClose: () => void;
}) {
  const open = findingId !== null;
  const { data, error, loading } = useApi<FindingDetail>(
    open ? `/api/projects/${projectId}/findings/${findingId}` : null,
    [findingId],
  );

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true">
      <button
        type="button"
        className="absolute inset-0 bg-navy-950/40"
        aria-label="Закрыть панель"
        onClick={onClose}
      />
      <aside className="relative flex h-full w-full max-w-xl flex-col bg-white shadow-drawer">
        <header className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
          <h2 className="text-sm font-semibold text-slate-900">Детали замечания</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-700"
            aria-label="Закрыть"
          >
            <X className="h-5 w-5" aria-hidden />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {loading ? <LoadingBlock label="Загрузка деталей…" /> : null}
          {error ? <ErrorBlock message={error} /> : null}
          {data ? <DrawerBody finding={data} /> : null}
        </div>
      </aside>
    </div>
  );
}

function DrawerBody({ finding }: { finding: FindingDetail }) {
  const req = finding.requirement;
  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <SeverityBadge severity={finding.severity} />
          <span className="chip bg-navy-900 text-white">{finding.pillar_id}</span>
          <span className="chip bg-slate-100 text-slate-600">{finding.finding_type_label}</span>
        </div>
        <h3 className="text-base font-semibold leading-snug text-slate-900">{finding.title}</h3>
      </div>

      {finding.demo_warning ? <DemoBanner text={finding.demo_warning} /> : null}

      <Field label="Пояснение">{finding.explanation}</Field>

      <div className="grid grid-cols-2 gap-4">
        {finding.document_id ? (
          <Field label="Документ">
            {finding.document_type ?? finding.document_id}
          </Field>
        ) : (
          <Field label="Уровень">Пакет документов</Field>
        )}
        {finding.page_references.length > 0 ? (
          <Field label="Страницы">{finding.page_references.join(", ")}</Field>
        ) : null}
        {finding.confidence != null ? (
          <Field label="Достоверность оценки">{finding.confidence.toFixed(2)}</Field>
        ) : null}
        {finding.inference_label ? (
          <Field label="Вывод">
            {INFERENCE_LABEL[finding.inference_label] ?? finding.inference_label}
          </Field>
        ) : null}
        {finding.retrieval_score != null ? (
          <Field label="Оценка релевантности">{finding.retrieval_score.toFixed(2)}</Field>
        ) : null}
        {finding.applicability ? (
          <Field label="Применимость">{finding.applicability}</Field>
        ) : null}
      </div>

      {finding.observed_value || finding.expected_value ? (
        <div className="grid grid-cols-2 gap-4">
          {finding.observed_value ? (
            <Field label="Наблюдалось">{finding.observed_value}</Field>
          ) : null}
          {finding.expected_value ? (
            <Field label="Ожидалось">{finding.expected_value}</Field>
          ) : null}
        </div>
      ) : null}

      {req ? (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            Регуляторное требование {req.article ? `· ${req.article}` : ""}
          </p>
          <p className="mt-1 text-sm font-medium text-slate-800">{req.title}</p>
          <p className="mt-2 text-sm leading-relaxed text-slate-600">{req.requirement_text}</p>
          <p className="mt-2 text-xs text-slate-500">
            {req.document_title}
            {req.demo_only ? " · демонстрационный корпус (не право)" : ""}
          </p>
          {req.source_url ? (
            <a
              href={req.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-accent-700 hover:underline"
            >
              Источник <ExternalLink className="h-3 w-3" aria-hidden />
            </a>
          ) : null}
        </div>
      ) : null}

      {finding.quantitative?.formula ? (
        <Field label="Формула сравнения">
          <code className="rounded bg-slate-100 px-2 py-1 text-xs">
            {finding.quantitative.formula}
          </code>
        </Field>
      ) : null}

      {finding.coherence && finding.coherence.entities.length > 0 ? (
        <Field label="Связанные сущности">
          <ul className="space-y-1.5">
            {finding.coherence.entities.map((e) => (
              <li key={e.entity_id} className="flex flex-wrap items-center gap-2">
                {e.role ? (
                  <span className="chip bg-slate-100 text-slate-600">{e.role}</span>
                ) : null}
                <span className="font-medium text-slate-800">{e.label}</span>
                {e.identifiers.map((id) => (
                  <span key={id} className="chip bg-navy-900 text-white">
                    БИН {id}
                  </span>
                ))}
              </li>
            ))}
          </ul>
        </Field>
      ) : null}

      {finding.coherence && finding.coherence.conflicting_claims.length > 0 ? (
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            Противоречащие сведения по документам
          </p>
          <ul className="mt-2 space-y-2">
            {finding.coherence.conflicting_claims.map((c, i) => (
              <li key={i} className="rounded-lg border border-amber-200 bg-amber-50/50 p-3 text-sm">
                <p className="font-medium text-slate-800">«{c.raw_value}»</p>
                <p className="mt-1 text-xs text-slate-500">
                  {c.document_type ?? c.document_id} · {c.attribute}
                </p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {finding.evidence.length > 0 ? (
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            Свидетельства
          </p>
          <ul className="mt-2 space-y-2">
            {finding.evidence.map((ev, i) => (
              <li key={i} className="rounded-lg border border-slate-200 bg-white p-3 text-sm">
                {ev.quote ? (
                  <p className="italic text-slate-700">«{ev.quote}»</p>
                ) : ev.note ? (
                  <p className="text-slate-600">{ev.note}</p>
                ) : null}
                <p className="mt-1 text-xs text-slate-400">
                  {ev.document_type ?? ev.document_id ?? "пакет"}
                  {ev.page_number != null ? ` · с. ${ev.page_number}` : ""}
                </p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {finding.missing_information.length > 0 ? (
        <Field label="Чего не хватает для вывода">
          <ul className="list-inside list-disc space-y-0.5">
            {finding.missing_information.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        </Field>
      ) : null}

      {finding.limitations ? (
        <Field label="Ограничения">
          <span className="text-slate-500">{finding.limitations}</span>
        </Field>
      ) : null}

      <p className="rounded-lg bg-slate-100 px-3 py-2 text-xs leading-relaxed text-slate-500">
        {finding.review_notice}
      </p>
    </div>
  );
}

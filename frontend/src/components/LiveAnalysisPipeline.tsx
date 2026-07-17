"use client";

import {
  AlertTriangle,
  Archive,
  Ban,
  Check,
  FileText,
  Loader2,
  ShieldCheck,
  XCircle,
} from "lucide-react";

import type {
  ArchiveStatus,
  LiveDossierSectionId,
  LiveJobEvent,
  LiveJobResponse,
  LiveJobStatus,
  LiveStageStatus,
} from "@/lib/types";
import { formatFileSize } from "@/lib/ui";

const JOB_STATUS_LABEL: Record<LiveJobStatus, string> = {
  created: "Задание создано",
  receiving: "Файлы приняты",
  validating: "P0 · проверяем пакет",
  preparing: "P0.5 · готовим документы",
  running_p1: "P1 · целостность документов",
  running_p2: "P2 · нормативные проверки",
  running_p3: "P3 · количественные сопоставления",
  running_p4: "P4 · междокументная связность",
  running_meta: "Meta · рассчитываем приоритет",
  completed: "Анализ завершён",
  failed: "Анализ завершился с ошибкой",
  cancelled: "Анализ отменён",
  expired: "Срок хранения задания истёк",
};

const STAGE_STATUS_LABEL: Record<LiveStageStatus, string> = {
  pending: "Ожидание",
  running: "Выполняется",
  completed: "Готово",
  unavailable: "Недоступно",
  insufficient_input: "Недостаточно данных",
  failed: "Ошибка",
  cancelled: "Отменено",
};

const ARCHIVE_STATUS_LABEL: Record<ArchiveStatus, string> = {
  not_archive: "Не архив",
  registered: "Архив зарегистрирован",
  extracted: "Архив распакован",
  extraction_unsupported: "Распаковка не поддерживается",
  extraction_failed: "Ошибка распаковки",
};

const SECTION_LABEL: Record<LiveDossierSectionId, string> = {
  project_documents: "Проектная документация",
  official_supporting_documents: "Официальные решения",
  hearing_protocol: "Протокол слушаний",
  procedural_publication_evidence: "Публикация и уведомления",
  visual_geographic_materials: "Визуальные и географические материалы",
  public_feedback_metadata: "Общественная обратная связь",
};

const STAGES: Array<{
  state: Extract<
    LiveJobStatus,
    | "validating"
    | "preparing"
    | "running_p1"
    | "running_p2"
    | "running_p3"
    | "running_p4"
    | "running_meta"
  >;
  id: string;
  pillar: string | null;
  title: string;
}> = [
  { state: "validating", id: "p0", pillar: null, title: "P0 · Приём и проверка пакета" },
  { state: "preparing", id: "p0_5", pillar: null, title: "P0.5 · Подготовка документов" },
  { state: "running_p1", id: "p1", pillar: "P1", title: "Целостность документов" },
  { state: "running_p2", id: "p2", pillar: "P2", title: "Нормативные проверки" },
  { state: "running_p3", id: "p3", pillar: "P3", title: "Количественные сопоставления" },
  { state: "running_p4", id: "p4", pillar: "P4", title: "Междокументная связность" },
  { state: "running_meta", id: "meta", pillar: "META", title: "Приоритет экспертной проверки" },
];

function explicitStageStatus(event: LiveJobEvent | undefined): LiveStageStatus | null {
  if (!event?.metrics) return null;
  for (const key of ["stage_status", "status"]) {
    const value = event.metrics[key];
    if (
      value === "completed" ||
      value === "unavailable" ||
      value === "insufficient_input" ||
      value === "failed" ||
      value === "cancelled"
    ) {
      return value;
    }
  }
  return null;
}

function stageStatus(
  stageIndex: number,
  job: LiveJobResponse,
  events: LiveJobEvent[],
): LiveStageStatus {
  const stage = STAGES[stageIndex];
  const resultStage = job.result?.stages?.find(
    (item) => item.stage_id.toLowerCase() === stage.id,
  );
  if (resultStage) return resultStage.status;
  const event = [...events].reverse().find((item) => item.state === stage.state);
  const explicit = explicitStageStatus(event);
  if (explicit) return explicit;

  const activeIndex = STAGES.findIndex((item) => item.state === job.status);
  if (activeIndex === stageIndex) {
    return "running";
  }
  if (activeIndex > stageIndex) return "completed";
  if (job.status === "completed" && event) return "completed";
  if (job.status === "failed" || job.status === "cancelled") {
    const lastProcessingEvent = [...events]
      .reverse()
      .find((item) => STAGES.some((definition) => definition.state === item.state));
    const lastProcessingIndex = STAGES.findIndex(
      (definition) => definition.state === lastProcessingEvent?.state,
    );
    if (lastProcessingIndex > stageIndex) return "completed";
    if (lastProcessingIndex === stageIndex) {
      return job.status === "failed" ? "failed" : "cancelled";
    }
  }
  return "pending";
}

function stageStyle(status: LiveStageStatus): string {
  if (status === "running") return "border-accent-500 bg-accent-50/50 shadow-card";
  if (status === "completed") return "border-slate-200 bg-white";
  if (status === "failed") return "border-red-200 bg-red-50";
  if (status === "unavailable" || status === "insufficient_input") {
    return "border-amber-200 bg-amber-50/40";
  }
  return "border-dashed border-slate-300 bg-slate-50";
}

function StageIcon({ status }: { status: LiveStageStatus }) {
  if (status === "completed") return <Check className="h-4 w-4" aria-hidden />;
  if (status === "running") return <Loader2 className="h-4 w-4 animate-spin" aria-hidden />;
  if (status === "failed") return <XCircle className="h-4 w-4" aria-hidden />;
  if (status === "unavailable" || status === "insufficient_input") {
    return <Ban className="h-4 w-4" aria-hidden />;
  }
  return <span aria-hidden>·</span>;
}

function displayMetric(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (value === null) return "—";
  return null;
}

function metricLabel(key: string): string {
  return key.replaceAll("_", " ");
}

function LiveStageRow({
  stageIndex,
  job,
  events,
}: {
  stageIndex: number;
  job: LiveJobResponse;
  events: LiveJobEvent[];
}) {
  const stage = STAGES[stageIndex];
  const status = stageStatus(stageIndex, job, events);
  const event = [...events].reverse().find((item) => item.state === stage.state);
  const resultStage = job.result?.stages?.find(
    (item) => item.stage_id.toLowerCase() === stage.id,
  );
  const eventMetrics = Object.entries(event?.metrics ?? {})
    .filter(([key]) => key !== "status" && key !== "stage_status")
    .flatMap(([key, value]) => {
      const displayed = displayMetric(value);
      return displayed === null ? [] : [{ key, displayed }];
    });
  const metrics = resultStage
    ? resultStage.metrics.map((metric) => ({ key: metric.label, displayed: metric.value }))
    : eventMetrics;
  const operation = resultStage?.operation ?? event?.operation;
  const warnings = resultStage?.warnings ?? event?.warnings ?? [];
  const limitations = resultStage?.limitations ?? event?.limitations ?? [];
  const exposeOutput = status !== "pending" && status !== "running";

  return (
    <li className={`rounded-xl border p-4 transition-colors ${stageStyle(status)}`}>
      <div className="flex items-start gap-3">
        <span
          className={`flex h-8 w-8 flex-none items-center justify-center rounded-full ${
            status === "completed"
              ? "bg-accent-600 text-white"
              : status === "running"
                ? "bg-accent-100 text-accent-700"
                : status === "failed"
                  ? "bg-red-100 text-red-700"
                  : "bg-slate-200 text-slate-500"
          }`}
        >
          <StageIcon status={status} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {stage.pillar ? (
              <span className="chip bg-navy-900 px-2 py-0.5 text-[10px] text-white">
                {stage.pillar}
              </span>
            ) : null}
            <p className="text-sm font-semibold text-slate-900">{stage.title}</p>
            <span className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
              {STAGE_STATUS_LABEL[status]}
            </span>
          </div>

          {status === "running" && event ? (
            <div className="mt-2 space-y-1.5">
              <p aria-live="polite" className="text-xs leading-relaxed text-accent-700">
                {event.operation}
              </p>
              <p className="text-[10px] text-slate-400">Общий прогресс: {event.progress}%</p>
            </div>
          ) : null}

          {exposeOutput ? (
            <div className="mt-2 space-y-2">
              {resultStage?.reason ? (
                <p className="text-xs text-slate-700">{resultStage.reason}</p>
              ) : operation ? (
                <p className="text-xs text-slate-700">{operation}</p>
              ) : null}
              {metrics.length > 0 ? (
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
                  {metrics.slice(0, 9).map((metric) => (
                    <div key={metric.key}>
                      <dt className="text-[10px] uppercase tracking-wide text-slate-400">
                        {metricLabel(metric.key)}
                      </dt>
                      <dd className="text-xs font-semibold tabular-nums text-slate-800">
                        {metric.displayed}
                      </dd>
                    </div>
                  ))}
                </dl>
              ) : null}
              {warnings.map((warning) => (
                <p key={warning} className="text-xs leading-relaxed text-amber-700">
                  {warning}
                </p>
              ))}
              {limitations.map((limitation) => (
                <p key={limitation} className="text-xs leading-relaxed text-slate-500">
                  {limitation}
                </p>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </li>
  );
}

export function LiveAnalysisPipeline({
  job,
  events,
  cancelling,
  onCancel,
}: {
  job: LiveJobResponse;
  events: LiveJobEvent[];
  cancelling: boolean;
  onCancel: () => void;
}) {
  const progress = Math.max(0, Math.min(100, job.progress));
  const terminal = ["completed", "failed", "cancelled", "expired"].includes(job.status);
  const eventWarnings = Array.from(new Set(events.flatMap((event) => event.warnings)));

  return (
    <div className="space-y-4">
      <div className="rounded-xl bg-navy-900 px-5 py-4 text-white">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="chip bg-accent-600 text-white">
              <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
              Evidence-first
            </span>
            <span className="text-xs text-slate-300">Анализ нового проекта</span>
          </div>
          <span className="text-xs font-medium text-slate-200">{JOB_STATUS_LABEL[job.status]}</span>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-300">
          <span>{job.project_display_name}</span>
          <span>Файлов принято: {job.file_count}</span>
          <span>Общий размер: {formatFileSize(job.total_size_bytes)}</span>
        </div>
      </div>

      <div>
        <div
          className="h-2 overflow-hidden rounded-full bg-slate-200"
          role="progressbar"
          aria-label="Фактический прогресс серверного анализа"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress}
        >
          <span
            className="block h-full rounded-full bg-accent-600 transition-[width] duration-500 ease-out"
            style={{ width: `${progress}%` }}
          />
        </div>
        <div className="mt-1.5 flex items-start justify-between gap-3 text-[11px] text-slate-400">
          <p>{job.current_operation}</p>
          <span className="flex-none tabular-nums">{Math.round(progress)}%</span>
        </div>
        <p className="mt-1 text-[10px] leading-relaxed text-slate-400">
          Значение поступает от сервера; визуальный переход только сглаживает его отображение.
        </p>
      </div>

      <section className="card overflow-hidden" aria-label="Фактически принятые документы">
        <div className="border-b border-slate-100 px-4 py-3">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Фактически принятый пакет
          </h2>
        </div>
        <ul className="divide-y divide-slate-100">
          {job.files.map((file) => {
            const isArchive = file.archive_status !== "not_archive";
            return (
              <li key={file.file_id} className="flex items-start gap-3 px-4 py-3">
                {isArchive ? (
                  <Archive className="h-4 w-4 flex-none text-slate-400" aria-hidden />
                ) : (
                  <FileText className="h-4 w-4 flex-none text-slate-400" aria-hidden />
                )}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-slate-800">
                    {file.display_filename}
                  </p>
                  <p className="text-xs text-slate-500">
                    {SECTION_LABEL[file.section_id]} · {file.media_type.toUpperCase()} ·{" "}
                    {formatFileSize(file.size_bytes)}
                  </p>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    <span className="chip bg-slate-100 text-slate-600 ring-1 ring-inset ring-slate-200">
                      Проверен сервером
                    </span>
                    {isArchive ? (
                      <span
                        className={`chip ring-1 ring-inset ${
                          file.archive_status === "extracted"
                            ? "bg-accent-50 text-accent-700 ring-accent-100"
                            : file.archive_status === "registered"
                              ? "bg-sky-50 text-sky-700 ring-sky-200"
                              : "bg-amber-50 text-amber-800 ring-amber-200"
                        }`}
                      >
                        {ARCHIVE_STATUS_LABEL[file.archive_status]}
                      </span>
                    ) : null}
                    {file.duplicate_of ? (
                      <span className="chip bg-amber-50 text-amber-800 ring-1 ring-inset ring-amber-200">
                        Дубликат
                      </span>
                    ) : null}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      </section>

      <ol className="space-y-3">
        {STAGES.map((stage, index) => (
          <LiveStageRow key={stage.id} stageIndex={index} job={job} events={events} />
        ))}
      </ol>

      {eventWarnings.map((warning) => (
        <p
          key={warning}
          className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs leading-relaxed text-amber-800"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-none" aria-hidden />
          {warning}
        </p>
      ))}

      {!terminal ? (
        <div className="flex justify-center">
          <button
            type="button"
            disabled={cancelling}
            onClick={onCancel}
            className="btn-ghost disabled:cursor-not-allowed disabled:opacity-60"
          >
            {cancelling ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <XCircle className="h-4 w-4" aria-hidden />
            )}
            {cancelling ? "Отменяем…" : "Отменить анализ и удалить временные файлы"}
          </button>
        </div>
      ) : null}
    </div>
  );
}

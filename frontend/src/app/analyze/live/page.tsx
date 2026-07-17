"use client";

import { useCallback, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  FileSearch,
  Info,
  Loader2,
  MessageSquareText,
  Trash2,
} from "lucide-react";

import type {
  LiveDossierSchemaResponse,
  LiveDossierSectionId,
  LiveJobCreateResponse,
  LiveJobRequestPayload,
  LivePackageLimits,
  LiveSectionAssignment,
} from "@/lib/types";
import { apiPostForm } from "@/lib/api";
import { rememberJobToken } from "@/lib/jobTokens";
import { useApi } from "@/lib/useApi";
import { fileExtension, formatFileSize } from "@/lib/ui";
import { ErrorBlock, LoadingBlock } from "@/components/primitives";
import {
  LiveDossierSectionCard,
  type PendingLiveFile,
} from "@/components/LiveDossierBuilder";

const FALLBACK_LIMITS: LivePackageLimits = {
  max_file_count: 20,
  max_file_bytes: 50 * 1024 * 1024,
  max_total_bytes: 200 * 1024 * 1024,
  max_archive_files: 100,
  max_archive_expanded_bytes: 250 * 1024 * 1024,
  max_archive_ratio: 200,
  job_ttl_seconds: 1800,
  max_active_jobs: 4,
};

function newClientFileId(): string {
  return window.crypto.randomUUID();
}

export default function LiveAnalysisCreatePage() {
  const router = useRouter();
  const [retry, setRetry] = useState(0);
  const schema = useApi<LiveDossierSchemaResponse>("/api/live/package-schema", [retry]);
  const [projectName, setProjectName] = useState("");
  const [files, setFiles] = useState<PendingLiveFile[]>([]);
  const [feedbackEnabled, setFeedbackEnabled] = useState(false);
  const [submissionCount, setSubmissionCount] = useState("0");
  const [questionCount, setQuestionCount] = useState("0");
  const [feedbackNote, setFeedbackNote] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const sections = useMemo(() => schema.data?.sections ?? [], [schema.data]);
  const limits = schema.data?.limits ?? FALLBACK_LIMITS;
  const totalSize = useMemo(
    () => files.reduce((total, item) => total + item.file.size, 0),
    [files],
  );

  const addFiles = useCallback(
    (sectionId: LiveDossierSectionId, incoming: FileList) => {
      const definition = sections.find((section) => section.section_id === sectionId);
      if (!definition || !definition.upload_enabled) return;

      const nextErrors: string[] = [];
      const accepted: PendingLiveFile[] = [];
      let nextTotalSize = files.reduce((total, item) => total + item.file.size, 0);

      for (const file of Array.from(incoming)) {
        if (files.length + accepted.length >= limits.max_file_count) {
          nextErrors.push(`Можно загрузить не более ${limits.max_file_count} файлов в одно задание.`);
          break;
        }
        const extension = fileExtension(file.name);
        if (!definition.accepted_formats.includes(extension)) {
          nextErrors.push(
            `«${file.name}»: раздел «${definition.title_ru}» принимает только ${definition.accepted_formats
              .map((format) => format.toUpperCase())
              .join(", ")}.`,
          );
          continue;
        }
        if (file.size <= 0) {
          nextErrors.push(`«${file.name}»: пустой файл нельзя отправить на анализ.`);
          continue;
        }
        if (file.size > limits.max_file_bytes) {
          nextErrors.push(
            `«${file.name}»: размер превышает ${formatFileSize(limits.max_file_bytes)}.`,
          );
          continue;
        }
        if (nextTotalSize + file.size > limits.max_total_bytes) {
          nextErrors.push(
            `Общий размер файлов не должен превышать ${formatFileSize(limits.max_total_bytes)}.`,
          );
          break;
        }
        accepted.push({ clientId: newClientFileId(), file, sectionId });
        nextTotalSize += file.size;
      }

      setErrors(nextErrors);
      setSubmitError(null);
      if (accepted.length > 0) {
        setFiles((current) => [...current, ...accepted]);
      }
    },
    [files, limits.max_file_bytes, limits.max_file_count, limits.max_total_bytes, sections],
  );

  const startAnalysis = async () => {
    if (files.length === 0) {
      setErrors(["Добавьте хотя бы один поддерживаемый документ."]);
      return;
    }
    const parsedSubmissionCount = Number(submissionCount);
    const parsedQuestionCount = Number(questionCount);
    if (
      feedbackEnabled &&
      (!Number.isInteger(parsedSubmissionCount) ||
        parsedSubmissionCount < 0 ||
        parsedSubmissionCount > 1_000_000 ||
        !Number.isInteger(parsedQuestionCount) ||
        parsedQuestionCount < 0 ||
        parsedQuestionCount > 1_000_000)
    ) {
      setErrors(["Количество обращений и вопросов должно быть целым неотрицательным числом."]);
      return;
    }

    setSubmitting(true);
    setErrors([]);
    setSubmitError(null);
    const sectionAssignments: LiveSectionAssignment[] = sections
      .filter((section) => section.section_id !== "public_feedback_metadata")
      .map((section) => ({
        section_id: section.section_id,
        upload_indices: files.flatMap((item, fileIndex) =>
          item.sectionId === section.section_id ? [fileIndex] : [],
        ),
      }))
      .filter((section) => section.upload_indices.length > 0);
    if (
      feedbackEnabled &&
      sections.some((section) => section.section_id === "public_feedback_metadata")
    ) {
      sectionAssignments.push({
        section_id: "public_feedback_metadata",
        upload_indices: [],
      });
    }
    const request: LiveJobRequestPayload = {
      mode: "live_analysis",
      project_display_name: projectName.trim() || null,
      sections: sectionAssignments,
      public_feedback: feedbackEnabled
        ? {
            submission_count: parsedSubmissionCount,
            question_count: parsedQuestionCount,
            note: feedbackNote.trim() || null,
          }
        : undefined,
    };
    const form = new FormData();
    form.append("request", JSON.stringify(request));
    for (const item of files) {
      form.append("files", item.file, item.file.name);
    }

    try {
      const job = await apiPostForm<LiveJobCreateResponse>("/api/live/jobs", form);
      if (job.mode !== "live_analysis" || !job.access_token) {
        throw new Error("Сервер вернул некорректный ответ для нового анализа.");
      }
      rememberJobToken("live_analysis", job.job_id, job.access_token);
      router.push(`/analyze/live/${encodeURIComponent(job.job_id)}`);
    } catch (error) {
      setSubmitError(
        error instanceof Error
          ? error.message
          : "Не удалось передать документы. Проверьте соединение и повторите попытку.",
      );
      setSubmitting(false);
    }
  };

  if (schema.loading) {
    return (
      <div className="mx-auto max-w-3xl">
        <LoadingBlock label="Загружаем структуру нового проекта…" />
      </div>
    );
  }

  if (schema.error || !schema.data) {
    return (
      <div className="mx-auto max-w-3xl space-y-3">
        <ErrorBlock message={schema.error ?? "Не удалось загрузить правила приёма документов."} />
        <div className="flex justify-center gap-3">
          <button type="button" onClick={() => setRetry((value) => value + 1)} className="btn-ghost">
            Повторить
          </button>
          <Link href="/analyze" className="btn-ghost">
            К выбору режима
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <header>
        <Link
          href="/analyze"
          className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-accent-700"
        >
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
          Выбрать другой режим
        </Link>
        <h1 className="mt-3 text-2xl font-semibold tracking-tight text-slate-900">
          Анализ нового проекта
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-slate-600">
          Добавьте реальные документы по разделам. Сервер проверит типы и содержимое, создаст
          отдельный временный набор данных и запустит фактические P0, P0.5, доступные P1–P4 и Meta.
        </p>
      </header>

      <div className="flex items-start gap-2.5 rounded-lg border border-sky-200 bg-sky-50 px-4 py-3">
        <Info className="mt-0.5 h-4 w-4 flex-none text-sky-700" aria-hidden />
        <p className="text-xs leading-relaxed text-sky-900">
          Файлы хранятся только во временной изолированной рабочей области задания. Результаты
          строятся только из этого пакета, а недоступные проверки отмечаются явно.
        </p>
      </div>

      <label className="card block p-4">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Название проекта · необязательно
        </span>
        <input
          type="text"
          maxLength={120}
          value={projectName}
          disabled={submitting}
          onChange={(event) => setProjectName(event.target.value)}
          placeholder="Например, проект модернизации площадки"
          className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 outline-none focus:border-accent-500 focus:ring-2 focus:ring-accent-100 disabled:bg-slate-50"
        />
      </label>

      {errors.length > 0 ? (
        <div className="space-y-1.5 rounded-lg border border-red-200 bg-red-50 px-4 py-3">
          {errors.map((message) => (
            <p key={message} className="flex items-start gap-2 text-xs text-red-800">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-none" aria-hidden />
              {message}
            </p>
          ))}
        </div>
      ) : null}

      <div className="space-y-3">
        {sections.map((definition) =>
          definition.section_id === "public_feedback_metadata" ? (
            <section key={definition.section_id} className="card overflow-hidden">
              <div className="space-y-2 border-b border-slate-100 p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-navy-900 text-[11px] font-semibold text-white">
                    {definition.order}
                  </span>
                  <MessageSquareText className="h-4 w-4 text-slate-400" aria-hidden />
                  <h3 className="text-sm font-semibold text-slate-900">{definition.title_ru}</h3>
                </div>
                <p className="text-xs leading-relaxed text-slate-500">
                  Необязательные агрегированные данные из поддерживаемого структурированного
                  источника. Они помечаются как предоставленные пользователем.
                </p>
              </div>
              <div className="space-y-3 p-4">
                <label className="flex items-center gap-2 text-xs font-medium text-slate-700">
                  <input
                    type="checkbox"
                    checked={feedbackEnabled}
                    disabled={submitting}
                    onChange={(event) => setFeedbackEnabled(event.target.checked)}
                    className="h-4 w-4 rounded border-slate-300 text-accent-600 focus:ring-accent-500"
                  />
                  Добавить структурированную сводку обратной связи
                </label>
                {feedbackEnabled ? (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <label className="text-xs text-slate-600">
                      Обращений
                      <input
                        type="number"
                        min={0}
                        max={1_000_000}
                        step={1}
                        value={submissionCount}
                        disabled={submitting}
                        onChange={(event) => setSubmissionCount(event.target.value)}
                        className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800"
                      />
                    </label>
                    <label className="text-xs text-slate-600">
                      Вопросов и замечаний
                      <input
                        type="number"
                        min={0}
                        max={1_000_000}
                        step={1}
                        value={questionCount}
                        disabled={submitting}
                        onChange={(event) => setQuestionCount(event.target.value)}
                        className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800"
                      />
                    </label>
                    <label className="text-xs text-slate-600 sm:col-span-2">
                      Примечание · необязательно
                      <textarea
                        maxLength={1000}
                        value={feedbackNote}
                        disabled={submitting}
                        onChange={(event) => setFeedbackNote(event.target.value)}
                        className="mt-1 min-h-20 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800"
                      />
                    </label>
                  </div>
                ) : null}
              </div>
            </section>
          ) : (
            <LiveDossierSectionCard
              key={definition.section_id}
              definition={definition}
              files={files.filter((item) => item.sectionId === definition.section_id)}
              sections={sections}
              disabled={submitting}
              onAddFiles={addFiles}
              onMoveFile={(fileId, sectionId) =>
                setFiles((current) =>
                  current.map((item) =>
                    item.clientId === fileId ? { ...item, sectionId } : item,
                  ),
                )
              }
              onRemoveFile={(fileId) =>
                setFiles((current) => current.filter((item) => item.clientId !== fileId))
              }
            />
          ),
        )}
      </div>

      <section className="card p-4" aria-label="Параметры загрузки">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div>
            <p className="text-[10px] uppercase tracking-wide text-slate-400">Файлов</p>
            <p className="text-lg font-semibold tabular-nums text-slate-900">
              {files.length}/{limits.max_file_count}
            </p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wide text-slate-400">Общий размер</p>
            <p className="text-lg font-semibold tabular-nums text-slate-900">
              {formatFileSize(totalSize)}
            </p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wide text-slate-400">Лимит файла</p>
            <p className="text-lg font-semibold tabular-nums text-slate-900">
              {formatFileSize(limits.max_file_bytes)}
            </p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wide text-slate-400">Лимит пакета</p>
            <p className="text-lg font-semibold tabular-nums text-slate-900">
              {formatFileSize(limits.max_total_bytes)}
            </p>
          </div>
        </div>
        <p className="mt-3 text-[11px] leading-relaxed text-slate-400">
          Проверка в браузере помогает собрать пакет. Окончательная проверка MIME-типа, сигнатуры,
          хеша, дублей и архивов выполняется сервером.
        </p>
      </section>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={startAnalysis}
          disabled={submitting || files.length === 0}
          className="btn-primary disabled:cursor-not-allowed disabled:opacity-70"
        >
          {submitting ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <FileSearch className="h-4 w-4" aria-hidden />
          )}
          {submitting ? "Передаём файлы…" : "Запустить анализ нового проекта"}
        </button>
        {files.length > 0 ? (
          <button
            type="button"
            disabled={submitting}
            onClick={() => {
              setFiles([]);
              setFeedbackEnabled(false);
              setSubmissionCount("0");
              setQuestionCount("0");
              setFeedbackNote("");
              setErrors([]);
            }}
            className="btn-ghost disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Trash2 className="h-4 w-4" aria-hidden />
            Очистить пакет
          </button>
        ) : null}
      </div>

      {submitError ? (
        <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-none text-red-600" aria-hidden />
          <p className="text-xs leading-relaxed text-red-800">{submitError}</p>
        </div>
      ) : null}
    </div>
  );
}

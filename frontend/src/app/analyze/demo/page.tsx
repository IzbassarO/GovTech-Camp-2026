"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertTriangle, ArrowLeft, Info, Loader2, Play } from "lucide-react";

import type {
  DemoJobCreateResponse,
  DemoJobRequest,
  DossierManifestResponse,
} from "@/lib/types";
import { apiPost } from "@/lib/api";
import { rememberJobToken } from "@/lib/jobTokens";
import { useApi } from "@/lib/useApi";
import { ErrorBlock, LoadingBlock } from "@/components/primitives";
import { PreparedDossierView } from "@/components/PreparedDossierView";

const REPLAY_NOTICE =
  "Демонстрационный запуск воспроизводит заранее рассчитанные результаты подготовленного проекта Bayterek.";

export default function PreparedDemoPage() {
  const router = useRouter();
  const [retry, setRetry] = useState(0);
  const manifest = useApi<DossierManifestResponse>("/api/demo/manifest", [retry]);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const startReplay = async () => {
    if (!manifest.data) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const request: DemoJobRequest = {
        mode: "prepared_replay",
      };
      const job = await apiPost<DemoJobCreateResponse>("/api/demo/jobs", request);
      if (job.mode !== "prepared_replay" || !job.access_token) {
        throw new Error("Сервер вернул некорректный ответ для демонстрационного запуска.");
      }
      rememberJobToken("prepared_replay", job.job_id, job.access_token);
      router.push(`/analyze/demo/${encodeURIComponent(job.job_id)}`);
    } catch (error) {
      setSubmitError(
        error instanceof Error
          ? error.message
          : "Не удалось открыть подготовленную демонстрацию.",
      );
      setSubmitting(false);
    }
  };

  if (manifest.loading) {
    return (
      <div className="mx-auto max-w-3xl">
        <LoadingBlock label="Загружаем подготовленный пакет Bayterek…" />
      </div>
    );
  }

  if (manifest.error || !manifest.data || !manifest.data.prepared) {
    return (
      <div className="mx-auto max-w-3xl space-y-3">
        <ErrorBlock
          message={
            manifest.error ??
            "Сервер не подтвердил неизменяемый подготовленный пакет демонстрации."
          }
        />
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
          Демонстрация Bayterek
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-slate-600">
          Полный структурированный пакет и принятые результаты P0–P4 и Meta доступны только для
          просмотра. Этот режим не анализирует новые документы.
        </p>
      </header>

      <div className="flex items-start gap-2.5 rounded-lg border border-sky-200 bg-sky-50 px-4 py-3">
        <Info className="mt-0.5 h-4 w-4 flex-none text-sky-700" aria-hidden />
        <p className="text-xs font-medium leading-relaxed text-sky-900">{REPLAY_NOTICE}</p>
      </div>

      <PreparedDossierView manifest={manifest.data} />

      <div className="sticky bottom-4 z-10 rounded-xl border border-slate-200 bg-white/95 p-4 shadow-card backdrop-blur">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="max-w-xl text-xs leading-relaxed text-slate-500">{REPLAY_NOTICE}</p>
          <button
            type="button"
            onClick={startReplay}
            disabled={submitting}
            className="btn-primary disabled:cursor-not-allowed disabled:opacity-70"
          >
            {submitting ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Play className="h-4 w-4" aria-hidden />
            )}
            Запустить демонстрацию Bayterek
          </button>
        </div>
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

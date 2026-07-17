"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { AlertTriangle } from "lucide-react";

import { apiDeleteWithJobToken } from "@/lib/api";
import { forgetJobToken } from "@/lib/jobTokens";
import { useLiveJob } from "@/lib/useLiveJob";
import { LoadingBlock } from "@/components/primitives";
import { LiveAnalysisPipeline } from "@/components/LiveAnalysisPipeline";
import { LiveAnalysisResult } from "@/components/LiveAnalysisResult";

export default function LiveAnalysisJobPage() {
  const params = useParams<{ jobId: string }>();
  const router = useRouter();
  const [retry, setRetry] = useState(0);
  const job = useLiveJob(params.jobId, retry);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);

  const cancelJob = async () => {
    if (!job.accessToken) return;
    setCancelling(true);
    setCancelError(null);
    try {
      await apiDeleteWithJobToken<void>(
        `/api/live/jobs/${encodeURIComponent(params.jobId)}`,
        job.accessToken,
      );
      forgetJobToken("live_analysis", params.jobId);
      router.replace("/analyze/live");
    } catch (error) {
      setCancelling(false);
      setCancelError(
        error instanceof Error
          ? error.message
          : "Не удалось отменить задание и удалить временные файлы.",
      );
    }
  };

  if (job.loading && !job.data) {
    return (
      <div className="mx-auto max-w-2xl">
        <LoadingBlock label="Получаем фактическое состояние анализа…" />
      </div>
    );
  }

  if (!job.data) {
    return (
      <div className="mx-auto max-w-2xl space-y-4">
        <div className="flex flex-col items-center gap-2 rounded-xl border border-red-200 bg-red-50 py-10 text-center">
          <AlertTriangle className="h-6 w-6 text-red-500" aria-hidden />
          <p className="text-sm font-medium text-red-800">Задание анализа недоступно.</p>
          <p className="max-w-md text-xs leading-relaxed text-red-600">{job.error}</p>
        </div>
        <div className="flex flex-wrap justify-center gap-3">
          {job.accessToken ? (
            <button type="button" onClick={() => setRetry((value) => value + 1)} className="btn-ghost">
              Повторить
            </button>
          ) : null}
          <Link href="/analyze/live" className="btn-primary">
            Создать новый анализ
          </Link>
          <Link href="/analyze" className="btn-ghost">
            К выбору режима
          </Link>
        </div>
      </div>
    );
  }

  const terminalProblem = ["failed", "cancelled", "expired"].includes(job.data.status);

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <LiveAnalysisPipeline
        job={job.data}
        events={job.events}
        cancelling={cancelling}
        onCancel={() => void cancelJob()}
      />

      {job.error ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
          <p className="text-xs leading-relaxed text-amber-800">{job.error}</p>
          <button type="button" onClick={() => setRetry((value) => value + 1)} className="btn-ghost">
            Возобновить обновление
          </button>
        </div>
      ) : null}

      {cancelError ? (
        <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-none text-red-600" aria-hidden />
          <p className="text-xs leading-relaxed text-red-800">{cancelError}</p>
        </div>
      ) : null}

      {terminalProblem ? (
        <div className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-5 text-center">
          <p className="text-sm font-semibold text-slate-800">
            {job.data.status === "failed"
              ? "Анализ завершился с ошибкой"
              : job.data.status === "cancelled"
                ? "Анализ отменён"
                : "Срок хранения задания истёк"}
          </p>
          <p className="text-xs leading-relaxed text-slate-500">
            {job.data.failure_code ??
              job.data.limitations[0] ??
              "Создайте новое временное задание, чтобы повторить обработку документов."}
          </p>
          <Link href="/analyze/live" className="btn-primary">
            Создать новый анализ
          </Link>
        </div>
      ) : null}

      <LiveAnalysisResult job={job.data} />
    </div>
  );
}

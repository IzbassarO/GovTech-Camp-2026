"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AlertTriangle, Info } from "lucide-react";

import type { DemoJobResponse } from "@/lib/types";
import { ApiError, apiGetWithJobToken } from "@/lib/api";
import { readJobToken } from "@/lib/jobTokens";
import { LoadingBlock } from "@/components/primitives";
import { PreparedReplayPipeline } from "@/components/AnalysisPipeline";
import { PreparedReplayResult } from "@/components/AnalysisResult";

export default function PreparedReplayJobPage() {
  const params = useParams<{ jobId: string }>();
  const [retry, setRetry] = useState(0);
  const [job, setJob] = useState<DemoJobResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [runKey, setRunKey] = useState(0);
  const [complete, setComplete] = useState(false);

  useEffect(() => {
    const accessToken = readJobToken("prepared_replay", params.jobId);
    if (!accessToken) {
      setLoading(false);
      setError(
        "Защищённый ключ этого запуска недоступен в текущей вкладке. Откройте пакет и запустите демонстрацию заново.",
      );
      return;
    }

    const controller = new AbortController();
    setLoading(true);
    setError(null);
    apiGetWithJobToken<DemoJobResponse>(
      `/api/demo/jobs/${encodeURIComponent(params.jobId)}`,
      accessToken,
      controller.signal,
    )
      .then((response) => {
        if (response.mode !== "prepared_replay") {
          throw new Error("Режим задания не соответствует подготовленной демонстрации.");
        }
        setJob(response);
        setLoading(false);
      })
      .catch((requestError: unknown) => {
        if (controller.signal.aborted) return;
        setLoading(false);
        setError(
          requestError instanceof ApiError || requestError instanceof Error
            ? requestError.message
            : "Демонстрационный запуск недоступен.",
        );
      });
    return () => controller.abort();
  }, [params.jobId, retry]);

  if (loading) {
    return (
      <div className="mx-auto max-w-2xl">
        <LoadingBlock label="Открываем защищённое воспроизведение…" />
      </div>
    );
  }

  if (error || !job) {
    return (
      <div className="mx-auto max-w-2xl space-y-4">
        <div className="flex flex-col items-center gap-2 rounded-xl border border-red-200 bg-red-50 py-10 text-center">
          <AlertTriangle className="h-6 w-6 text-red-500" aria-hidden />
          <p className="text-sm font-medium text-red-800">Не удалось открыть воспроизведение.</p>
          <p className="max-w-md text-xs leading-relaxed text-red-600">{error}</p>
        </div>
        <div className="flex flex-wrap justify-center gap-3">
          <button type="button" onClick={() => setRetry((value) => value + 1)} className="btn-ghost">
            Повторить
          </button>
          <Link href="/analyze/demo" className="btn-primary">
            Открыть пакет заново
          </Link>
          <Link href="/analyze" className="btn-ghost">
            К выбору режима
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <div className="flex items-start gap-2.5 rounded-lg border border-sky-200 bg-sky-50 px-4 py-3">
        <Info className="mt-0.5 h-4 w-4 flex-none text-sky-700" aria-hidden />
        <p className="text-xs font-medium leading-relaxed text-sky-900">
          Демонстрационный запуск воспроизводит заранее рассчитанные результаты подготовленного
          проекта Bayterek.
        </p>
      </div>
      <PreparedReplayPipeline
        key={runKey}
        job={job}
        onComplete={() => setComplete(true)}
        cancelHref="/analyze/demo"
        onRestart={() => {
          setComplete(false);
          setRunKey((value) => value + 1);
        }}
      />
      {complete ? <PreparedReplayResult job={job} restartHref="/analyze" /> : null}
    </div>
  );
}

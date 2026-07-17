"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Check, FileText, Loader2, RotateCcw, ShieldCheck, XCircle } from "lucide-react";

import type { DemoJobResponse, DemoStage } from "@/lib/types";
import { useReducedMotion } from "@/lib/useReducedMotion";

// Total prepared-demo duration target is ~12-20s (see brief). Each stage
// advances one sub-status message at a time; reduced motion keeps the same
// SEQUENCE (never skips a stage) but compresses the pacing drastically.
const MESSAGE_DURATION_MS = 800;
const REDUCED_MESSAGE_DURATION_MS = 150;

type StageStatus = "pending" | "active" | "done";

function StageRow({
  stage,
  status,
  activeMessage,
}: {
  stage: DemoStage;
  status: StageStatus;
  activeMessage: string | undefined;
}) {
  const statusLabel =
    status === "done" ? "Готово" : status === "active" ? "Выполняется" : "Ожидание";
  return (
    <li
      className={`rounded-xl border p-4 transition-colors ${
        status === "active"
          ? "border-accent-500 bg-accent-50/50 shadow-card"
          : status === "done"
            ? "border-slate-200 bg-white"
            : "border-dashed border-slate-300 bg-slate-50"
      }`}
    >
      <div className="flex items-start gap-3">
        <span
          className={`flex h-8 w-8 flex-none items-center justify-center rounded-full ${
            status === "done"
              ? "bg-accent-600 text-white"
              : status === "active"
                ? "bg-accent-100 text-accent-700"
                : "bg-slate-200 text-slate-400"
          }`}
        >
          {status === "done" ? (
            <Check className="h-4 w-4" aria-hidden />
          ) : status === "active" ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <span aria-hidden>·</span>
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {stage.pillar_id ? (
              <span className="chip bg-navy-900 px-2 py-0.5 text-[10px] text-white">
                {stage.pillar_id}
              </span>
            ) : null}
            <p className="text-sm font-semibold text-slate-900">{stage.title}</p>
            <span className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
              {statusLabel}
            </span>
          </div>
          {status === "active" ? (
            <div className="mt-1 space-y-1">
              {activeMessage ? (
                <p aria-live="polite" className="text-xs text-accent-700">
                  {activeMessage}
                </p>
              ) : null}
              {stage.operation ? (
                <p className="text-xs leading-relaxed text-slate-500">{stage.operation}</p>
              ) : null}
            </div>
          ) : null}
          {status === "done" ? (
            <div className="mt-2 space-y-2">
              {/* Input: which dossier materials feed this stage */}
              {stage.inputs.length > 0 ? (
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                    Вход
                  </span>
                  {stage.inputs.slice(0, 4).map((input) => (
                    <span
                      key={input}
                      className="chip bg-slate-100 text-slate-600 ring-1 ring-inset ring-slate-200"
                    >
                      {input}
                    </span>
                  ))}
                  {stage.inputs.length > 4 ? (
                    <span className="text-[11px] text-slate-400">
                      +{stage.inputs.length - 4}
                    </span>
                  ) : null}
                </div>
              ) : null}
              {stage.input_note ? (
                <p className="text-[11px] leading-snug text-slate-400">{stage.input_note}</p>
              ) : null}
              {/* Operation: what the stage does */}
              {stage.operation ? (
                <p className="text-xs leading-relaxed text-slate-500">{stage.operation}</p>
              ) : null}
              {/* Output: artifact-backed result */}
              <p className="text-sm text-slate-700">{stage.headline}</p>
              {stage.warning ? <p className="text-xs text-amber-700">{stage.warning}</p> : null}
              {stage.empty_state ? (
                <p className="text-xs text-accent-700">{stage.empty_state}</p>
              ) : null}
              {stage.metrics.length > 0 ? (
                <dl className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
                  {stage.metrics.slice(0, 6).map((metric) => (
                    <div key={metric.label}>
                      <dt className="text-[10px] uppercase tracking-wide text-slate-400">
                        {metric.label}
                      </dt>
                      <dd className="text-xs font-semibold tabular-nums text-slate-800">
                        {metric.value}
                      </dd>
                    </div>
                  ))}
                </dl>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </li>
  );
}

export function PreparedReplayPipeline({
  job,
  onComplete,
  cancelHref,
  onRestart,
}: {
  job: DemoJobResponse;
  onComplete: () => void;
  cancelHref: string;
  onRestart: () => void;
}) {
  const stages = job.stages;
  const reducedMotion = useReducedMotion();
  const [activeIndex, setActiveIndex] = useState(0);
  const [messageIndex, setMessageIndex] = useState(0);
  const [done, setDone] = useState(false);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  useEffect(() => {
    if (done) return;
    if (activeIndex >= stages.length) {
      setDone(true);
      onCompleteRef.current();
      return;
    }
    const stage = stages[activeIndex];
    const duration = reducedMotion ? REDUCED_MESSAGE_DURATION_MS : MESSAGE_DURATION_MS;
    const timer = window.setTimeout(() => {
      if (messageIndex + 1 < stage.status_messages.length) {
        setMessageIndex((value) => value + 1);
      } else {
        setActiveIndex((value) => value + 1);
        setMessageIndex(0);
      }
    }, duration);
    return () => window.clearTimeout(timer);
  }, [activeIndex, messageIndex, stages, reducedMotion, done]);

  const currentStage = stages[activeIndex];
  const currentStageMessageCount = currentStage?.status_messages.length ?? 1;
  const overallProgress = done
    ? 100
    : Math.min(
        100,
        Math.round(((activeIndex + messageIndex / currentStageMessageCount) / stages.length) * 100),
      );
  const showFilePreview =
    !done && (currentStage?.stage_id === "p0" || currentStage?.stage_id === "p0_5");
  const previewCount = Math.min(
    5,
    Math.max(2, job.registered_source_count + job.uploaded_file_count),
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-navy-900 px-5 py-4 text-white">
        <div className="flex items-center gap-2">
          <span className="chip bg-accent-600 text-white">
            <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
            Evidence-first
          </span>
          <span className="text-xs text-slate-300">Воспроизведение принятого анализа</span>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-300">
          <span>
            Источник: {job.registered_source_count} · локально: {job.locally_available_count} · в
            анализе: {job.analyzed_count}
          </span>
          <span>
            Шаг {Math.min(activeIndex + 1, stages.length)} из {stages.length}
          </span>
        </div>
      </div>

      <div
        className="h-2 overflow-hidden rounded-full bg-slate-200"
        role="progressbar"
        aria-label="Прогресс воспроизведения принятого анализа"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={overallProgress}
      >
        <span
          className="block h-full rounded-full bg-accent-600 transition-[width] duration-500 ease-out"
          style={{ width: `${overallProgress}%` }}
        />
      </div>

      {showFilePreview ? (
        <div className="flex items-center justify-center gap-3 py-1" aria-hidden>
          {Array.from({ length: previewCount }).map((_, index) => (
            <FileText
              key={index}
              className="h-7 w-7 animate-pulse text-accent-500/50"
              style={{ animationDelay: `${index * 150}ms` }}
            />
          ))}
        </div>
      ) : null}

      <ol className="space-y-3">
        {stages.map((stage, index) => (
          <StageRow
            key={stage.stage_id}
            stage={stage}
            status={
              done || index < activeIndex ? "done" : index === activeIndex ? "active" : "pending"
            }
            activeMessage={index === activeIndex ? stage.status_messages[messageIndex] : undefined}
          />
        ))}
      </ol>

      {!done ? (
        <div className="flex justify-center gap-3">
          <Link href={cancelHref} className="btn-ghost">
            <XCircle className="h-4 w-4" aria-hidden />
            Закрыть воспроизведение
          </Link>
          <button type="button" onClick={onRestart} className="btn-ghost">
            <RotateCcw className="h-4 w-4" aria-hidden />
            Воспроизвести заново
          </button>
        </div>
      ) : null}
    </div>
  );
}

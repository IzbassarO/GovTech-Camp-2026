"use client";

import Link from "next/link";
import { FileStack, FolderKanban, ShieldCheck, TriangleAlert } from "lucide-react";

import type { ProjectListItem, SystemMetrics } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { SEVERITY_LABEL, SEVERITY_ORDER } from "@/lib/ui";
import { ErrorBlock, Section, SkeletonCard } from "@/components/primitives";
import { StatCard } from "@/components/StatCard";
import { ProjectCard } from "@/components/ProjectCard";
import { PipelineSteps } from "@/components/PipelineSteps";

export default function DashboardPage() {
  const metrics = useApi<SystemMetrics>("/api/system/metrics");
  const projects = useApi<ProjectListItem[]>("/api/projects");

  return (
    <div className="space-y-10">
      <section className="rounded-2xl bg-navy-900 px-6 py-10 text-white sm:px-10">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-accent-500">
          BizAI · Dalel
        </p>
        <h1 className="mt-3 max-w-3xl text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">
          AI-платформа доказательного анализа экологической документации
        </h1>
        <p className="mt-4 max-w-2xl text-sm leading-relaxed text-slate-300 sm:text-base">
          Каждое наблюдение привязано к документу, странице и разделу. Анализ
          детерминированный и воспроизводимый, а итоговое решение остаётся за
          экспертом — платформа не выносит юридических выводов.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link href="/projects" className="btn-primary">
            Перейти к проектам
          </Link>
          <Link
            href="/methodology"
            className="inline-flex items-center rounded-lg border border-navy-700 px-4 py-2 text-sm font-medium text-slate-200 hover:bg-navy-800"
          >
            Методология
          </Link>
        </div>
      </section>

      <Section
        title="Сводка анализа"
        description="Агрегировано по принятым результатам P1 / P2 / P3. Интегральная оценка риска пока не рассчитывается."
      >
        {metrics.error ? (
          <ErrorBlock message={metrics.error} />
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {metrics.loading || !metrics.data ? (
              <>
                <SkeletonCard />
                <SkeletonCard />
                <SkeletonCard />
                <SkeletonCard />
              </>
            ) : (
              <>
                <StatCard
                  label="Проектов"
                  value={metrics.data.projects}
                  icon={<FolderKanban className="h-5 w-5" aria-hidden />}
                />
                <StatCard
                  label="Документов"
                  value={metrics.data.documents}
                  icon={<FileStack className="h-5 w-5" aria-hidden />}
                />
                <StatCard
                  label="Замечаний всего"
                  value={metrics.data.findings_total}
                  hint="P1 структура · P2 демо-корпус · P3 числа"
                  icon={<TriangleAlert className="h-5 w-5" aria-hidden />}
                />
                <StatCard
                  label="Доказанных числовых противоречий"
                  value={metrics.data.findings_by_pillar.p3 ?? 0}
                  hint="P3: недостаточно контекстные сравнения исключены"
                  icon={<ShieldCheck className="h-5 w-5" aria-hidden />}
                />
              </>
            )}
          </div>
        )}

        {metrics.data ? (
          <div className="card mt-4 flex flex-wrap items-center gap-x-6 gap-y-2 p-4">
            <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
              По серьёзности
            </span>
            {SEVERITY_ORDER.map((sev) => (
              <span key={sev} className="text-sm text-slate-600">
                {SEVERITY_LABEL[sev]}:{" "}
                <span className="font-semibold tabular-nums text-slate-900">
                  {metrics.data!.severity_counts[sev]}
                </span>
              </span>
            ))}
            <span className="ml-auto rounded-lg bg-slate-100 px-3 py-1 text-xs text-slate-500">
              Интегральный риск — следующий этап
            </span>
          </div>
        ) : null}
      </Section>

      <Section title="Конвейер и статус пилларов">
        <PipelineSteps />
      </Section>

      <Section
        title="Проекты"
        description="Пакеты экологической документации, прошедшие анализ."
        action={
          <Link href="/projects" className="text-sm font-medium text-accent-700 hover:underline">
            Все проекты →
          </Link>
        }
      >
        {projects.error ? (
          <ErrorBlock message={projects.error} />
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {projects.loading || !projects.data ? (
              <>
                <SkeletonCard />
                <SkeletonCard />
                <SkeletonCard />
              </>
            ) : (
              projects.data.map((project) => (
                <ProjectCard key={project.project_id} project={project} />
              ))
            )}
          </div>
        )}
      </Section>
    </div>
  );
}

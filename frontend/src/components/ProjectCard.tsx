import Link from "next/link";
import { ArrowRight, Building2, Gauge, MapPin } from "lucide-react";

import type { ProjectListItem } from "@/lib/types";
import {
  assessmentPercent,
  documentsWord,
  findingsWord,
  formatMetaNumber,
  reviewPriorityLabel,
  reviewPriorityStyle,
} from "@/lib/ui";
import { SeverityBar } from "@/components/primitives";

const PILLAR_SHORT: Record<string, string> = { p1: "P1", p2: "P2", p3: "P3", p4: "P4" };

export function ProjectCard({ project }: { project: ProjectListItem }) {
  return (
    <Link
      href={`/projects/${project.project_id}`}
      className="card group flex flex-col p-5 transition-shadow hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-slate-900">{project.name}</h3>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
            {project.region ? (
              <span className="inline-flex items-center gap-1">
                <MapPin className="h-3.5 w-3.5" aria-hidden />
                {project.region}
              </span>
            ) : null}
            {project.industry ? (
              <span className="inline-flex items-center gap-1">
                <Building2 className="h-3.5 w-3.5" aria-hidden />
                {project.industry}
              </span>
            ) : null}
          </div>
        </div>
        {project.has_demo_pillar ? (
          <span className="chip bg-amber-50 text-amber-700">демо-корпус</span>
        ) : null}
      </div>

      <div className="mt-4 flex items-center gap-4 text-sm text-slate-600">
        <span>{documentsWord(project.document_count)}</span>
        <span className="text-slate-300">·</span>
        <span>{findingsWord(project.findings_total)}</span>
      </div>

      <div className="mt-3">
        <SeverityBar counts={project.severity_counts} />
      </div>

      {project.meta ? (
        <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50/70 p-3.5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="flex items-center gap-1.5 text-xs font-medium text-slate-500">
                <Gauge className="h-3.5 w-3.5 text-accent-600" aria-hidden />
                Приоритетность проверки
              </p>
              <p className="mt-1 text-2xl font-semibold tabular-nums text-slate-900">
                {formatMetaNumber(project.meta.review_priority_score)}
                <span className="ml-0.5 text-sm font-medium text-slate-400">/100</span>
              </p>
            </div>
            <span className={`chip ${reviewPriorityStyle(project.meta.review_priority_level)}`}>
              {reviewPriorityLabel(project.meta.review_priority_level)}
            </span>
          </div>
          <div className="mt-3">
            <div className="flex items-center justify-between text-[11px] text-slate-500">
              <span>Покрытие доказательств</span>
              <span className="font-semibold tabular-nums text-slate-700">
                {formatMetaNumber(assessmentPercent(project.meta.evidence_coverage))}%
              </span>
            </div>
            <div
              className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-200"
              role="progressbar"
              aria-label="Покрытие доказательств"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={assessmentPercent(project.meta.evidence_coverage)}
            >
              <span
                className="block h-full rounded-full bg-accent-600"
                style={{ width: `${assessmentPercent(project.meta.evidence_coverage)}%` }}
              />
            </div>
          </div>
        </div>
      ) : (
        <p className="mt-4 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
          Интегральная оценка недоступна: нет валидных Meta-артефактов.
        </p>
      )}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4">
        <div className="flex flex-wrap gap-2">
          {Object.entries(project.pillar_finding_counts).map(([key, count]) => (
            <span
              key={key}
              className="chip bg-slate-100 text-slate-600"
              title={`${PILLAR_SHORT[key] ?? key}: ${count}`}
            >
              {PILLAR_SHORT[key] ?? key}
              <span className="tabular-nums text-slate-400">{count}</span>
            </span>
          ))}
        </div>
        <span className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-accent-700 group-hover:gap-1.5">
          Открыть <ArrowRight className="h-3.5 w-3.5 transition-all" aria-hidden />
        </span>
      </div>
    </Link>
  );
}

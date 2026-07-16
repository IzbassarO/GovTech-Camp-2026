import Link from "next/link";
import { ArrowRight, Building2, MapPin } from "lucide-react";

import type { ProjectListItem } from "@/lib/types";
import { documentsWord, findingsWord } from "@/lib/ui";
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

      <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-4">
        <div className="flex gap-2">
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
        <span className="inline-flex items-center gap-1 text-xs font-medium text-accent-700 group-hover:gap-1.5">
          Открыть <ArrowRight className="h-3.5 w-3.5 transition-all" aria-hidden />
        </span>
      </div>
    </Link>
  );
}

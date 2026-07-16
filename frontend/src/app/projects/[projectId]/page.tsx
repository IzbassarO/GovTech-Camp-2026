"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Building2, ExternalLink, FileText, MapPin } from "lucide-react";

import type { ProjectDetail, ProjectSummary } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { SEVERITY_LABEL, SEVERITY_ORDER } from "@/lib/ui";
import {
  ErrorBlock,
  LoadingBlock,
  Section,
  SkeletonCard,
} from "@/components/primitives";
import { PillarCard } from "@/components/PillarCard";
import { FindingsExplorer } from "@/components/FindingsExplorer";
import { ReportModal } from "@/components/ReportModal";
import { DocumentsTable } from "@/components/DocumentsTable";
import { CoherenceView } from "@/components/CoherenceView";

export default function ProjectDetailPage() {
  const params = useParams<{ projectId: string }>();
  const projectId = params.projectId;

  const summary = useApi<ProjectSummary>(`/api/projects/${projectId}/summary`, [projectId]);
  const detail = useApi<ProjectDetail>(`/api/projects/${projectId}`, [projectId]);

  const [activePillar, setActivePillar] = useState("");
  const [reportPillar, setReportPillar] = useState<string | null>(null);
  const findingsRef = useRef<HTMLDivElement>(null);

  const openFindings = (pillarKey: string) => {
    setActivePillar(pillarKey);
    findingsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  if (summary.error) {
    return (
      <div className="space-y-4">
        <BackLink />
        <ErrorBlock message={summary.error} />
      </div>
    );
  }

  const s = summary.data;

  return (
    <div className="space-y-10">
      <div>
        <BackLink />
        {summary.loading || !s ? (
          <div className="mt-4 space-y-3">
            <div className="skeleton h-8 w-64" />
            <div className="skeleton h-4 w-96" />
          </div>
        ) : (
          <header className="mt-4">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
                  {s.name}
                </h1>
                <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-slate-500">
                  {s.region ? (
                    <span className="inline-flex items-center gap-1.5">
                      <MapPin className="h-4 w-4" aria-hidden />
                      {s.region}
                    </span>
                  ) : null}
                  {s.industry ? (
                    <span className="inline-flex items-center gap-1.5">
                      <Building2 className="h-4 w-4" aria-hidden />
                      {s.industry}
                    </span>
                  ) : null}
                  <span className="inline-flex items-center gap-1.5">
                    <FileText className="h-4 w-4" aria-hidden />
                    {s.document_count} документов
                  </span>
                </div>
              </div>
              <div className="rounded-lg bg-slate-100 px-4 py-3 text-right">
                <p className="text-xs text-slate-500">Замечаний всего</p>
                <p className="text-2xl font-semibold tabular-nums text-slate-900">
                  {s.findings_total}
                </p>
              </div>
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-4 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm">
              {SEVERITY_ORDER.map((sev) => (
                <span key={sev} className="text-slate-600">
                  {SEVERITY_LABEL[sev]}:{" "}
                  <span className="font-semibold tabular-nums text-slate-900">
                    {s.severity_counts[sev]}
                  </span>
                </span>
              ))}
              <span className="ml-auto rounded-md bg-slate-100 px-2.5 py-1 text-xs text-slate-500">
                {s.integrated_risk_note}
              </span>
            </div>
          </header>
        )}
      </div>

      <Section
        title="Пиллары анализа"
        description="Каждый пиллар оценивает отдельный аспект. Интегральная оценка не рассчитывается."
      >
        {summary.loading || !s ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {s.pillars.map((pillar) => (
                <PillarCard key={pillar.key} pillar={pillar} onOpenFindings={openFindings} />
              ))}
            </div>
            <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
              {s.reserved_pillars.map((rp) => (
                <div
                  key={rp.key}
                  className="rounded-xl border border-dashed border-slate-300 bg-slate-50/60 p-4"
                >
                  <div className="flex items-center gap-2">
                    <span className="chip bg-slate-200 text-slate-500">{rp.pillar_id}</span>
                    <p className="text-sm font-medium text-slate-600">{rp.title}</p>
                  </div>
                  <p className="mt-1.5 text-xs text-slate-500">{rp.description}</p>
                </div>
              ))}
            </div>
          </>
        )}
      </Section>

      {s ? <P4Section pillars={s.pillars} /> : null}

      <div ref={findingsRef} className="scroll-mt-20">
        <Section
          title="Замечания"
          description="Нажмите строку, чтобы открыть свидетельства. Все записи требуют экспертной проверки."
          action={
            <Link
              href={`/projects/${projectId}/findings`}
              className="text-sm font-medium text-accent-700 hover:underline"
            >
              Открыть отдельно →
            </Link>
          }
        >
          <FindingsExplorer
            key={activePillar}
            projectId={projectId}
            initialPillar={activePillar}
          />
        </Section>
      </div>

      <Section title="Документы пакета">
        {detail.error ? (
          <ErrorBlock message={detail.error} />
        ) : detail.loading || !detail.data ? (
          <LoadingBlock label="Загрузка документов…" />
        ) : (
          <DocumentsTable documents={detail.data.documents} />
        )}
      </Section>

      {s ? (
        <Section title="Отчёты и ограничения">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {s.pillars.map((pillar) => (
              <div key={pillar.key} className="card flex flex-col p-5">
                <p className="text-sm font-semibold text-slate-900">{pillar.title}</p>
                {pillar.limitations ? (
                  <p className="mt-2 flex-1 text-xs leading-relaxed text-slate-500">
                    {pillar.limitations}
                  </p>
                ) : (
                  <span className="flex-1" />
                )}
                <button
                  type="button"
                  onClick={() => setReportPillar(pillar.key)}
                  className="btn-ghost mt-4 self-start"
                >
                  Открыть отчёт
                </button>
              </div>
            ))}
          </div>
        </Section>
      ) : null}

      {detail.data?.source_url ? (
        <a
          href={detail.data.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 text-sm font-medium text-accent-700 hover:underline"
        >
          Источник документов (портал общественных слушаний)
          <ExternalLink className="h-3.5 w-3.5" aria-hidden />
        </a>
      ) : null}

      <ReportModal
        projectId={projectId}
        pillar={reportPillar}
        onClose={() => setReportPillar(null)}
      />
    </div>
  );
}

function BackLink() {
  return (
    <Link
      href="/projects"
      className="inline-flex items-center gap-1.5 text-sm font-medium text-slate-500 hover:text-slate-700"
    >
      <ArrowLeft className="h-4 w-4" aria-hidden />
      Все проекты
    </Link>
  );
}

function P4Section({ pillars }: { pillars: ProjectSummary["pillars"] }) {
  const p4 = pillars.find((p) => p.key === "p4");
  if (!p4 || !p4.available) return null;
  return (
    <Section
      title="P4 · Междокументная согласованность"
      description="Сопоставляет сведения о проекте, объектах, местоположении, деятельности и периодах между документами. Различия написания и транслитерации считаются алиасами, а не противоречиями."
    >
      <CoherenceView pillar={p4} />
    </Section>
  );
}

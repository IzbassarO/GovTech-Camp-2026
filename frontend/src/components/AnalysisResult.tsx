// Completion screen: shows BOTH the full registered source package and the
// detailed analyzed subset, the document → pillar coverage matrix and the
// Meta priority — all values artifact-backed, levels and factor titles in
// Russian, raw internal ids only inside "Технические детали".

import Link from "next/link";
import {
  ArrowRight,
  CheckCircle2,
  FolderOpen,
  Home,
  MessageSquareText,
  RotateCcw,
  Search,
  Table2,
} from "lucide-react";

import type { DemoJobResponse, DossierDocument } from "@/lib/types";
import { materialsWord, RECONCILED_STATUS_STYLE } from "@/lib/ui";
import { CoverageMatrix } from "@/components/CoverageMatrix";
import { PublicFeedbackPanel } from "@/components/DossierBuilder";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-slate-400">{label}</p>
      <p className="mt-0.5 text-lg font-semibold tabular-nums text-white sm:text-xl">{value}</p>
    </div>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{children}</p>
  );
}

function PackageDocumentChip({ document }: { document: DossierDocument }) {
  return (
    <li className="flex items-center justify-between gap-2 py-1.5">
      <span className="min-w-0 truncate text-xs text-slate-700">{document.safe_display_name}</span>
      <span className={`chip flex-none ${RECONCILED_STATUS_STYLE[document.reconciled_status]}`}>
        {document.status_label}
      </span>
    </li>
  );
}

export function PreparedReplayResult({
  job,
  restartHref,
}: {
  job: DemoJobResponse;
  restartHref: string;
}) {
  const metaStage = job.stages.find((s) => s.stage_id === "meta");
  const pillarStages = job.stages.filter((s) => ["p1", "p2", "p3", "p4"].includes(s.stage_id));
  const metric = (label: string) => metaStage?.metrics.find((m) => m.label === label)?.value ?? "—";
  const factorMetrics = metaStage?.metrics.filter((m) => m.hint) ?? [];

  const allDocuments = job.dossier.sections.flatMap((section) => section.documents);
  const analyzedDocuments = allDocuments.filter((d) => d.reconciled_status === "analyzed");
  const contextDocuments = allDocuments.filter((d) => d.reconciled_status !== "analyzed");

  return (
    <div className="space-y-5 rounded-2xl border border-accent-100 bg-white p-6 shadow-card">
      <div className="flex items-center gap-2 text-accent-700">
        <CheckCircle2 className="h-5 w-5" aria-hidden />
        <p className="text-xs font-semibold uppercase tracking-wide">Воспроизведение завершено</p>
      </div>

      <div>
        <h2 className="text-xl font-semibold text-slate-900">{job.project_name}</h2>
        <p className="mt-0.5 text-sm text-slate-500">
          Официальный пакет: {job.registered_source_count}{" "}
          {materialsWord(job.registered_source_count)} · в детальном анализе: {job.analyzed_count}{" "}
          · демонстрационная реплика принятых результатов
        </p>
      </div>

      {metaStage ? (
        <div className="grid grid-cols-2 gap-4 rounded-xl bg-navy-900 p-5 sm:grid-cols-4">
          <Stat label="Приоритет" value={metric("Приоритет проверки")} />
          <Stat label="Уровень" value={metric("Уровень")} />
          <Stat label="Покрытие" value={metric("Покрытие доказательств")} />
          <Stat label="Уверенность" value={metric("Уверенность оценки")} />
        </div>
      ) : null}

      {metaStage?.warning ? (
        <p className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2.5 text-xs font-medium leading-relaxed text-sky-900">
          {metaStage.warning}
        </p>
      ) : null}

      <p className="rounded-lg bg-slate-50 px-3 py-2.5 text-xs leading-relaxed text-slate-600">
        {job.analysis_scope_note}
      </p>

      {/* Source package vs analyzed subset — both visible, honestly labeled */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-200 p-4">
          <div className="flex items-center gap-2">
            <FolderOpen className="h-4 w-4 text-slate-400" aria-hidden />
            <SectionHeading>Пакет источника · {allDocuments.length}</SectionHeading>
          </div>
          <ul className="mt-2 divide-y divide-slate-100">
            {contextDocuments.map((document) => (
              <PackageDocumentChip key={document.document_id} document={document} />
            ))}
          </ul>
        </div>
        <div className="rounded-xl border border-accent-100 bg-accent-50/40 p-4">
          <div className="flex items-center gap-2">
            <Search className="h-4 w-4 text-accent-600" aria-hidden />
            <SectionHeading>Детальный анализ · {analyzedDocuments.length}</SectionHeading>
          </div>
          <ul className="mt-2 divide-y divide-accent-100/60">
            {analyzedDocuments.map((document) => (
              <li key={document.document_id} className="py-1.5">
                <p className="text-xs font-medium text-slate-800">{document.safe_display_name}</p>
                <p className="text-[11px] text-slate-500">
                  {[
                    document.page_count ? `${document.page_count} стр.` : null,
                    document.analyzed_by.join(" · "),
                    document.meta_evidence ? "Meta" : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Coverage matrix */}
      <div>
        <div className="flex items-center gap-2">
          <Table2 className="h-4 w-4 text-slate-400" aria-hidden />
          <SectionHeading>Покрытие документов пилларами</SectionHeading>
        </div>
        <div className="mt-2">
          <CoverageMatrix records={job.dossier.coverage_matrix} />
        </div>
      </div>

      <div>
        <SectionHeading>Сводка по пилларам</SectionHeading>
        <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {pillarStages.map((stage) => (
            <div key={stage.stage_id} className="rounded-lg border border-slate-200 p-3">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                {stage.pillar_id}
              </p>
              <p className="mt-0.5 text-sm text-slate-700">{stage.headline}</p>
              {stage.warning ? (
                <p className="mt-1 text-[11px] leading-snug text-amber-700">{stage.warning}</p>
              ) : null}
            </div>
          ))}
        </div>
      </div>

      {factorMetrics.length > 0 ? (
        <div>
          <SectionHeading>Сильнейшие факторы приоритета</SectionHeading>
          <ul className="mt-2 space-y-1.5">
            {factorMetrics.map((factor) => (
              <li key={factor.label} className="text-xs leading-relaxed text-slate-600">
                <span className="font-medium text-slate-800">{factor.label}</span>: {factor.value}
                {factor.hint ? <span className="text-slate-500"> — {factor.hint}</span> : null}
              </li>
            ))}
          </ul>
          <details className="mt-2">
            <summary className="cursor-pointer text-[11px] font-medium text-slate-400 hover:text-slate-600">
              Технические детали
            </summary>
            <ul className="mt-1.5 space-y-1">
              {metaStage?.metrics
                .filter((m) => m.technical_id)
                .map((m) => (
                  <li key={m.label} className="font-mono text-[11px] text-slate-500">
                    {m.technical_id} = {m.value}
                  </li>
                ))}
            </ul>
          </details>
        </div>
      ) : null}

      {/* Public feedback: registered honestly, not fed to pillars today */}
      {job.dossier.public_feedback ? (
        <div className="rounded-xl border border-slate-200">
          <div className="flex items-center gap-2 border-b border-slate-100 px-4 pt-3 pb-2">
            <MessageSquareText className="h-4 w-4 text-slate-400" aria-hidden />
            <SectionHeading>Вопросы и ответы общественности</SectionHeading>
          </div>
          <PublicFeedbackPanel feedback={job.dossier.public_feedback} />
        </div>
      ) : null}

      {job.limitations.length > 0 ? (
        <div className="space-y-1">
          {job.limitations.map((limitation) => (
            <p key={limitation} className="text-xs leading-relaxed text-slate-500">
              {limitation}
            </p>
          ))}
        </div>
      ) : null}

      {metaStage?.limitations ? (
        <p className="text-xs leading-relaxed text-slate-500">{metaStage.limitations}</p>
      ) : null}

      <div className="flex flex-wrap gap-3 border-t border-slate-100 pt-4">
        <Link href={job.result_url} className="btn-primary">
          Открыть полный результат
          <ArrowRight className="h-4 w-4" aria-hidden />
        </Link>
        <Link href={`${job.result_url}/findings`} className="btn-ghost">
          <Search className="h-4 w-4" aria-hidden />
          Посмотреть замечания
        </Link>
        <Link href={restartHref} className="btn-ghost">
          <RotateCcw className="h-4 w-4" aria-hidden />
          Открыть другой режим
        </Link>
        <Link href="/" className="btn-ghost">
          <Home className="h-4 w-4" aria-hidden />
          Вернуться на главную
        </Link>
      </div>
    </div>
  );
}

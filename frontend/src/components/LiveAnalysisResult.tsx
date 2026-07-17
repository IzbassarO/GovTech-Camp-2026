import Link from "next/link";
import { CheckCircle2, Home, Image as ImageIcon, RotateCcw, ShieldAlert } from "lucide-react";

import type {
  LiveDossierSectionId,
  LiveJobResponse,
  LivePillarResult,
} from "@/lib/types";
import {
  assessmentPercent,
  formatMetaNumber,
  reviewPriorityLabel,
  reviewPriorityStyle,
} from "@/lib/ui";

const PILLAR_RESULT_LABEL: Record<LivePillarResult["status"], string> = {
  completed: "Выполнено",
  unavailable: "Недоступно",
  insufficient_input: "Недостаточно данных",
  failed: "Ошибка",
};

const SECTION_LABEL: Record<LiveDossierSectionId, string> = {
  project_documents: "Проектная документация",
  official_supporting_documents: "Официальные решения и подтверждающие документы",
  hearing_protocol: "Протокол общественных слушаний",
  procedural_publication_evidence: "Подтверждение процедурной публикации",
  visual_geographic_materials: "Визуальные и географические материалы",
  public_feedback_metadata: "Структурированные данные обратной связи",
};

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-slate-400">{label}</p>
      <p className="mt-0.5 text-lg font-semibold tabular-nums text-white sm:text-xl">{value}</p>
    </div>
  );
}

export function LiveAnalysisResult({ job }: { job: LiveJobResponse }) {
  if (job.status !== "completed") return null;
  const pillarResults = Object.entries(job.result?.pillars ?? {});
  const inventory = job.result?.inventory;
  const preparation = job.result?.preparation;
  const meta = job.result?.meta ?? null;
  const limitations = Array.from(
    new Set([...(job.limitations ?? []), ...(job.result?.limitations ?? [])]),
  );

  return (
    <section className="space-y-5 rounded-2xl border border-accent-100 bg-white p-6 shadow-card">
      <div className="flex items-center gap-2 text-accent-700">
        <CheckCircle2 className="h-5 w-5" aria-hidden />
        <p className="text-xs font-semibold uppercase tracking-wide">Фактический анализ завершён</p>
      </div>

      <div>
        <h2 className="text-xl font-semibold text-slate-900">{job.project_display_name}</h2>
        <p className="mt-1 text-sm leading-relaxed text-slate-500">
          Результат сформирован только из документов временного задания. Недоступные проверки не
          заменялись чужими или подготовленными артефактами.
        </p>
      </div>

      {inventory ? (
        <div className="space-y-3 rounded-xl border border-slate-200 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Итог P0 · состав пакета
            </h3>
            <span className="chip bg-sky-50 text-sky-700 ring-1 ring-inset ring-sky-200">
              {inventory.supplied_sections.length}/{inventory.expected_sections.length} разделов
            </span>
          </div>
          <p className="text-xs leading-relaxed text-slate-600">{inventory.package_readiness}</p>
          {inventory.missing_sections.length > 0 ? (
            <p className="text-xs leading-relaxed text-amber-700">
              Не представлены: {inventory.missing_sections.map((section) => SECTION_LABEL[section]).join(", ")}.
            </p>
          ) : null}
          {inventory.unsupported_materials.map((material) => (
            <p key={material} className="text-xs leading-relaxed text-red-700">
              Неподдерживаемый материал: {material}
            </p>
          ))}
          {inventory.duplicate_files.length > 0 ? (
            <p className="text-xs leading-relaxed text-amber-700">
              Дубликаты: {inventory.duplicate_files.join(", ")}.
            </p>
          ) : null}
        </div>
      ) : null}

      {meta ? (
        <>
          <div className="grid grid-cols-2 gap-4 rounded-xl bg-navy-900 p-5 sm:grid-cols-4">
            <Stat
              label="Приоритет проверки"
              value={`${formatMetaNumber(meta.review_priority_score, 1)}/100`}
            />
            <Stat label="Уровень" value={reviewPriorityLabel(meta.review_priority_level)} />
            <Stat
              label="Покрытие"
              value={`${formatMetaNumber(assessmentPercent(meta.evidence_coverage), 0)}%`}
            />
            <Stat
              label="Уверенность"
              value={`${formatMetaNumber(assessmentPercent(meta.assessment_confidence), 0)}%`}
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={`chip ${reviewPriorityStyle(meta.review_priority_level)}`}>
              {meta.primary_label}
            </span>
            <p className="text-xs leading-relaxed text-slate-500">{meta.review_notice}</p>
          </div>
        </>
      ) : (
        <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
          <ShieldAlert className="mt-0.5 h-4 w-4 flex-none text-amber-700" aria-hidden />
          <p className="text-xs leading-relaxed text-amber-800">
            Meta не рассчитана: доступных результатов пилларов недостаточно. Отсутствующие проверки
            не считаются нулевым риском.
          </p>
        </div>
      )}

      {preparation ? (
        <div className="grid grid-cols-2 gap-3 rounded-xl border border-slate-200 p-4 sm:grid-cols-5">
          <div>
            <p className="text-[10px] uppercase tracking-wide text-slate-400">Документов</p>
            <p className="text-lg font-semibold tabular-nums text-slate-900">
              {preparation.document_count}
            </p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wide text-slate-400">Подготовлено</p>
            <p className="text-lg font-semibold tabular-nums text-slate-900">
              {preparation.prepared_document_count}
            </p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wide text-slate-400">Страниц</p>
            <p className="text-lg font-semibold tabular-nums text-slate-900">
              {preparation.page_count}
            </p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wide text-slate-400">Визуальных активов</p>
            <p className="text-lg font-semibold tabular-nums text-slate-900">
              {preparation.extracted_visual_asset_count}
            </p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wide text-slate-400">Ошибок извлечения</p>
            <p className="text-lg font-semibold tabular-nums text-slate-900">
              {preparation.extraction_failure_count}
            </p>
          </div>
        </div>
      ) : null}

      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Результаты P1–P4
        </h3>
        <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {pillarResults.map(([pillarKey, pillar]) => (
            <div key={pillarKey} className="rounded-lg border border-slate-200 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="chip bg-navy-900 px-2 py-0.5 text-[10px] text-white">
                  {(pillar.pillar_id ?? pillarKey).toUpperCase()}
                </span>
                <span className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
                  {PILLAR_RESULT_LABEL[pillar.status]}
                </span>
              </div>
              <p className="mt-2 text-sm text-slate-700">
                {pillar.reason ?? "Этап завершён без дополнительного описания."}
              </p>
              {Object.keys(pillar.metrics ?? {}).length > 0 ? (
                <dl className="mt-2 grid grid-cols-2 gap-2">
                  {Object.entries(pillar.metrics ?? {})
                    .slice(0, 6)
                    .map(([label, value]) => (
                      <div key={label}>
                        <dt className="text-[10px] uppercase tracking-wide text-slate-400">
                          {label.replaceAll("_", " ")}
                        </dt>
                        <dd className="text-xs font-semibold tabular-nums text-slate-800">
                          {value === null ? "—" : String(value)}
                        </dd>
                      </div>
                    ))}
                </dl>
              ) : null}
              {(pillar.warnings ?? []).map((warning) => (
                <p key={warning} className="mt-1 text-[11px] leading-relaxed text-amber-700">
                  {warning}
                </p>
              ))}
              {(pillar.limitations ?? []).map((limitation) => (
                <p key={limitation} className="mt-1 text-[11px] leading-relaxed text-slate-500">
                  {limitation}
                </p>
              ))}
            </div>
          ))}
          {pillarResults.length === 0 ? (
            <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-relaxed text-amber-800 sm:col-span-2">
              Детальные результаты пилларов недоступны; успешные результаты не подставлялись.
            </p>
          ) : null}
        </div>
      </div>

      <div className="flex items-start gap-2 rounded-lg bg-slate-50 px-3 py-2.5">
        <ImageIcon className="mt-0.5 h-4 w-4 flex-none text-slate-400" aria-hidden />
        <p className="text-xs leading-relaxed text-slate-500">
          Визуальные материалы инвентаризированы, но P5 и P6 пока недоступны и не влияют на Meta.
          Автоматически сгенерированное объяснение также не создаётся.
        </p>
      </div>

      {limitations.length > 0 ? (
        <div className="space-y-1">
          {limitations.map((limitation) => (
            <p key={limitation} className="text-xs leading-relaxed text-slate-500">
              {limitation}
            </p>
          ))}
        </div>
      ) : null}

      <div className="flex flex-wrap gap-3 border-t border-slate-100 pt-4">
        <Link href="/analyze/live" className="btn-primary">
          <RotateCcw className="h-4 w-4" aria-hidden />
          Создать новый анализ
        </Link>
        <Link href="/" className="btn-ghost">
          <Home className="h-4 w-4" aria-hidden />
          На главную
        </Link>
      </div>
    </section>
  );
}

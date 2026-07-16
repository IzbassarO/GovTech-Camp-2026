import {
  AlertTriangle,
  BarChart3,
  ChevronDown,
  Database,
  Gauge,
  Info,
  LockKeyhole,
} from "lucide-react";

import type {
  MetaAdjustment,
  MetaFeatureContribution,
  ProjectMetaAssessment,
} from "@/lib/types";
import {
  assessmentPercent,
  formatMetaNumber,
  reviewPriorityLabel,
  reviewPriorityStyle,
} from "@/lib/ui";

const PILLAR_LABEL: Record<string, string> = {
  P1: "Целостность документов",
  P2: "Регуляторное соответствие",
  P3: "Количественная согласованность",
  P4: "Междокументная согласованность",
};

const PILLAR_BAR: Record<string, string> = {
  P1: "bg-sky-500",
  P2: "bg-amber-500",
  P3: "bg-violet-500",
  P4: "bg-accent-600",
};

export function MetaDisclaimer() {
  return (
    <div className="flex items-start gap-2.5 rounded-lg border border-sky-200 bg-sky-50 px-4 py-3">
      <Info className="mt-0.5 h-4 w-4 flex-none text-sky-700" aria-hidden />
      <p className="text-xs font-medium leading-relaxed text-sky-900">
        Это приоритет экспертной проверки, а не вероятность нарушения. Оценка помогает
        определить очерёдность изучения пакетов и не является выводом о юридическом
        соответствии, экологической безопасности или выдаче разрешения.
      </p>
    </div>
  );
}

export function MetaAssessmentView({ meta }: { meta: ProjectMetaAssessment }) {
  const coverage = assessmentPercent(meta.evidence_coverage);
  const confidence = assessmentPercent(meta.assessment_confidence);
  const p2Contribution = meta.pillar_contributions.find(
    (pillar) => pillar.pillar_id === "P2",
  );
  const maxPillarContribution = Math.max(
    1,
    ...meta.pillar_contributions.map((pillar) => Math.abs(pillar.adjusted_subtotal)),
  );
  const adjustedPillarSum = meta.pillar_contributions.reduce(
    (total, pillar) => total + pillar.adjusted_subtotal,
    0,
  );
  const factors = selectTopFactors(meta);
  const topFactorIds = new Set(factors.map((factor) => factor.contribution_id));
  const remainingFactors = meta.feature_contributions.filter(
    (factor) => !topFactorIds.has(factor.contribution_id),
  );

  return (
    <div className="space-y-4">
      <MetaDisclaimer />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <article className="overflow-hidden rounded-xl bg-navy-900 p-6 text-white shadow-card">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-accent-500">
                <Gauge className="h-4 w-4" aria-hidden />
                Meta · P1–P4
              </p>
              <p className="mt-3 text-sm text-slate-300">
                Интегральная приоритетность проверки
              </p>
              <p className="mt-1 text-5xl font-semibold tracking-tight tabular-nums">
                {formatMetaNumber(meta.review_priority_score, 4)}
                <span className="ml-1 text-lg font-medium text-slate-400">/100</span>
              </p>
            </div>
            <span className={`chip ${reviewPriorityStyle(meta.review_priority_level)}`}>
              {reviewPriorityLabel(meta.review_priority_level)}
            </span>
          </div>

          <dl className="mt-6 grid grid-cols-2 gap-3 border-t border-navy-700 pt-4 text-xs">
            <div>
              <dt className="text-slate-400">Базовая оценка</dt>
              <dd className="mt-1 font-semibold tabular-nums text-white">
                {formatMetaNumber(meta.base_score, 4)}
              </dd>
            </div>
            <div>
              <dt className="text-slate-400">Сумма вкладов P1–P4</dt>
              <dd className="mt-1 font-semibold tabular-nums text-white">
                {formatMetaNumber(adjustedPillarSum, 4)}
              </dd>
            </div>
            <div>
              <dt className="text-slate-400">Факторы до корректировок</dt>
              <dd className="mt-1 font-semibold tabular-nums text-white">
                {formatMetaNumber(meta.raw_feature_total, 4)}
              </dd>
            </div>
            <div>
              <dt className="text-slate-400">Итог после корректировок</dt>
              <dd className="mt-1 font-semibold tabular-nums text-white">
                {formatMetaNumber(meta.final_score, 4)}
              </dd>
            </div>
          </dl>
          <p className="mt-4 rounded-lg bg-navy-800 px-3 py-2.5 text-[11px] leading-relaxed text-slate-300">
            Проверка арифметики: {formatMetaNumber(meta.base_score, 4)} +{" "}
            {formatMetaNumber(adjustedPillarSum, 4)} + ({formatMetaNumber(meta.uncertainty_adjustment, 4)}) + ({formatMetaNumber(meta.global_cap_adjustment, 4)}) ={" "}
            <span className="font-semibold tabular-nums text-white">
              {formatMetaNumber(meta.final_score, 4)}
            </span>
            <span className="mt-1 block text-slate-400">
              база + P1–P4 + неопределённость + общий лимит = итог
            </span>
          </p>
        </article>

        <article className="card p-6">
          <h3 className="text-sm font-semibold text-slate-900">Доказательность оценки</h3>
          <div className="mt-5 space-y-5">
            <AssessmentMeter
              label="Покрытие доказательств"
              value={coverage}
              hint="Доля релевантного анализа, которую удалось выполнить по доступным артефактам."
            />
            <AssessmentMeter
              label="Уверенность оценки"
              value={confidence}
              hint="Надёжность приоритета с учётом пропусков, подавленных сравнений и демонстрационных источников."
            />
          </div>
          <p className="mt-5 rounded-lg bg-slate-50 px-3 py-2.5 text-xs leading-relaxed text-slate-600">
            Низкое покрытие снижает уверенность, но не означает низкий приоритет и не
            считается признаком безопасности.
          </p>
          <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
            {meta.available_pillars.map((pillar) => (
              <span key={pillar} className="chip bg-accent-50 text-accent-700">
                {pillar} доступен
              </span>
            ))}
            {meta.missing_pillars.map((pillar) => (
              <span key={pillar} className="chip bg-amber-50 text-amber-800">
                {pillar} недоступен
              </span>
            ))}
          </div>
        </article>
      </div>

      <article className="card p-6">
        <div className="flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-accent-700" aria-hidden />
          <h3 className="text-sm font-semibold text-slate-900">Вклад пилларов P1–P4</h3>
        </div>
        <p className="mt-1 text-xs text-slate-500">
          Горизонтальные полосы показывают относительный размер вклада; точные значения
          приведены справа.
        </p>

        <div className="mt-5 grid gap-5 lg:grid-cols-2">
          {meta.pillar_contributions.map((pillar) => (
            <div key={pillar.pillar_id} className="rounded-lg border border-slate-200 p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                    {pillar.pillar_id}
                  </p>
                  <p className="mt-0.5 text-sm font-medium text-slate-800">
                    {PILLAR_LABEL[pillar.pillar_id] ?? pillar.pillar_id}
                  </p>
                </div>
                {pillar.available ? (
                  <span className="font-semibold tabular-nums text-slate-900">
                    {formatSigned(pillar.adjusted_subtotal)}
                  </span>
                ) : (
                  <span className="chip bg-slate-100 text-slate-500">Недоступен</span>
                )}
              </div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100">
                <span
                  className={`block h-full rounded-full ${PILLAR_BAR[pillar.pillar_id] ?? "bg-slate-500"}`}
                  style={{
                    width: pillar.available
                      ? `${(Math.abs(pillar.adjusted_subtotal) / maxPillarContribution) * 100}%`
                      : "0%",
                  }}
                  aria-hidden
                />
              </div>
              <dl className="mt-3 grid grid-cols-3 gap-2 text-[11px]">
                <div>
                  <dt className="text-slate-400">До корректировок</dt>
                  <dd className="mt-0.5 font-medium tabular-nums text-slate-700">
                    {formatMetaNumber(pillar.raw_subtotal, 4)}
                  </dd>
                </div>
                <div>
                  <dt className="text-slate-400">Дисконт</dt>
                  <dd className="mt-0.5 font-medium tabular-nums text-slate-700">
                    {pillar.discount_applied
                      ? `${formatSigned(pillar.discount_amount)} · ×${formatMetaNumber(pillar.discount_factor, 4)}`
                      : "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-slate-400">Лимит вклада</dt>
                  <dd className="mt-0.5 font-medium tabular-nums text-slate-700">
                    {pillar.cap_applied
                      ? `${formatSigned(pillar.cap_amount)} · ≤${formatMetaNumber(pillar.cap, 4)}`
                      : `≤${formatMetaNumber(pillar.cap, 4)}`}
                  </dd>
                </div>
              </dl>
              {pillar.explanation ? (
                <p className="mt-3 text-xs leading-relaxed text-slate-500">
                  {pillar.explanation}
                </p>
              ) : null}
            </div>
          ))}
        </div>

        {p2Contribution?.available ? (
          <div className="mt-5 flex items-start gap-2.5 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
            <AlertTriangle className="mt-0.5 h-4 w-4 flex-none text-amber-700" aria-hidden />
            <div>
              <p className="text-xs font-semibold text-amber-900">
                P2 · Вклад ограничен: используется демонстрационный нормативный корпус.
              </p>
              <p className="mt-1 text-xs leading-relaxed text-amber-800">
                Синтетический корпус не является официальным источником права, поэтому P2
                не может доминировать в итоговой оценке.
              </p>
            </div>
          </div>
        ) : null}
      </article>

      <article className="card p-6">
        <h3 className="text-sm font-semibold text-slate-900">Факторы итоговой оценки</h3>
        <p className="mt-1 text-xs leading-relaxed text-slate-500">
          Сначала показаны наиболее влиятельные точные вклады детерминированного алгоритма,
          а не SHAP-значения. Раскройте фактор, чтобы увидеть исходные значения и ссылки на
          свидетельства; полный список доступен ниже.
        </p>

        {factors.length > 0 ? (
          <div className="mt-4 divide-y divide-slate-100 rounded-lg border border-slate-200">
            {factors.map((factor, index) => (
              <FactorDetails
                key={factor.contribution_id}
                factor={factor}
                initiallyOpen={index === 0}
              />
            ))}
          </div>
        ) : (
          <p className="mt-4 rounded-lg bg-slate-50 px-4 py-3 text-xs text-slate-500">
            Положительные факторы для отображения отсутствуют.
          </p>
        )}

        {remainingFactors.length > 0 ? (
          <details className="group/all mt-4 rounded-lg border border-slate-200 bg-slate-50/50">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-xs font-medium text-slate-700">
              <span>Все остальные факторы ({remainingFactors.length})</span>
              <ChevronDown
                className="h-4 w-4 text-slate-400 transition-transform group-open/all:rotate-180"
                aria-hidden
              />
            </summary>
            <div className="divide-y divide-slate-100 border-t border-slate-200 bg-white">
              {remainingFactors.map((factor) => (
                <FactorDetails
                  key={factor.contribution_id}
                  factor={factor}
                  initiallyOpen={false}
                />
              ))}
            </div>
          </details>
        ) : null}

        <p className="mt-4 text-xs leading-relaxed text-slate-500">
          {meta.counterfactual_explanation}
        </p>
      </article>

      <div className="grid gap-4 lg:grid-cols-2">
        <article className="card p-6">
          <h3 className="text-sm font-semibold text-slate-900">Ограничения и корректировки</h3>
          <AdjustmentGroup title="Применённые ограничения" items={meta.caps_applied} />
          <AdjustmentGroup title="Применённые дисконты" items={meta.discounts_applied} />
          <AdjustmentGroup
            title="Корректировки неопределённости"
            items={meta.uncertainty_adjustments}
          />
          {meta.limitations.length > 0 ? (
            <div className="mt-5">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                Ограничения оценки
              </p>
              <ul className="mt-2 space-y-2">
                {meta.limitations.map((limitation) => (
                  <li key={limitation} className="flex items-start gap-2 text-xs text-slate-600">
                    <span className="mt-1.5 h-1 w-1 flex-none rounded-full bg-slate-400" />
                    <span>{limitation}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </article>

        <article className="card p-6">
          <div className="flex items-center gap-2">
            <LockKeyhole className="h-4 w-4 text-slate-500" aria-hidden />
            <h3 className="text-sm font-semibold text-slate-900">Калибровка и модель</h3>
          </div>
          <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
            <p className="text-sm font-medium text-slate-800">
              Калибровка недоступна без достаточной экспертной разметки.
            </p>
            <p className="mt-2 text-xs leading-relaxed text-slate-600">
              Калиброванная вероятность не рассчитывается. SHAP-вклады не формируются:
              текущая производственная оценка является прозрачной детерминированной суммой.
            </p>
            <div className="mt-3 flex items-center gap-2 text-[11px] text-slate-500">
              <Database className="h-3.5 w-3.5" aria-hidden />
              <span>Статус: {calibrationStatusLabel(meta.calibration_status)}</span>
            </div>
            {meta.scoring_config_version ? (
              <p className="mt-2 text-[11px] text-slate-500">
                Версия правил: {meta.scoring_config_version}
              </p>
            ) : null}
          </div>
        </article>
      </div>
    </div>
  );
}

function AssessmentMeter({
  label,
  value,
  hint,
}: {
  label: string;
  value: number;
  hint: string;
}) {
  return (
    <div>
      <div className="flex items-end justify-between gap-3">
        <p className="text-xs font-medium text-slate-700">{label}</p>
        <p className="text-lg font-semibold tabular-nums text-slate-900">
          {formatMetaNumber(value, 2)}%
        </p>
      </div>
      <div
        className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value}
      >
        <span
          className="block h-full rounded-full bg-accent-600"
          style={{ width: `${value}%` }}
        />
      </div>
      <p className="mt-1.5 text-[11px] leading-relaxed text-slate-500">{hint}</p>
    </div>
  );
}

function FactorDetails({
  factor,
  initiallyOpen,
}: {
  factor: MetaFeatureContribution;
  initiallyOpen: boolean;
}) {
  const references = [...factor.source_finding_ids, ...factor.source_artifact_ids];
  return (
    <details className="group p-4" open={initiallyOpen}>
      <summary className="flex cursor-pointer list-none items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-sm font-medium text-slate-800">
            {factor.explanation || humanizeFeatureName(factor.feature_name)}
          </p>
          <p className="mt-1 font-mono text-[10px] text-slate-400">
            {factor.pillar_id} · {factor.feature_name}
          </p>
        </div>
        <div className="flex flex-none items-center gap-2">
          <span className="font-semibold tabular-nums text-slate-900">
            {formatSigned(factor.contribution)}
          </span>
          <ChevronDown
            className="h-4 w-4 text-slate-400 transition-transform group-open:rotate-180"
            aria-hidden
          />
        </div>
      </summary>
      <div className="mt-4 border-t border-slate-100 pt-4">
        <dl className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-3 lg:grid-cols-5">
          <div>
            <dt className="text-slate-400">Исходное значение</dt>
            <dd className="mt-0.5 font-semibold tabular-nums text-slate-700">
              {formatRawValue(factor.raw_value)}
            </dd>
          </div>
          <div>
            <dt className="text-slate-400">Нормализовано</dt>
            <dd className="mt-0.5 font-semibold tabular-nums text-slate-700">
              {formatMetaNumber(factor.normalized_value, 6)}
            </dd>
          </div>
          <div>
            <dt className="text-slate-400">Вес</dt>
            <dd className="mt-0.5 font-semibold tabular-nums text-slate-700">
              {formatMetaNumber(factor.weight, 6)}
            </dd>
          </div>
          <div>
            <dt className="text-slate-400">До корректировок</dt>
            <dd className="mt-0.5 font-semibold tabular-nums text-slate-700">
              {formatSigned(factor.raw_contribution, 6)}
            </dd>
          </div>
          <div>
            <dt className="text-slate-400">Итоговый вклад</dt>
            <dd className="mt-0.5 font-semibold tabular-nums text-slate-700">
              {formatSigned(factor.contribution, 6)}
            </dd>
          </div>
        </dl>

        <div className="mt-4">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            Ссылки на свидетельства
          </p>
          {references.length > 0 ? (
            <ul className="mt-2 flex flex-wrap gap-2">
              {references.map((reference) => (
                <li
                  key={reference}
                  className="max-w-full break-all rounded-md bg-slate-100 px-2 py-1 font-mono text-[10px] text-slate-600"
                >
                  {reference}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-xs text-slate-500">Ссылки для этого агрегата не указаны.</p>
          )}
        </div>

        {factor.limitations.length > 0 ? (
          <p className="mt-3 text-xs leading-relaxed text-slate-500">
            Ограничения: {factor.limitations.join(" · ")}
          </p>
        ) : null}
      </div>
    </details>
  );
}

function AdjustmentGroup({ title, items }: { title: string; items: MetaAdjustment[] }) {
  const appliedItems = items.filter(
    (item) => item.applied && Math.abs(item.amount) > Number.EPSILON,
  );
  if (appliedItems.length === 0) return null;
  return (
    <div className="mt-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{title}</p>
      <ul className="mt-2 space-y-2">
        {appliedItems.map((item) => (
          <li
            key={item.adjustment_id ?? `${item.pillar_id}:${item.name}:${item.amount}`}
            className="rounded-lg bg-slate-50 px-3 py-2.5"
          >
            <div className="flex items-start justify-between gap-3 text-xs">
              <span className="font-medium text-slate-700">
                {item.pillar_id ? `${item.pillar_id} · ` : ""}
                {adjustmentName(item)}
              </span>
              <span className="font-semibold tabular-nums text-slate-800">
                {formatSigned(item.amount, 4)}
              </span>
            </div>
            {localizedAdjustmentExplanation(item) ? (
              <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
                {localizedAdjustmentExplanation(item)}
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function selectTopFactors(meta: ProjectMetaAssessment): MetaFeatureContribution[] {
  if (meta.top_positive_factors.length > 0) return meta.top_positive_factors;
  return [...meta.feature_contributions]
    .filter((factor) => factor.contribution > 0)
    .sort((left, right) => {
      if (left.contribution !== right.contribution) {
        return right.contribution - left.contribution;
      }
      const leftKey = `${left.pillar_id}:${left.feature_name}`;
      const rightKey = `${right.pillar_id}:${right.feature_name}`;
      return leftKey < rightKey ? -1 : leftKey > rightKey ? 1 : 0;
    })
    .slice(0, 6);
}

function formatSigned(value: number, maximumFractionDigits = 4): string {
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${formatMetaNumber(value, maximumFractionDigits)}`;
}

function formatRawValue(value: MetaFeatureContribution["raw_value"]): string {
  if (value == null) return "—";
  if (typeof value === "boolean") return value ? "да" : "нет";
  if (typeof value === "number") return formatMetaNumber(value, 6);
  return value;
}

function humanizeFeatureName(value: string): string {
  const normalized = value.replaceAll("_", " ").trim();
  return normalized.length > 0
    ? `${normalized.charAt(0).toUpperCase()}${normalized.slice(1)}`
    : value;
}

function calibrationStatusLabel(status: string): string {
  if (status === "not_available_without_expert_labels") {
    return "нет достаточной экспертной разметки";
  }
  return status;
}

function adjustmentName(item: MetaAdjustment): string {
  const normalized = item.name.toLowerCase();
  if (normalized.includes("cap")) return "Ограничение вклада";
  if (normalized.includes("discount")) return "Дисконт источника";
  if (normalized.includes("uncertainty")) return "Учёт неопределённости";
  return item.name;
}

function localizedAdjustmentExplanation(item: MetaAdjustment): string {
  const normalized = item.name.toLowerCase();
  if (normalized.includes("discount") && item.pillar_id === "P2") {
    return "Вклад P2 снижен из-за синтетического неавторитетного корпуса.";
  }
  if (normalized.includes("cap") && item.pillar_id === "P2") {
    return "Лимит не позволяет демонстрационному P2 доминировать в итоговой оценке.";
  }
  if (normalized.includes("cap") && item.pillar_id) {
    return "Вклад одного пиллара ограничен, чтобы он не определял итог единолично.";
  }
  if (normalized.includes("uncertainty")) {
    return "Покрытие и неопределённость влияют на уверенность, а не скрыто уменьшают приоритет.";
  }
  return item.explanation;
}

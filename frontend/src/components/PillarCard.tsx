import { CheckCircle2, FileText, Scale, Sigma } from "lucide-react";

import type { PillarSummary } from "@/lib/types";
import { DemoBanner, StatusPill } from "@/components/primitives";

const PILLAR_ICON: Record<string, typeof FileText> = {
  p1: FileText,
  p2: Scale,
  p3: Sigma,
};

export function PillarCard({
  pillar,
  onOpenFindings,
}: {
  pillar: PillarSummary;
  onOpenFindings?: (pillarKey: string) => void;
}) {
  const Icon = PILLAR_ICON[pillar.key] ?? FileText;
  const clear = pillar.status === "clear";

  return (
    <article className="card flex flex-col p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <span
            className={`flex h-10 w-10 items-center justify-center rounded-lg ${
              clear ? "bg-accent-50 text-accent-600" : "bg-navy-900 text-white"
            }`}
          >
            <Icon className="h-5 w-5" aria-hidden />
          </span>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              {pillar.pillar_id}
            </p>
            <h3 className="text-sm font-semibold text-slate-900">{pillar.title}</h3>
          </div>
        </div>
        <StatusPill status={pillar.status} />
      </div>

      <p className="mt-3 flex items-center gap-2 text-sm font-medium text-slate-700">
        {clear ? (
          <CheckCircle2 className="h-4 w-4 flex-none text-accent-600" aria-hidden />
        ) : null}
        <span>{pillar.headline}</span>
      </p>

      {pillar.warning ? (
        <div className="mt-3">
          <DemoBanner text={pillar.warning} />
        </div>
      ) : null}

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3">
        {pillar.metrics.map((metric) => (
          <div key={metric.label}>
            <dt className="text-xs text-slate-500">{metric.label}</dt>
            <dd className="text-sm font-semibold tabular-nums text-slate-900" title={metric.hint ?? undefined}>
              {metric.value}
            </dd>
          </div>
        ))}
      </dl>

      {pillar.empty_state ? (
        <p className="mt-4 rounded-lg bg-accent-50 px-3 py-2 text-xs leading-relaxed text-accent-700">
          {pillar.empty_state}
        </p>
      ) : null}

      <div className="mt-auto flex items-center justify-between pt-4">
        {pillar.score != null ? (
          <div className="text-xs text-slate-500">
            {pillar.score_label}:{" "}
            <span className="font-semibold text-slate-800">
              {pillar.score}
              <span className="text-slate-400">/{pillar.score_max}</span>
            </span>
          </div>
        ) : (
          <span />
        )}
        {onOpenFindings && pillar.available ? (
          <button
            type="button"
            onClick={() => onOpenFindings(pillar.key)}
            className="text-xs font-medium text-accent-700 hover:text-accent-600 hover:underline"
          >
            {pillar.finding_count > 0 ? "Показать замечания →" : "Открыть результаты →"}
          </button>
        ) : null}
      </div>
    </article>
  );
}

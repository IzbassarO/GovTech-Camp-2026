import type { ReactNode } from "react";
import { AlertTriangle, Inbox, Loader2 } from "lucide-react";

import type { Severity, SeverityCounts } from "@/lib/types";
import {
  SEVERITY_BADGE,
  SEVERITY_DOT,
  SEVERITY_LABEL,
  SEVERITY_ORDER,
  STATUS_LABEL,
  STATUS_STYLE,
  type PillarStatus,
} from "@/lib/ui";

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={`chip ${SEVERITY_BADGE[severity]}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${SEVERITY_DOT[severity]}`} aria-hidden />
      {SEVERITY_LABEL[severity]}
    </span>
  );
}

export function StatusPill({ status }: { status: PillarStatus }) {
  return <span className={`chip ${STATUS_STYLE[status]}`}>{STATUS_LABEL[status]}</span>;
}

export function SeverityBar({ counts }: { counts: SeverityCounts }) {
  const total = counts.high + counts.medium + counts.low + counts.info;
  if (total === 0) {
    return <span className="text-xs text-slate-400">—</span>;
  }
  return (
    <div className="flex items-center gap-2">
      <div className="flex h-1.5 w-24 overflow-hidden rounded-full bg-slate-100">
        {SEVERITY_ORDER.map((sev) => {
          const value = counts[sev];
          if (value === 0) return null;
          return (
            <span
              key={sev}
              className={SEVERITY_DOT[sev]}
              style={{ width: `${(value / total) * 100}%` }}
              aria-hidden
            />
          );
        })}
      </div>
      <span className="text-xs tabular-nums text-slate-500">{total}</span>
    </div>
  );
}

export function DemoBanner({ text }: { text: string }) {
  return (
    <div className="flex items-start gap-2.5 rounded-lg border border-amber-200 bg-amber-50 px-3.5 py-2.5">
      <AlertTriangle className="mt-0.5 h-4 w-4 flex-none text-amber-600" aria-hidden />
      <p className="text-xs font-medium leading-relaxed text-amber-800">{text}</p>
    </div>
  );
}

export function LoadingBlock({ label = "Загрузка результатов анализа…" }: { label?: string }) {
  return (
    <div
      className="flex items-center justify-center gap-3 rounded-xl border border-slate-200 bg-white py-16 text-slate-500"
      role="status"
      aria-live="polite"
    >
      <Loader2 className="h-5 w-5 animate-spin text-accent-600" aria-hidden />
      <span className="text-sm">{label}</span>
    </div>
  );
}

export function ErrorBlock({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-red-200 bg-red-50 py-14 text-center">
      <AlertTriangle className="h-6 w-6 text-red-500" aria-hidden />
      <p className="text-sm font-medium text-red-800">Не удалось загрузить результаты проекта.</p>
      <p className="max-w-md text-xs text-red-600">{message}</p>
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-slate-300 bg-slate-50/60 py-12 text-center">
      <Inbox className="h-6 w-6 text-accent-500" aria-hidden />
      <p className="text-sm font-medium text-slate-700">{title}</p>
      {hint ? <p className="max-w-md text-xs text-slate-500">{hint}</p> : null}
    </div>
  );
}

export function SkeletonCard() {
  return (
    <div className="card space-y-3 p-5">
      <div className="skeleton h-4 w-1/3" />
      <div className="skeleton h-8 w-2/3" />
      <div className="skeleton h-3 w-full" />
      <div className="skeleton h-3 w-4/5" />
    </div>
  );
}

export function Section({
  title,
  description,
  action,
  children,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-slate-900">{title}</h2>
          {description ? <p className="mt-1 text-sm text-slate-500">{description}</p> : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

import type { ProjectListItem, ReviewPriorityLevel, Severity } from "./types";

export const SEVERITY_LABEL: Record<Severity, string> = {
  high: "Высокая",
  medium: "Средняя",
  low: "Низкая",
  info: "Инфо",
};

// Severity badge styles (light background + strong text; readable, no neon).
export const SEVERITY_BADGE: Record<Severity, string> = {
  high: "bg-red-100 text-red-800 ring-1 ring-inset ring-red-200",
  medium: "bg-amber-100 text-amber-800 ring-1 ring-inset ring-amber-200",
  low: "bg-sky-100 text-sky-800 ring-1 ring-inset ring-sky-200",
  info: "bg-slate-100 text-slate-700 ring-1 ring-inset ring-slate-200",
};

export const SEVERITY_DOT: Record<Severity, string> = {
  high: "bg-red-500",
  medium: "bg-amber-500",
  low: "bg-sky-500",
  info: "bg-slate-400",
};

export const SEVERITY_ORDER: Severity[] = ["high", "medium", "low", "info"];

export const REVIEW_PRIORITY_LABEL: Record<ReviewPriorityLevel, string> = {
  low: "Низкая",
  moderate: "Умеренная",
  elevated: "Повышенная",
  high: "Высокая",
};

export const REVIEW_PRIORITY_STYLE: Record<ReviewPriorityLevel, string> = {
  low: "bg-accent-50 text-accent-700 ring-1 ring-inset ring-accent-100",
  moderate: "bg-sky-50 text-sky-700 ring-1 ring-inset ring-sky-200",
  elevated: "bg-amber-50 text-amber-800 ring-1 ring-inset ring-amber-200",
  high: "bg-red-50 text-red-800 ring-1 ring-inset ring-red-200",
};

export function reviewPriorityLabel(level: string): string {
  return level in REVIEW_PRIORITY_LABEL
    ? REVIEW_PRIORITY_LABEL[level as ReviewPriorityLevel]
    : "Не определена";
}

export function reviewPriorityStyle(level: string): string {
  return level in REVIEW_PRIORITY_STYLE
    ? REVIEW_PRIORITY_STYLE[level as ReviewPriorityLevel]
    : "bg-slate-100 text-slate-600 ring-1 ring-inset ring-slate-200";
}

export function assessmentPercent(value: number): number {
  const percent = value <= 1 ? value * 100 : value;
  return Math.max(0, Math.min(100, percent));
}

export function formatMetaNumber(value: number, maximumFractionDigits = 2): string {
  return value.toLocaleString("ru-RU", { maximumFractionDigits });
}

export function rankProjectsByMeta(projects: ProjectListItem[]): ProjectListItem[] {
  return [...projects].sort((left, right) => {
    const leftScore = left.meta?.review_priority_score;
    const rightScore = right.meta?.review_priority_score;
    if (leftScore == null && rightScore != null) return 1;
    if (leftScore != null && rightScore == null) return -1;
    if (leftScore != null && rightScore != null && leftScore !== rightScore) {
      return rightScore - leftScore;
    }
    return left.project_id < right.project_id ? -1 : left.project_id > right.project_id ? 1 : 0;
  });
}

export type PillarStatus = "clear" | "attention" | "info" | "unavailable";

export const STATUS_STYLE: Record<PillarStatus, string> = {
  clear: "bg-accent-50 text-accent-700 ring-1 ring-inset ring-accent-100",
  attention: "bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-200",
  info: "bg-slate-100 text-slate-600 ring-1 ring-inset ring-slate-200",
  unavailable: "bg-slate-100 text-slate-400 ring-1 ring-inset ring-slate-200",
};

export const STATUS_LABEL: Record<PillarStatus, string> = {
  clear: "Замечаний нет",
  attention: "Есть замечания",
  info: "К сведению",
  unavailable: "Недоступно",
};

export const INFERENCE_LABEL: Record<string, string> = {
  supported_by_evidence: "Подтверждено свидетельствами",
  potential_conflict: "Потенциальное замечание",
  insufficient_evidence: "Недостаточно свидетельств",
  not_applicable: "Не применимо",
};

export function pluralize(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return `${n} ${one}`;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return `${n} ${few}`;
  return `${n} ${many}`;
}

export function findingsWord(n: number): string {
  return pluralize(n, "замечание", "замечания", "замечаний");
}

export function documentsWord(n: number): string {
  return pluralize(n, "документ", "документа", "документов");
}

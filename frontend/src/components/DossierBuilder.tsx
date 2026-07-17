"use client";

// Structured dossier builder blocks: project identity (section 0), numbered
// document sections with honest per-file states, computed completeness
// summary and the public-feedback panel. All counts are computed from the
// reconciled documents — never hardcoded per project.

import type { ReactNode } from "react";
import {
  Archive,
  BadgeCheck,
  Building2,
  CalendarRange,
  ExternalLink,
  FileText,
  Globe,
  Image as ImageIcon,
  Landmark,
  MapPin,
  MessageSquareText,
} from "lucide-react";

import type {
  DossierDocument,
  DossierProjectIdentity,
  PublicFeedbackSummary,
} from "@/lib/types";
import {
  RECONCILED_STATUS_STYLE,
  SOURCE_ORIGIN_LABEL,
} from "@/lib/ui";

// --- section 0: project identity ------------------------------------------------

function IdentityFact({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-start gap-2">
      <span className="mt-0.5 text-slate-400">{icon}</span>
      <div className="min-w-0">
        <p className="text-[10px] uppercase tracking-wide text-slate-400">{label}</p>
        <p className="text-xs font-medium leading-snug text-slate-800">{value}</p>
      </div>
    </div>
  );
}

export function IdentityCard({ identity }: { identity: DossierProjectIdentity }) {
  return (
    <section className="card space-y-3 p-5" aria-label="Паспорт проекта">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="chip bg-navy-900 px-2 py-0.5 text-[10px] text-white">Раздел 0</span>
          <h2 className="text-sm font-semibold text-slate-900">Паспорт проекта</h2>
        </div>
        {identity.official_source_verified_at ? (
          <span className="chip bg-accent-50 text-accent-700 ring-1 ring-inset ring-accent-100">
            <BadgeCheck className="h-3.5 w-3.5" aria-hidden />
            Официальный источник · проверен {identity.official_source_verified_at}
          </span>
        ) : null}
      </div>
      {identity.official_title ? (
        <p className="text-sm leading-relaxed text-slate-700">{identity.official_title}</p>
      ) : null}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {identity.hearing_registration_number ? (
          <IdentityFact
            icon={<Landmark className="h-3.5 w-3.5" aria-hidden />}
            label="Регистрационный номер слушаний"
            value={identity.hearing_registration_number}
          />
        ) : null}
        {identity.project_type_label ? (
          <IdentityFact
            icon={<Building2 className="h-3.5 w-3.5" aria-hidden />}
            label="Тип проекта"
            value={identity.project_type_label}
          />
        ) : null}
        {identity.region_label ? (
          <IdentityFact
            icon={<MapPin className="h-3.5 w-3.5" aria-hidden />}
            label="Регион"
            value={identity.region_label}
          />
        ) : null}
        {identity.initiator_type_label ? (
          <IdentityFact
            icon={<Building2 className="h-3.5 w-3.5" aria-hidden />}
            label="Инициатор"
            value={identity.initiator_type_label}
          />
        ) : null}
        {identity.hearing_method_label ? (
          <IdentityFact
            icon={<MessageSquareText className="h-3.5 w-3.5" aria-hidden />}
            label="Форма слушаний"
            value={identity.hearing_method_label}
          />
        ) : null}
        {identity.hearing_period_label ? (
          <IdentityFact
            icon={<CalendarRange className="h-3.5 w-3.5" aria-hidden />}
            label="Период обсуждения"
            value={identity.hearing_period_label}
          />
        ) : null}
      </div>
      {identity.source_url ? (
        <a
          href={identity.source_url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1.5 text-xs font-medium text-accent-700 hover:underline"
        >
          <Globe className="h-3.5 w-3.5" aria-hidden />
          {identity.portal_name ?? "Официальная страница слушаний"}
          <ExternalLink className="h-3 w-3" aria-hidden />
        </a>
      ) : null}
    </section>
  );
}

// --- per-file rows ---------------------------------------------------------------

function MediaIcon({ document }: { document: DossierDocument }) {
  if (document.media_type === "rar" || document.media_type === "zip") {
    return <Archive className="h-4 w-4 flex-none text-slate-400" aria-hidden />;
  }
  if (document.eligible_for_p5) {
    return <ImageIcon className="h-4 w-4 flex-none text-slate-400" aria-hidden />;
  }
  return <FileText className="h-4 w-4 flex-none text-slate-400" aria-hidden />;
}

export function PreparedDocumentRow({ document }: { document: DossierDocument }) {
  return (
    <div className="flex items-start gap-3 px-4 py-3">
      <MediaIcon document={document} />
      <div className="min-w-0 flex-1 space-y-1">
        <p className="text-sm font-medium leading-snug text-slate-800">
          {document.safe_display_name}
        </p>
        <p className="text-xs text-slate-500">
          {[
            document.subtype_label,
            document.media_type.toUpperCase(),
            document.size_label,
            document.page_count ? `${document.page_count} стр.` : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className={`chip ${RECONCILED_STATUS_STYLE[document.reconciled_status]}`}>
            {document.status_label}
          </span>
          <span className="chip bg-slate-100 text-slate-500 ring-1 ring-inset ring-slate-200">
            {SOURCE_ORIGIN_LABEL[document.source_origin]}
          </span>
          {document.analyzed_by.length > 0 ? (
            <span className="chip bg-navy-900 px-2 py-0.5 text-[10px] text-white">
              {document.analyzed_by.join(" · ")}
            </span>
          ) : null}
          {document.registered_label_source ? (
            <span className="chip bg-slate-100 text-slate-500 ring-1 ring-inset ring-slate-200">
              Контрольный материал
            </span>
          ) : null}
          {document.eligible_for_p5 ? (
            <span className="chip bg-slate-100 text-slate-500 ring-1 ring-inset ring-slate-200">
              Будущий вход P5
            </span>
          ) : null}
        </div>
        {document.missing_reason ? (
          <p className="text-xs leading-snug text-amber-700">{document.missing_reason}</p>
        ) : null}
        {document.limitations.length > 0 ? (
          <p className="text-xs leading-snug text-slate-500">{document.limitations[0]}</p>
        ) : null}
      </div>
    </div>
  );
}

// --- public feedback (external structured source) -----------------------------------

export function PublicFeedbackPanel({ feedback }: { feedback: PublicFeedbackSummary | null }) {
  if (feedback === null || !feedback.registered_in_official_source) {
    return (
      <p className="px-4 py-3 text-xs text-slate-400">
        Заполняется из официального источника; для текущего пакета записи не загружены.
      </p>
    );
  }
  return (
    <div className="space-y-2 p-4">
      <div className="flex flex-wrap gap-4">
        <div>
          <p className="text-[10px] uppercase tracking-wide text-slate-400">Обращений</p>
          <p className="text-lg font-semibold tabular-nums text-slate-900">
            {feedback.submission_count}
          </p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wide text-slate-400">Вопросов и замечаний</p>
          <p className="text-lg font-semibold tabular-nums text-slate-900">
            {feedback.question_count}
          </p>
        </div>
        {feedback.submitted_at_label ? (
          <div>
            <p className="text-[10px] uppercase tracking-wide text-slate-400">Дата обращения</p>
            <p className="text-lg font-semibold tabular-nums text-slate-900">
              {feedback.submitted_at_label}
            </p>
          </div>
        ) : null}
      </div>
      <p className="text-xs text-slate-500">{feedback.responses_status_label}</p>
      <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
        {feedback.note}
      </p>
    </div>
  );
}

// --- computed completeness summary ---------------------------------------------------

export interface ComputedCompleteness {
  officialRegistered: number;
  locallyAvailable: number;
  analyzed: number;
  supporting: number;
  officialOnly: number;
  sectionsWithMaterials: number;
  sectionsTotal: number;
}

function SummaryStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] uppercase leading-tight tracking-wide text-slate-400">{label}</p>
      <p className="mt-0.5 text-lg font-semibold tabular-nums text-slate-900">{value}</p>
    </div>
  );
}

export function PackageCompletenessCard({
  completeness,
  sectionChecklist,
}: {
  completeness: ComputedCompleteness;
  sectionChecklist: Array<{ title: string; state: string; note: string }>;
}) {
  return (
    <section className="card space-y-3 p-4" aria-label="Комплектность материалов для анализа">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        Комплектность материалов для анализа
      </h3>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <SummaryStat
          label="В официальном источнике"
          value={String(completeness.officialRegistered)}
        />
        <SummaryStat label="Доступно локально" value={String(completeness.locallyAvailable)} />
        <SummaryStat
          label="Разделов представлено"
          value={`${completeness.sectionsWithMaterials}/${completeness.sectionsTotal}`}
        />
        <SummaryStat label="В детальном анализе" value={String(completeness.analyzed)} />
        <SummaryStat label="Подтверждающих" value={String(completeness.supporting)} />
        <SummaryStat label="Только в источнике" value={String(completeness.officialOnly)} />
      </div>
      <ul className="space-y-1">
        {sectionChecklist.map((item) => (
          <li key={item.title} className="flex items-center justify-between gap-2 text-xs">
            <span className="text-slate-600">{item.title}</span>
            <span className={`chip ${item.state}`}>{item.note}</span>
          </li>
        ))}
      </ul>
      <p className="text-[11px] leading-relaxed text-slate-400">
        Сводка описывает комплектность материалов для анализа, а не юридическую полноту пакета.
      </p>
    </section>
  );
}

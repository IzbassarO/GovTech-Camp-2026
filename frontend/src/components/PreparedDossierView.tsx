import { Eye, LockKeyhole, Table2 } from "lucide-react";

import type { DossierManifestResponse, DossierSectionView } from "@/lib/types";
import { materialsWord, SECTION_COVERAGE_STYLE } from "@/lib/ui";
import { CoverageMatrix } from "@/components/CoverageMatrix";
import {
  IdentityCard,
  PackageCompletenessCard,
  PreparedDocumentRow,
  PublicFeedbackPanel,
} from "@/components/DossierBuilder";

function PreparedSection({
  section,
  manifest,
}: {
  section: DossierSectionView;
  manifest: DossierManifestResponse;
}) {
  const { definition, documents, status } = section;
  return (
    <section className="card overflow-hidden" aria-label={`Раздел ${definition.order}: ${definition.title_ru}`}>
      <div className="space-y-2 border-b border-slate-100 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-navy-900 text-[11px] font-semibold text-white">
            {definition.order}
          </span>
          <h3 className="text-sm font-semibold text-slate-900">{definition.title_ru}</h3>
          {status.total > 0 ? (
            <span className="chip bg-slate-100 text-slate-600 ring-1 ring-inset ring-slate-200">
              {status.total} {materialsWord(status.total)}
            </span>
          ) : null}
          <span className="chip bg-slate-100 text-slate-500 ring-1 ring-inset ring-slate-200">
            <LockKeyhole className="h-3 w-3" aria-hidden />
            Только просмотр
          </span>
        </div>
        <p className="text-xs leading-relaxed text-slate-500">{definition.purpose}</p>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-400">
          <span className="font-medium text-slate-500">{definition.requirement_label}</span>
          {definition.pillar_relevance.length > 0 ? (
            <span className="font-medium text-accent-700">
              В принятом анализе: {definition.pillar_relevance.join(", ")}
            </span>
          ) : definition.future_pillar ? (
            <span>Будущий вход {definition.future_pillar}</span>
          ) : null}
        </div>
      </div>

      {definition.section_id === "public_feedback" ? (
        <PublicFeedbackPanel feedback={manifest.public_feedback} />
      ) : documents.length > 0 ? (
        <div className="divide-y divide-slate-100">
          {documents.map((document) => (
            <PreparedDocumentRow key={document.document_id} document={document} />
          ))}
        </div>
      ) : (
        <p className="px-4 py-3 text-xs text-slate-400">Материалы в источнике не зарегистрированы.</p>
      )}
    </section>
  );
}

export function PreparedDossierView({ manifest }: { manifest: DossierManifestResponse }) {
  const completeness = {
    officialRegistered: manifest.completeness.official_registered_total,
    locallyAvailable: manifest.completeness.locally_available_total,
    analyzed: manifest.completeness.analyzed_total,
    supporting: manifest.completeness.supporting_total,
    officialOnly: manifest.completeness.official_only_total,
    sectionsWithMaterials: manifest.completeness.sections_with_materials,
    sectionsTotal: manifest.completeness.sections_total,
  };
  const sectionChecklist = manifest.sections.map((section) => ({
    title: `${section.definition.order}. ${section.definition.title_ru}`,
    state: SECTION_COVERAGE_STYLE[section.status.coverage_state],
    note: section.status.status_note,
  }));

  return (
    <div className="space-y-5">
      <IdentityCard identity={manifest.identity} />

      <div className="flex items-start gap-2.5 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
        <Eye className="mt-0.5 h-4 w-4 flex-none text-slate-500" aria-hidden />
        <p className="text-xs leading-relaxed text-slate-600">
          Подготовленный пакет неизменяем: документы, разделы и статусы показаны в том виде, в
          котором они связаны с принятыми артефактами анализа.
        </p>
      </div>

      <div className="space-y-3">
        {manifest.sections.map((section) => (
          <PreparedSection key={section.definition.section_id} section={section} manifest={manifest} />
        ))}
      </div>

      <PackageCompletenessCard completeness={completeness} sectionChecklist={sectionChecklist} />

      <section className="card p-4" aria-label="Покрытие документов пилларами">
        <div className="flex items-center gap-2">
          <Table2 className="h-4 w-4 text-slate-400" aria-hidden />
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Покрытие документов пилларами
          </h3>
        </div>
        <div className="mt-3">
          <CoverageMatrix records={manifest.coverage_matrix} />
        </div>
      </section>
    </div>
  );
}

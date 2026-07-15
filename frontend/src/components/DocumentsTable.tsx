import { ExternalLink } from "lucide-react";

import type { DocumentInfo } from "@/lib/types";
import { SeverityBar } from "@/components/primitives";

const DOC_TYPE_LABEL: Record<string, string> = {
  ndv: "Проект НДВ",
  pek: "Программа ПЭК",
  puo: "Управление отходами",
  action_plan: "План мероприятий",
  nontechnical_summary: "Нетехническое резюме",
  roos: "ОВОС / ООС",
  explanatory_note: "Пояснительная записка",
  working_project_note: "Записка рабочего проекта",
};

export function DocumentsTable({ documents }: { documents: DocumentInfo[] }) {
  return (
    <div className="card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3 font-medium">Тип документа</th>
              <th className="hidden px-4 py-3 font-medium sm:table-cell">Страниц</th>
              <th className="hidden px-4 py-3 font-medium md:table-cell">Режим</th>
              <th className="px-4 py-3 font-medium">Замечания</th>
              <th className="px-4 py-3 font-medium">Источник</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {documents.map((doc) => (
              <tr key={doc.document_id}>
                <td className="px-4 py-3">
                  <p className="font-medium text-slate-800">
                    {DOC_TYPE_LABEL[doc.document_type] ?? doc.document_type}
                  </p>
                  <p className="text-xs text-slate-400">
                    {doc.languages.map((l) => l.toUpperCase()).join(", ")}
                  </p>
                </td>
                <td className="hidden px-4 py-3 tabular-nums text-slate-600 sm:table-cell">
                  {doc.page_count ?? "—"}
                </td>
                <td className="hidden px-4 py-3 text-slate-600 md:table-cell">
                  {doc.document_mode ?? "—"}
                </td>
                <td className="px-4 py-3">
                  <SeverityBar counts={doc.finding_counts} />
                </td>
                <td className="px-4 py-3">
                  {doc.source_url ? (
                    <a
                      href={doc.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-xs font-medium text-accent-700 hover:underline"
                    >
                      Портал <ExternalLink className="h-3 w-3" aria-hidden />
                    </a>
                  ) : (
                    <span className="text-xs text-slate-400">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

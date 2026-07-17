// Document → pillar coverage matrix. Explains WHICH materials feed which
// pillars: full-package registration is not deep-analysis coverage. Rows come
// reconciled from the backend (artifact-backed), never computed in React.

import { Check, Minus } from "lucide-react";

import type { AnalysisCoverageRecord } from "@/lib/types";

function CoverageCell({ value, label }: { value: boolean; label: string }) {
  return value ? (
    <Check className="mx-auto h-4 w-4 text-accent-600" aria-label={`${label}: да`} />
  ) : (
    <Minus className="mx-auto h-3.5 w-3.5 text-slate-300" aria-label={`${label}: нет`} />
  );
}

const PILLAR_COLUMNS = [
  { key: "prepared", label: "Подготовлен" },
  { key: "p1", label: "P1" },
  { key: "p2", label: "P2" },
  { key: "p3", label: "P3" },
  { key: "p4", label: "P4" },
  { key: "meta_evidence", label: "Meta" },
] as const;

export function CoverageMatrix({ records }: { records: AnalysisCoverageRecord[] }) {
  return (
    <div>
      {/* Desktop: compact table */}
      <div className="hidden overflow-x-auto sm:block">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="border-b border-slate-200 text-[10px] uppercase tracking-wide text-slate-400">
              <th scope="col" className="py-2 pr-3 font-medium">
                Документ
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                Раздел
              </th>
              {PILLAR_COLUMNS.map((column) => (
                <th key={column.key} scope="col" className="px-2 py-2 text-center font-medium">
                  {column.label}
                </th>
              ))}
              <th scope="col" className="py-2 pl-3 font-medium">
                Ограничение
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {records.map((record) => (
              <tr key={record.document_id} className="align-top text-xs">
                <td className="max-w-[16rem] py-2 pr-3 font-medium leading-snug text-slate-800">
                  {record.safe_display_name}
                </td>
                <td className="py-2 pr-3 text-slate-500">{record.section_title}</td>
                {PILLAR_COLUMNS.map((column) => (
                  <td key={column.key} className="px-2 py-2 text-center">
                    <CoverageCell value={record[column.key]} label={column.label} />
                  </td>
                ))}
                <td className="max-w-[14rem] py-2 pl-3 leading-snug text-slate-500">
                  {record.limitation ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile: document cards instead of a wide table */}
      <ul className="space-y-2 sm:hidden">
        {records.map((record) => (
          <li key={record.document_id} className="rounded-lg border border-slate-200 p-3">
            <p className="text-xs font-medium leading-snug text-slate-800">
              {record.safe_display_name}
            </p>
            <p className="mt-0.5 text-[11px] text-slate-400">{record.section_title}</p>
            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
              {PILLAR_COLUMNS.map((column) => (
                <span
                  key={column.key}
                  className={`inline-flex items-center gap-1 text-[11px] ${
                    record[column.key] ? "font-medium text-accent-700" : "text-slate-300"
                  }`}
                >
                  {record[column.key] ? (
                    <Check className="h-3 w-3" aria-hidden />
                  ) : (
                    <Minus className="h-3 w-3" aria-hidden />
                  )}
                  {column.label}
                </span>
              ))}
            </div>
            {record.limitation ? (
              <p className="mt-1.5 text-[11px] leading-snug text-slate-500">{record.limitation}</p>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

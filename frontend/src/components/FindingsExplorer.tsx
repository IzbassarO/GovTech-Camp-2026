"use client";

import { useMemo, useState } from "react";
import { Search } from "lucide-react";

import type { FindingsPage } from "@/lib/types";
import { buildQuery } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { SEVERITY_LABEL, SEVERITY_ORDER } from "@/lib/ui";
import {
  EmptyState,
  ErrorBlock,
  LoadingBlock,
  SeverityBadge,
} from "@/components/primitives";
import { EvidenceDrawer } from "@/components/EvidenceDrawer";

const PILLAR_LABEL: Record<string, string> = {
  p1: "P1 · Целостность",
  p2: "P2 · Соответствие",
  p3: "P3 · Согласованность",
  p4: "P4 · Междокументная",
};

// Stable fallback list of implemented pillars, used until the API filter
// list arrives so P3/P4 never disappear from the dropdown mid-load.
const IMPLEMENTED_PILLARS = ["p1", "p2", "p3", "p4"];

const P3_EMPTY_TITLE = "Доказанных числовых противоречий не обнаружено.";
const P3_EMPTY_HINT = "Сравнения с недостаточным контекстом были исключены из выводов.";
const P4_EMPTY_TITLE = "Доказанных междокументных противоречий не обнаружено.";
const P4_EMPTY_HINT =
  "Сопоставления с недостаточной идентичностью или контекстом были исключены из выводов.";

export function FindingsExplorer({
  projectId,
  initialPillar = "",
}: {
  projectId: string;
  initialPillar?: string;
}) {
  const [pillar, setPillar] = useState(initialPillar);
  const [severity, setSeverity] = useState("");
  const [findingType, setFindingType] = useState("");
  const [search, setSearch] = useState("");
  const [openFindingId, setOpenFindingId] = useState<string | null>(null);

  const query = useMemo(
    () =>
      buildQuery({
        pillar: pillar || undefined,
        severity: severity || undefined,
        finding_type: findingType || undefined,
        search: search.trim() || undefined,
      }),
    [pillar, severity, findingType, search],
  );

  const { data, error, loading } = useApi<FindingsPage>(
    `/api/projects/${projectId}/findings${query}`,
    [query],
  );

  const typeOptions = data?.available_filters.finding_types ?? [];
  // Registry-based, findings-independent pillar list (falls back to the
  // static implemented set during loading so P3 stays selectable).
  const pillarOptions = data?.available_filters.pillars?.length
    ? data.available_filters.pillars
    : IMPLEMENTED_PILLARS;

  const resetType = (nextPillar: string) => {
    setPillar(nextPillar);
    setFindingType("");
  };

  return (
    <div className="space-y-4">
      <div className="card flex flex-wrap items-center gap-3 p-4">
        <div className="relative min-w-[200px] flex-1">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
            aria-hidden
          />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Поиск по заголовку или типу…"
            className="w-full rounded-lg border border-slate-200 bg-white py-2 pl-9 pr-3 text-sm text-slate-800 placeholder:text-slate-400 focus:border-accent-500"
            aria-label="Поиск замечаний"
          />
        </div>

        <FilterSelect
          label="Пиллар"
          value={pillar}
          onChange={resetType}
          options={[
            { value: "", label: "Все пиллары" },
            ...pillarOptions.map((p) => ({
              value: p,
              label: PILLAR_LABEL[p] ?? p.toUpperCase(),
            })),
          ]}
        />

        <FilterSelect
          label="Серьёзность"
          value={severity}
          onChange={setSeverity}
          options={[
            { value: "", label: "Любая" },
            ...SEVERITY_ORDER.filter((s) =>
              (data?.available_filters.severities ?? []).includes(s),
            ).map((s) => ({ value: s, label: SEVERITY_LABEL[s] })),
          ]}
        />

        <FilterSelect
          label="Тип"
          value={findingType}
          onChange={setFindingType}
          options={[
            { value: "", label: "Все типы" },
            ...typeOptions.map((o) => ({
              value: o.value,
              label: `${o.label} (${o.count})`,
            })),
          ]}
        />
      </div>

      {loading ? <LoadingBlock /> : null}
      {error ? <ErrorBlock message={error} /> : null}

      {data && !loading ? (
        data.findings.length === 0 ? (
          pillar === "p3" ? (
            <EmptyState title={P3_EMPTY_TITLE} hint={P3_EMPTY_HINT} />
          ) : pillar === "p4" ? (
            <EmptyState title={P4_EMPTY_TITLE} hint={P4_EMPTY_HINT} />
          ) : (
            <EmptyState
              title="Замечаний по выбранным фильтрам нет"
              hint="Измените фильтры или сбросьте поиск. Отсутствие замечаний не является подтверждением корректности документов."
            />
          )
        ) : (
          <>
            <p className="text-xs text-slate-500">
              Показано {data.returned} из {data.total} · нажмите строку, чтобы открыть
              свидетельства
            </p>
            <FindingsTable
              findings={data.findings}
              onOpen={(id) => setOpenFindingId(id)}
            />
          </>
        )
      ) : null}

      <EvidenceDrawer
        projectId={projectId}
        findingId={openFindingId}
        onClose={() => setOpenFindingId(null)}
      />
    </div>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: Array<{ value: string; label: string }>;
}) {
  return (
    <label className="flex min-w-0 items-center gap-2 text-xs text-slate-500">
      <span className="hidden sm:inline">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="max-w-full rounded-lg border border-slate-200 bg-white py-2 pl-3 pr-8 text-sm text-slate-800 focus:border-accent-500"
        aria-label={label}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function FindingsTable({
  findings,
  onOpen,
}: {
  findings: FindingsPage["findings"];
  onOpen: (id: string) => void;
}) {
  return (
    <>
      {/* Narrow screens: stacked cards instead of a cramped/scrolling table. */}
      <div className="space-y-2.5 sm:hidden">
        {findings.map((f) => (
          <button
            key={f.finding_id}
            type="button"
            onClick={() => onOpen(f.finding_id)}
            className="card w-full p-4 text-left transition-colors hover:bg-accent-50/40 focus-visible:bg-accent-50/60"
          >
            <div className="flex items-center justify-between gap-2">
              <SeverityBadge severity={f.severity} />
              <span className="chip bg-slate-100 text-slate-600">{f.pillar_id}</span>
            </div>
            <p className="mt-2 text-sm font-medium leading-snug text-slate-800">{f.title}</p>
            <p className="mt-0.5 text-xs text-slate-400">{f.finding_type_label}</p>
            <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
              <span>{f.document_type ?? "пакет"}</span>
              {f.page_references.length ? (
                <span className="tabular-nums">стр. {f.page_references.join(", ")}</span>
              ) : null}
              {f.is_demo ? <span className="chip bg-amber-50 text-amber-700">демо</span> : null}
            </div>
          </button>
        ))}
      </div>

      {/* Tablet and up: full table. */}
      <div className="card hidden overflow-hidden sm:block">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Серьёзность</th>
                <th className="px-4 py-3 font-medium">Пиллар</th>
                <th className="px-4 py-3 font-medium">Замечание</th>
                <th className="hidden px-4 py-3 font-medium md:table-cell">Документ</th>
                <th className="hidden px-4 py-3 font-medium lg:table-cell">Стр.</th>
                <th className="hidden px-4 py-3 font-medium lg:table-cell">Статус</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {findings.map((f) => (
                <tr
                  key={f.finding_id}
                  tabIndex={0}
                  role="button"
                  onClick={() => onOpen(f.finding_id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onOpen(f.finding_id);
                    }
                  }}
                  className="cursor-pointer transition-colors hover:bg-accent-50/40 focus:bg-accent-50/60"
                >
                  <td className="whitespace-nowrap px-4 py-3">
                    <SeverityBadge severity={f.severity} />
                  </td>
                  <td className="whitespace-nowrap px-4 py-3">
                    <span className="chip bg-slate-100 text-slate-600">{f.pillar_id}</span>
                  </td>
                  <td className="px-4 py-3">
                    <p className="font-medium text-slate-800">{f.title}</p>
                    <p className="text-xs text-slate-400">{f.finding_type_label}</p>
                  </td>
                  <td className="hidden px-4 py-3 text-slate-600 md:table-cell">
                    {f.document_type ?? "пакет"}
                  </td>
                  <td className="hidden px-4 py-3 tabular-nums text-slate-500 lg:table-cell">
                    {f.page_references.length ? f.page_references.join(", ") : "—"}
                  </td>
                  <td className="hidden px-4 py-3 lg:table-cell">
                    {f.is_demo ? (
                      <span className="chip bg-amber-50 text-amber-700">демо</span>
                    ) : (
                      <span className="text-xs text-slate-400">на проверку</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

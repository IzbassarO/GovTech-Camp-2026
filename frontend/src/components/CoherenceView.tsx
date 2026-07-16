"use client";

import { CheckCircle2, HelpCircle } from "lucide-react";

import type { CoherenceGraph, P4NotableEntity, PillarSummary } from "@/lib/types";

const SIGNAL_LABEL: Record<string, string> = {
  shared_identifier: "общий БИН",
  normalized_name_match: "совпадение названия",
  same_metadata_value: "метаданные проекта",
};

const COUNT_FIELDS: Array<{ key: keyof PillarSummary; label: string; hint: string }> = [
  { key: "entity_count", label: "Сущностей", hint: "Узлов в графе пакета" },
  { key: "edge_count", label: "Связей", hint: "Рёбер графа" },
  {
    key: "linked_document_count",
    label: "Связанных документов",
    hint: "Документы, соединённые подтверждённой межкументной связью",
  },
  {
    key: "unresolved_entity_count",
    label: "Неразрешённых",
    hint: "Идентичность не установлена",
  },
  {
    key: "suppressed_comparison_count",
    label: "Исключено сравнений",
    hint: "Сопоставления с недостаточной идентичностью/контекстом",
  },
];

export function CoherenceView({ pillar }: { pillar: PillarSummary }) {
  const graph = pillar.graph;
  if (!pillar.available || !graph) return null;
  const proven = graph.proven_conflicts;

  return (
    <div className="space-y-5">
      {proven === 0 ? (
        <div className="rounded-lg border border-accent-200 bg-accent-50 p-4">
          <p className="flex items-center gap-2 text-sm font-medium text-accent-800">
            <CheckCircle2 className="h-4 w-4 flex-none" aria-hidden />
            Доказанных междокументных противоречий не обнаружено.
          </p>
          <p className="mt-1 text-xs leading-relaxed text-accent-700">
            Сопоставления с недостаточной идентичностью или контекстом были исключены
            из выводов. Это не подтверждает корректность документов.
          </p>
        </div>
      ) : (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
          <p className="text-sm font-medium text-amber-800">
            {proven} потенциальных междокументных расхождений — подробности в разделе
            «Замечания».
          </p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {COUNT_FIELDS.map((f) => (
          <div key={f.key} className="card p-3" title={f.hint}>
            <p className="text-xs text-slate-500">{f.label}</p>
            <p className="text-lg font-semibold tabular-nums text-slate-900">
              {(pillar[f.key] as number | null) ?? 0}
            </p>
          </div>
        ))}
      </div>

      <CoherenceOverview graph={graph} />

      {graph.notable_entities.length > 0 ? (
        <div>
          <h4 className="text-sm font-semibold text-slate-800">Сущности графа</h4>
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {graph.notable_entities.map((e) => (
              <EntityCard key={e.entity_id} entity={e} />
            ))}
          </div>
          {graph.emission_source_count > 0 ? (
            <p className="mt-2 text-xs text-slate-500">
              + {graph.emission_source_count} источников выбросов (внутридокументные,
              не участвуют в межкументном сопоставлении)
            </p>
          ) : null}
        </div>
      ) : null}

      {graph.confirmed_links.length > 0 ? (
        <div>
          <h4 className="text-sm font-semibold text-slate-800">Подтверждённые связи</h4>
          <ul className="mt-2 space-y-2">
            {graph.confirmed_links.map((link, i) => (
              <li
                key={i}
                className="flex items-start gap-2 rounded-lg border border-accent-100 bg-accent-50/50 p-3 text-sm"
              >
                <CheckCircle2
                  className="mt-0.5 h-4 w-4 flex-none text-accent-600"
                  aria-hidden
                />
                <div>
                  <p className="text-slate-700">{link.reason}</p>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {link.entity_type_label} · сигнал:{" "}
                    {SIGNAL_LABEL[link.signal] ?? link.signal}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {graph.unresolved_links.length > 0 ? (
        <div>
          <h4 className="text-sm font-semibold text-slate-800">Неразрешённая идентичность</h4>
          <ul className="mt-2 space-y-2">
            {graph.unresolved_links.map((link, i) => (
              <li
                key={i}
                className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50/50 p-3 text-sm text-slate-700"
              >
                <HelpCircle className="mt-0.5 h-4 w-4 flex-none text-amber-600" aria-hidden />
                <span>{link.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {graph.relationships.length > 0 ? (
        <div>
          <h4 className="text-sm font-semibold text-slate-800">Связи документов и сущностей</h4>
          <div className="card mt-2 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">Источник</th>
                    <th className="px-4 py-2.5 font-medium">Связь</th>
                    <th className="px-4 py-2.5 font-medium">Сущность</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {graph.relationships.map((r, i) => (
                    <tr key={i}>
                      <td className="px-4 py-2.5 text-slate-600">{r.source_label}</td>
                      <td className="px-4 py-2.5 text-slate-500">{r.relation_label}</td>
                      <td className="px-4 py-2.5 font-medium text-slate-800">
                        {r.target_label}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : null}

      {graph.suppressed.length > 0 ? (
        <div>
          <h4 className="text-sm font-semibold text-slate-800">Исключённые сравнения</h4>
          <ul className="mt-2 space-y-2">
            {graph.suppressed.map((s) => (
              <li key={s.reason} className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
                <p className="text-slate-700">
                  <span className="chip mr-2 bg-slate-200 text-slate-600">{s.count}</span>
                  {s.detail || s.reason}
                </p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function EntityCard({ entity }: { entity: P4NotableEntity }) {
  return (
    <div className="card p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="chip bg-slate-100 text-slate-600">{entity.entity_type_label}</span>
        {entity.role_label && entity.role_label !== "—" ? (
          <span className="chip bg-navy-900 text-white">{entity.role_label}</span>
        ) : null}
      </div>
      <p className="mt-2 text-sm font-medium leading-snug text-slate-900">{entity.label}</p>
      {entity.identifiers.length > 0 ? (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {entity.identifiers.map((id) => (
            <span key={id} className="chip bg-accent-50 text-accent-700">
              БИН {id}
            </span>
          ))}
        </div>
      ) : null}
      {entity.aliases.length > 0 ? (
        <p className="mt-1.5 text-xs text-slate-500">
          Варианты: {entity.aliases.slice(0, 3).join("; ")}
          {entity.aliases.length > 3 ? " …" : ""}
        </p>
      ) : null}
      {entity.document_count > 1 ? (
        <p className="mt-1.5 text-xs text-accent-700">
          Согласовано в {entity.document_count} документах
        </p>
      ) : null}
    </div>
  );
}

// Minimal, non-interactive CSS/SVG relationship overview: a hub node (operator
// or project) linked to a few notable entities. No graph library.
function CoherenceOverview({ graph }: { graph: CoherenceGraph }) {
  const operator = graph.notable_entities.find((e) => e.role === "operator");
  const hub = operator ?? null;
  const spokeTypes = ["reporting_period", "administrative_location", "activity"];
  const spokes: P4NotableEntity[] = [];
  const seen = new Set<string>();
  for (const type of spokeTypes) {
    const found = graph.notable_entities.find((e) => e.entity_type === type);
    if (found && !seen.has(found.entity_id)) {
      spokes.push(found);
      seen.add(found.entity_id);
    }
  }
  const designers = graph.notable_entities.filter((e) => e.role === "designer").slice(0, 2);
  spokes.push(...designers);
  if (!hub || spokes.length === 0) return null;

  const width = 440;
  const height = 200;
  const cx = width / 2;
  const cy = height / 2;
  const radius = 74;
  const nodes = spokes.slice(0, 6);
  const positions = nodes.map((_, i) => {
    const angle = (i / nodes.length) * 2 * Math.PI - Math.PI / 2;
    return { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) };
  });

  const short = (text: string, n = 18) => (text.length > n ? `${text.slice(0, n)}…` : text);

  return (
    <div className="card p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
        Обзор связей пакета
      </p>
      <div className="mt-2 w-full overflow-x-auto">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="h-auto w-full"
          role="img"
          aria-label="Схема связей: оператор и ключевые сущности пакета"
        >
          {positions.map((p, i) => (
            <line
              key={`l${i}`}
              x1={cx}
              y1={cy}
              x2={p.x}
              y2={p.y}
              stroke="#cbd5e1"
              strokeWidth={1.5}
            />
          ))}
          {positions.map((p, i) => (
            <g key={`n${i}`}>
              <circle cx={p.x} cy={p.y} r={5} fill="#0f766e" />
              <text
                x={p.x}
                y={p.y > cy ? p.y + 16 : p.y - 10}
                textAnchor="middle"
                className="fill-slate-500"
                style={{ fontSize: 10 }}
              >
                {short(nodes[i].label)}
              </text>
            </g>
          ))}
          <circle cx={cx} cy={cy} r={26} fill="#0f172a" />
          <text
            x={cx}
            y={cy + 3}
            textAnchor="middle"
            className="fill-white"
            style={{ fontSize: 10, fontWeight: 600 }}
          >
            оператор
          </text>
        </svg>
      </div>
      <p className="mt-1 text-xs text-slate-500">{short(hub.label, 60)}</p>
    </div>
  );
}

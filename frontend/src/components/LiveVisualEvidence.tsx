"use client";

// P5 · живой результат: галерея job-local визуальных доказательств.
// Миниатюры защищены токеном задания: <img src> не умеет слать заголовки,
// поэтому байты запрашиваются fetch-ом с X-Dalel-Job-Token и показываются
// через object URL. Никаких путей файловой системы в разметке нет.

import { useEffect, useMemo, useState } from "react";
import { Images, Layers } from "lucide-react";

import { API_BASE_URL } from "@/lib/api";
import { readJobToken } from "@/lib/jobTokens";
import type { LiveP5Result } from "@/lib/types";
import {
  P5_CLASS_LABEL,
  P5_GROUP_LABEL,
  formatPercent,
} from "@/components/VisualEvidenceView";

const GROUP_ORDER = [
  "maps",
  "site_photos",
  "diagrams",
  "charts_tables",
  "procedural",
  "unknown",
  "excluded_duplicates",
  "excluded_other",
] as const;

const GALLERY_GROUPS: Record<string, string> = {
  map: "maps",
  site_plan: "maps",
  impact_zone_diagram: "maps",
  satellite_or_aerial_image: "maps",
  site_photo: "site_photos",
  industrial_equipment_photo: "site_photos",
  technical_diagram: "diagrams",
  process_flow_diagram: "diagrams",
  chart: "charts_tables",
  table: "charts_tables",
  procedural_notice: "procedural",
};

interface LiveAssetRow {
  asset_id: string;
  document_id: string;
  page_number: number | null;
  triage_status: string;
  procedural_supporting_evidence: boolean;
  duplicate_cluster_id: string | null;
  image_source: unknown;
}

function galleryGroup(asset: LiveAssetRow, predicted: string | undefined): string {
  if (asset.triage_status === "excluded_duplicate") return "excluded_duplicates";
  if (
    ["excluded_repeated_header", "excluded_logo_or_branding", "excluded_low_information", "unsupported"].includes(
      asset.triage_status,
    )
  ) {
    return "excluded_other";
  }
  if (asset.procedural_supporting_evidence) return "procedural";
  return GALLERY_GROUPS[predicted ?? ""] ?? "unknown";
}

function LiveThumb({
  jobId,
  assetId,
  token,
  alt,
}: {
  jobId: string;
  assetId: string;
  token: string;
  alt: string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let objectUrl: string | null = null;
    const controller = new AbortController();
    fetch(`${API_BASE_URL}/api/live/jobs/${jobId}/p5/assets/${assetId}/thumbnail`, {
      headers: { "X-Dalel-Job-Token": token },
      signal: controller.signal,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("thumbnail unavailable");
        const blob = await response.blob();
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [jobId, assetId, token]);

  if (failed || !url) {
    return <Images className="h-8 w-8 text-slate-300" aria-hidden />;
  }
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={url} alt={alt} className="max-h-full max-w-full object-contain" />;
}

export function LiveVisualEvidence({ jobId, p5 }: { jobId: string; p5: LiveP5Result }) {
  const [token, setToken] = useState<string | null>(null);
  useEffect(() => {
    setToken(readJobToken("live_analysis", jobId));
  }, [jobId]);
  const summary = p5.summary;
  const assets = useMemo(
    () => (p5.assets ?? []) as unknown as LiveAssetRow[],
    [p5.assets],
  );
  const classifications = useMemo(() => {
    const map = new Map<string, { predicted_class?: string; classification_confidence?: number | null }>();
    for (const row of p5.classifications ?? []) {
      map.set(String(row.asset_id), row as never);
    }
    return map;
  }, [p5.classifications]);
  const clusters = useMemo(
    () =>
      (p5.duplicate_clusters ?? []).map((row) => ({
        cluster_id: String(row.cluster_id),
        kind: String(row.kind),
        representative_asset_id: String(row.representative_asset_id),
        member_count: Number(row.member_count ?? 0),
        repeated_ocr_text: (row.repeated_ocr_text as string | null) ?? null,
      })),
    [p5.duplicate_clusters],
  );
  const clusterByRepresentative = useMemo(
    () => new Map(clusters.map((c) => [c.representative_asset_id, c])),
    [clusters],
  );

  const [group, setGroup] = useState<string>("maps");

  if (p5.status !== "completed") {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-relaxed text-amber-800">
        {p5.reason ?? "P5 недоступен для этого задания; отсутствие анализа не означает низкий риск."}
      </div>
    );
  }

  const grouped = new Map<string, LiveAssetRow[]>();
  for (const asset of assets) {
    const predicted = classifications.get(asset.asset_id)?.predicted_class;
    const key = galleryGroup(asset, predicted);
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key)!.push(asset);
  }
  // Дубликаты не показываются как равные карточки: только представитель.
  const duplicateCount = grouped.get("excluded_duplicates")?.length ?? 0;
  const availableGroups = GROUP_ORDER.filter((key) =>
    key === "excluded_duplicates" ? duplicateCount > 0 : (grouped.get(key)?.length ?? 0) > 0,
  );
  const active = availableGroups.includes(group as (typeof GROUP_ORDER)[number])
    ? group
    : (availableGroups[0] ?? "maps");
  const visible =
    active === "excluded_duplicates"
      ? clusters
          .filter((c) => c.kind === "exact_duplicate" || c.kind === "near_duplicate")
          .map((c) => assets.find((a) => a.asset_id === c.representative_asset_id))
          .filter((a): a is LiveAssetRow => Boolean(a))
      : (grouped.get(active) ?? []);

  return (
    <div className="space-y-3">
      {summary ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          <MiniStat label="Активов" value={String(summary.total_asset_count ?? 0)} />
          <MiniStat
            label="Представителей"
            value={String(summary.analyzed_representative_count ?? 0)}
          />
          <MiniStat
            label="Дубликатов исключено"
            value={String(summary.excluded_duplicate_count ?? 0)}
          />
          <MiniStat
            label="Приоритет P5"
            value={`${summary.review_priority ?? 0}/100`}
          />
          <MiniStat
            label="Уверенность"
            value={formatPercent(summary.assessment_confidence ?? null)}
          />
        </div>
      ) : null}

      {token && assets.length ? (
        <>
          <div className="flex gap-1.5 overflow-x-auto pb-1">
            {availableGroups.map((key) => (
              <button
                key={key}
                type="button"
                onClick={() => setGroup(key)}
                className={`whitespace-nowrap rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors ${
                  active === key
                    ? "bg-navy-900 text-white"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                }`}
              >
                {P5_GROUP_LABEL[key] ?? key} ·{" "}
                {key === "excluded_duplicates" ? duplicateCount : grouped.get(key)?.length ?? 0}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
            {visible.slice(0, 18).map((asset) => {
              const classification = classifications.get(asset.asset_id);
              const predicted = classification?.predicted_class ?? "unknown";
              const cluster = clusterByRepresentative.get(asset.asset_id);
              return (
                <figure
                  key={asset.asset_id}
                  className="overflow-hidden rounded-lg border border-slate-200 bg-white"
                >
                  <div className="relative flex h-24 items-center justify-center bg-slate-100">
                    <LiveThumb
                      jobId={jobId}
                      assetId={asset.asset_id}
                      token={token}
                      alt={P5_CLASS_LABEL[predicted] ?? predicted}
                    />
                    {cluster && cluster.member_count > 1 ? (
                      <span className="absolute right-1.5 top-1.5 inline-flex items-center gap-0.5 rounded-full bg-navy-900/85 px-1.5 py-0.5 text-[10px] font-medium text-white">
                        <Layers className="h-2.5 w-2.5" aria-hidden />×{cluster.member_count}
                      </span>
                    ) : null}
                  </div>
                  <figcaption className="p-1.5 text-[10px] leading-tight text-slate-600">
                    {P5_CLASS_LABEL[predicted] ?? predicted}
                    {classification?.classification_confidence !== null &&
                    classification?.classification_confidence !== undefined
                      ? ` · ${Math.round(Number(classification.classification_confidence) * 100)}%`
                      : ""}
                    <span className="block text-slate-400">
                      стр. {asset.page_number ?? "—"}
                    </span>
                  </figcaption>
                </figure>
              );
            })}
          </div>
          {visible.length > 18 ? (
            <p className="text-[11px] text-slate-400">
              Показаны первые 18 из {visible.length}; полный список — в артефактах задания.
            </p>
          ) : null}
        </>
      ) : null}

      {(p5.findings ?? []).length ? (
        <div className="space-y-1.5">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            Находки P5 · {(p5.findings ?? []).length}
          </p>
          {(p5.findings ?? []).slice(0, 6).map((finding) => (
            <div
              key={String(finding.finding_id)}
              className="rounded-md border border-slate-200 bg-white p-2"
            >
              <p className="text-xs font-medium text-slate-800">{String(finding.title)}</p>
              <p className="mt-0.5 text-[11px] leading-snug text-slate-500">
                {String(finding.explanation)}
              </p>
            </div>
          ))}
        </div>
      ) : null}

      {(p5.limitations ?? []).map((limitation) => (
        <p key={limitation} className="text-[11px] leading-relaxed text-slate-500">
          {limitation}
        </p>
      ))}
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white px-2 py-1.5">
      <p className="text-[10px] leading-tight text-slate-400">{label}</p>
      <p className="text-sm font-semibold tabular-nums text-slate-900">{value}</p>
    </div>
  );
}

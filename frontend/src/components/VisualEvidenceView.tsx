"use client";

// P5 · Мультимодальные визуальные доказательства — подготовленные проекты.
// Данные приходят только из принятых артефактов data/results/p5/v1 через API;
// компонент ничего не вычисляет заново и честно показывает ограничения.

import { useEffect, useMemo, useState } from "react";
import { Images, Layers, X } from "lucide-react";

import { API_BASE_URL } from "@/lib/api";
import type {
  P5AssetDetailResponse,
  P5AssetsResponse,
  P5AssetView,
  P5ClusterView,
  P5ProjectResponse,
} from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { EmptyState, ErrorBlock, LoadingBlock } from "@/components/primitives";

export const P5_CLASS_LABEL: Record<string, string> = {
  map: "Карта",
  site_photo: "Фото площадки",
  industrial_equipment_photo: "Фото оборудования",
  technical_diagram: "Технический чертёж",
  process_flow_diagram: "Технологическая схема",
  site_plan: "Генеральный план",
  impact_zone_diagram: "Схема зоны воздействия",
  chart: "График",
  table: "Таблица",
  satellite_or_aerial_image: "Спутниковый/аэроснимок",
  procedural_notice: "Процедурная публикация",
  text_fragment: "Фрагмент текста",
  logo_or_branding: "Логотип/брендинг",
  stamp_or_signature: "Печать/подпись",
  qr_code: "QR-код",
  unknown: "Не определено",
};

export const P5_GROUP_LABEL: Record<string, string> = {
  maps: "Карты и планы",
  site_photos: "Фотографии площадки",
  diagrams: "Схемы и чертежи",
  charts_tables: "Графики и таблицы",
  procedural: "Процедурные материалы",
  excluded_duplicates: "Исключённые дубликаты",
  excluded_other: "Прочие исключённые",
  unknown: "Не определено",
};

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

const TRIAGE_LABEL: Record<string, string> = {
  analyzed_representative: "Анализируется",
  excluded_duplicate: "Дубликат",
  excluded_low_information: "Малоинформативный",
  excluded_repeated_header: "Повторяемый колонтитул",
  excluded_logo_or_branding: "Логотип/оформление",
  unsupported: "Без пригодных байтов",
};

const CLUSTER_KIND_LABEL: Record<string, string> = {
  exact_duplicate: "Точные дубликаты",
  near_duplicate: "Почти идентичные",
  repeated_text_header: "Повторяемый колонтитул",
  logo_or_branding: "Логотип/оформление",
};

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "н/д";
  return `${Math.round(value * 100)}%`;
}

function thumbnailUrl(projectId: string, assetId: string): string {
  return `${API_BASE_URL}/api/projects/${projectId}/p5/assets/${assetId}/thumbnail`;
}

export function VisualEvidenceView({ projectId }: { projectId: string }) {
  const overview = useApi<P5ProjectResponse>(`/api/projects/${projectId}/p5`, [projectId]);
  const assets = useApi<P5AssetsResponse>(`/api/projects/${projectId}/p5/assets`, [projectId]);
  const [group, setGroup] = useState<string>("maps");
  const [openAsset, setOpenAsset] = useState<string | null>(null);

  if (overview.error) return <ErrorBlock message={overview.error} />;
  if (overview.loading || !overview.data) {
    return <LoadingBlock label="Загрузка визуальных доказательств…" />;
  }
  const data = overview.data;
  if (!data.available || !data.summary) {
    return (
      <EmptyState
        title="P5 недоступен для этого проекта"
        hint={
          data.status_reason ??
          "Визуальные материалы зарегистрированы, но мультимодальная модель недоступна."
        }
      />
    );
  }
  const summary = data.summary;
  const modelAvailable = summary.model_status === "available";

  return (
    <div className="space-y-6">
      <div
        className={`rounded-lg border px-4 py-3 text-sm ${
          modelAvailable
            ? "border-accent-100 bg-accent-50 text-slate-700"
            : "border-amber-200 bg-amber-50 text-amber-900"
        }`}
      >
        {modelAvailable
          ? "Мультимодальный анализ текста и визуальных доказательств выполнен: изображения классифицированы моделью и связаны с текстовым контекстом. Результаты — приоритет проверки, а не вывод о нарушении."
          : "Визуальные материалы зарегистрированы, но мультимодальная модель недоступна."}
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        <StatTile label="Всего активов" value={String(summary.total_asset_count)} />
        <StatTile
          label="Анализируемые представители"
          value={String(summary.analyzed_representative_count)}
        />
        <StatTile
          label="Дубликатов исключено"
          value={String(summary.excluded_duplicate_count)}
        />
        <StatTile
          label={data.score_label}
          value={`${summary.review_priority}/100`}
          emphasize
        />
        <StatTile label="Покрытие анализа" value={formatPercent(summary.visual_coverage)} />
        <StatTile
          label="Уверенность оценки"
          value={formatPercent(summary.assessment_confidence)}
        />
      </div>

      <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-2.5 text-xs text-slate-600">
        {data.meta_integration_notice}
      </div>

      {assets.error ? (
        <ErrorBlock message={assets.error} />
      ) : assets.loading || !assets.data ? (
        <LoadingBlock label="Загрузка галереи…" />
      ) : (
        <Gallery
          projectId={projectId}
          assets={assets.data.assets}
          clusters={assets.data.clusters}
          group={group}
          onGroup={setGroup}
          onOpen={setOpenAsset}
        />
      )}

      {data.limitations.length ? (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <p className="text-sm font-semibold text-slate-900">Ограничения</p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-slate-500">
            {data.limitations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {openAsset ? (
        <AssetDetailModal
          projectId={projectId}
          assetId={openAsset}
          onClose={() => setOpenAsset(null)}
        />
      ) : null}
    </div>
  );
}

function StatTile({
  label,
  value,
  emphasize = false,
}: {
  label: string;
  value: string;
  emphasize?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border p-3 ${
        emphasize ? "border-accent-100 bg-accent-50" : "border-slate-200 bg-white"
      }`}
    >
      <p className="text-[11px] leading-tight text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-semibold tabular-nums text-slate-900">{value}</p>
    </div>
  );
}

function Gallery({
  projectId,
  assets,
  clusters,
  group,
  onGroup,
  onOpen,
}: {
  projectId: string;
  assets: P5AssetView[];
  clusters: P5ClusterView[];
  group: string;
  onGroup: (value: string) => void;
  onOpen: (assetId: string) => void;
}) {
  const assetById = useMemo(
    () => new Map(assets.map((asset) => [asset.asset_id, asset])),
    [assets],
  );
  const clusterById = useMemo(
    () => new Map(clusters.map((cluster) => [cluster.cluster_id, cluster])),
    [clusters],
  );
  const groups = useMemo(() => {
    const buckets = new Map<string, P5AssetView[]>();
    for (const asset of assets) {
      const key = asset.gallery_group;
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key)!.push(asset);
    }
    return buckets;
  }, [assets]);

  const duplicateClusters = useMemo(
    () =>
      clusters
        .filter((c) => c.kind === "exact_duplicate" || c.kind === "near_duplicate")
        .sort((a, b) => b.member_count - a.member_count),
    [clusters],
  );
  const excludedClusters = useMemo(
    () =>
      clusters
        .filter((c) => c.kind === "repeated_text_header" || c.kind === "logo_or_branding")
        .sort((a, b) => b.member_count - a.member_count),
    [clusters],
  );

  const availableGroups = GROUP_ORDER.filter((key) => {
    if (key === "excluded_duplicates") return duplicateClusters.length > 0;
    return (groups.get(key)?.length ?? 0) > 0;
  });
  const active = availableGroups.includes(group as (typeof GROUP_ORDER)[number])
    ? group
    : (availableGroups[0] ?? "maps");

  if (!assets.length) {
    return (
      <EmptyState
        title="Визуальные активы не найдены"
        hint="В документах пакета не обнаружено растровых изображений."
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-1.5 overflow-x-auto pb-1" role="tablist" aria-label="Группы галереи">
        {availableGroups.map((key) => {
          const count =
            key === "excluded_duplicates"
              ? duplicateClusters.reduce((total, c) => total + c.member_count - 1, 0)
              : (groups.get(key)?.length ?? 0);
          return (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={active === key}
              onClick={() => onGroup(key)}
              className={`whitespace-nowrap rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                active === key
                  ? "bg-navy-900 text-white"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
            >
              {P5_GROUP_LABEL[key] ?? key} · {count}
            </button>
          );
        })}
      </div>

      {active === "excluded_duplicates" ? (
        <ClusterGrid
          projectId={projectId}
          clusters={duplicateClusters}
          assetById={assetById}
          onOpen={onOpen}
        />
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {(groups.get(active) ?? []).map((asset) => (
            <AssetCard
              key={asset.asset_id}
              projectId={projectId}
              asset={asset}
              cluster={
                asset.duplicate_cluster_id
                  ? clusterById.get(asset.duplicate_cluster_id)
                  : undefined
              }
              onOpen={onOpen}
            />
          ))}
        </div>
      )}

      {active === "excluded_other" && excludedClusters.length ? (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Повторяемые колонтитулы и логотипы
          </p>
          <ul className="mt-2 space-y-1 text-xs text-slate-600">
            {excludedClusters.map((cluster) => (
              <li key={cluster.cluster_id}>
                {CLUSTER_KIND_LABEL[cluster.kind] ?? cluster.kind} · {cluster.member_count}{" "}
                вхождений
                {cluster.repeated_ocr_text ? (
                  <span className="text-slate-500"> · «{cluster.repeated_ocr_text}»</span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function AssetCard({
  projectId,
  asset,
  cluster,
  onOpen,
}: {
  projectId: string;
  asset: P5AssetView;
  cluster?: P5ClusterView;
  onOpen: (assetId: string) => void;
}) {
  const classLabel = asset.predicted_class
    ? (P5_CLASS_LABEL[asset.predicted_class] ?? asset.predicted_class)
    : (TRIAGE_LABEL[asset.triage_status] ?? asset.triage_status);
  const confidence =
    asset.classification_confidence !== null && asset.classification_confidence !== undefined
      ? ` · ${Math.round(asset.classification_confidence * 100)}%`
      : "";
  const clusterBadge =
    cluster && cluster.representative_asset_id === asset.asset_id && cluster.member_count > 1
      ? cluster.member_count
      : null;
  return (
    <button
      type="button"
      onClick={() => onOpen(asset.asset_id)}
      className="card group flex flex-col overflow-hidden text-left transition-shadow hover:shadow-card"
    >
      <div className="relative flex h-36 items-center justify-center overflow-hidden bg-slate-100">
        {asset.thumbnail_available ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={thumbnailUrl(projectId, asset.asset_id)}
            alt={`${classLabel}: ${asset.image_id}`}
            loading="lazy"
            className="max-h-full max-w-full object-contain"
          />
        ) : (
          <Images className="h-8 w-8 text-slate-300" aria-hidden />
        )}
        {clusterBadge ? (
          <span className="absolute right-2 top-2 inline-flex items-center gap-1 rounded-full bg-navy-900/85 px-2 py-0.5 text-[11px] font-medium text-white">
            <Layers className="h-3 w-3" aria-hidden />×{clusterBadge}
          </span>
        ) : null}
      </div>
      <div className="flex flex-1 flex-col gap-1 p-3">
        <p className="text-xs font-semibold text-slate-900">
          {classLabel}
          <span className="font-normal text-slate-500">{confidence}</span>
        </p>
        <p className="text-[11px] text-slate-500">
          {asset.document_type ? `${asset.document_type} · ` : ""}
          стр. {asset.page_number ?? "—"}
        </p>
        {asset.caption ? (
          <p className="line-clamp-2 text-[11px] leading-snug text-slate-500">{asset.caption}</p>
        ) : null}
        {!asset.eligible_for_analysis && asset.triage_status !== "analyzed_representative" ? (
          <p className="line-clamp-2 text-[11px] leading-snug text-slate-400">
            {asset.triage_reason}
          </p>
        ) : null}
      </div>
    </button>
  );
}

function ClusterGrid({
  projectId,
  clusters,
  assetById,
  onOpen,
}: {
  projectId: string;
  clusters: P5ClusterView[];
  assetById: Map<string, P5AssetView>;
  onOpen: (assetId: string) => void;
}) {
  if (!clusters.length) {
    return <EmptyState title="Дубликатов не обнаружено" />;
  }
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {clusters.map((cluster) => {
        const representative = assetById.get(cluster.representative_asset_id);
        return (
          <button
            key={cluster.cluster_id}
            type="button"
            onClick={() => onOpen(cluster.representative_asset_id)}
            className="card flex gap-3 p-3 text-left transition-shadow hover:shadow-card"
          >
            <div className="flex h-20 w-24 shrink-0 items-center justify-center overflow-hidden rounded-md bg-slate-100">
              {representative?.thumbnail_available ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={thumbnailUrl(projectId, cluster.representative_asset_id)}
                  alt="Представитель кластера"
                  loading="lazy"
                  className="max-h-full max-w-full object-contain"
                />
              ) : (
                <Images className="h-6 w-6 text-slate-300" aria-hidden />
              )}
            </div>
            <div className="min-w-0">
              <p className="text-xs font-semibold text-slate-900">
                {CLUSTER_KIND_LABEL[cluster.kind] ?? cluster.kind} · ×{cluster.member_count}
              </p>
              <p className="mt-1 line-clamp-2 text-[11px] leading-snug text-slate-500">
                {cluster.exclusion_reason}
              </p>
              <p className="mt-1 text-[11px] text-slate-400">
                Стр.: {cluster.page_numbers.slice(0, 6).join(", ")}
                {cluster.page_numbers.length > 6 ? "…" : ""}
              </p>
            </div>
          </button>
        );
      })}
    </div>
  );
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{label}</p>
      <div className="mt-0.5 text-xs leading-relaxed text-slate-700">{children}</div>
    </div>
  );
}

function AssetDetailModal({
  projectId,
  assetId,
  onClose,
}: {
  projectId: string;
  assetId: string;
  onClose: () => void;
}) {
  const detail = useApi<P5AssetDetailResponse>(
    `/api/projects/${projectId}/p5/assets/${assetId}`,
    [projectId, assetId],
  );

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const asset = detail.data?.asset as Record<string, unknown> | undefined;
  const context = detail.data?.context ?? undefined;
  const classification = detail.data?.classification ?? undefined;
  const cluster = detail.data?.cluster ?? undefined;
  const predicted = String(classification?.predicted_class ?? "unknown");
  const competing = (classification?.competing_classes as
    | Array<{ visual_class: string; affinity: number }>
    | undefined)?.slice(0, 3);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-navy-950/60 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Детали визуального актива"
      onClick={onClose}
    >
      <div
        className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-xl bg-white shadow-drawer"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="sticky top-0 flex items-center justify-between border-b border-slate-200 bg-white px-5 py-3">
          <p className="text-sm font-semibold text-slate-900">
            {P5_CLASS_LABEL[predicted] ?? predicted}
            {classification?.classification_confidence !== null &&
            classification?.classification_confidence !== undefined
              ? ` · аффинность ${Math.round(Number(classification.classification_confidence) * 100)}%`
              : ""}
          </p>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>

        {detail.error ? (
          <div className="p-5">
            <ErrorBlock message={detail.error} />
          </div>
        ) : detail.loading || !detail.data ? (
          <div className="p-5">
            <LoadingBlock label="Загрузка актива…" />
          </div>
        ) : (
          <div className="space-y-4 p-5">
            <div className="flex items-center justify-center rounded-lg bg-slate-100 p-2">
              {detail.data.thumbnail_available ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={thumbnailUrl(projectId, assetId)}
                  alt="Визуальный актив"
                  className="max-h-[45vh] max-w-full object-contain"
                />
              ) : (
                <p className="p-8 text-xs text-slate-500">Изображение недоступно</p>
              )}
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <DetailRow label="Документ и страница">
                {String(asset?.document_id ?? "—")} · стр. {String(asset?.page_number ?? "—")}
              </DetailRow>
              <DetailRow label="Статус триажа">
                {TRIAGE_LABEL[String(asset?.triage_status)] ?? String(asset?.triage_status)}
              </DetailRow>
              {context?.caption ? (
                <DetailRow label="Подпись на странице">{String(context.caption)}</DetailRow>
              ) : null}
              {context?.nearest_heading ? (
                <DetailRow label="Ближайший заголовок">
                  {String(context.nearest_heading)}
                </DetailRow>
              ) : null}
            </div>

            {context?.page_text_excerpt ? (
              <DetailRow label="Контекст страницы">
                <p className="line-clamp-4">{String(context.page_text_excerpt)}</p>
              </DetailRow>
            ) : null}

            {context?.ocr_text ? (
              <DetailRow label={`OCR (${String(context.ocr_status)})`}>
                <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap rounded-md bg-slate-50 p-2 text-[11px]">
                  {String(context.ocr_text)}
                </pre>
              </DetailRow>
            ) : (
              <DetailRow label="OCR">
                Статус: {String(context?.ocr_status ?? "not_run")}
                {context?.ocr_failure_reason ? ` · ${String(context.ocr_failure_reason)}` : ""}
              </DetailRow>
            )}

            {competing?.length ? (
              <DetailRow label="Конкурирующие классы (аффинность)">
                <div className="space-y-1">
                  {competing.map((entry) => (
                    <div key={entry.visual_class} className="flex items-center gap-2">
                      <span className="w-40 shrink-0 text-[11px] text-slate-600">
                        {P5_CLASS_LABEL[entry.visual_class] ?? entry.visual_class}
                      </span>
                      <div className="h-1.5 flex-1 rounded-full bg-slate-100">
                        <div
                          className="h-1.5 rounded-full bg-accent-500"
                          style={{ width: `${Math.round(entry.affinity * 100)}%` }}
                        />
                      </div>
                      <span className="w-10 text-right text-[11px] tabular-nums text-slate-500">
                        {Math.round(entry.affinity * 100)}%
                      </span>
                    </div>
                  ))}
                </div>
              </DetailRow>
            ) : null}

            {(context?.image_caption_similarity !== null &&
              context?.image_caption_similarity !== undefined) ||
            (context?.image_context_similarity !== null &&
              context?.image_context_similarity !== undefined) ? (
              <DetailRow label="Кросс-модальные проверки">
                Сходство с подписью:{" "}
                {context?.image_caption_similarity !== null &&
                context?.image_caption_similarity !== undefined
                  ? Number(context.image_caption_similarity).toFixed(3)
                  : "н/д"}{" "}
                · с контекстом страницы:{" "}
                {context?.image_context_similarity !== null &&
                context?.image_context_similarity !== undefined
                  ? Number(context.image_context_similarity).toFixed(3)
                  : "н/д"}
                <p className="mt-1 text-[11px] text-slate-400">
                  Низкое сходство — сигнал для проверки, а не доказанное противоречие.
                </p>
              </DetailRow>
            ) : null}

            {cluster ? (
              <DetailRow label="Кластер повторов">
                {CLUSTER_KIND_LABEL[String(cluster.kind)] ?? String(cluster.kind)} · ×
                {String(cluster.member_count)} · {String(cluster.exclusion_reason ?? "")}
              </DetailRow>
            ) : null}

            {detail.data.findings.length ? (
              <DetailRow label="Находки P5">
                <ul className="space-y-2">
                  {detail.data.findings.map((finding) => (
                    <li
                      key={String(finding.finding_id)}
                      className="rounded-md border border-slate-200 p-2"
                    >
                      <p className="text-xs font-medium text-slate-800">
                        {String(finding.title)}
                      </p>
                      <p className="mt-0.5 text-[11px] text-slate-500">
                        {String(finding.explanation)}
                      </p>
                    </li>
                  ))}
                </ul>
              </DetailRow>
            ) : null}

            {Array.isArray(classification?.limitations) &&
            (classification?.limitations as string[]).length ? (
              <DetailRow label="Ограничения">
                <ul className="list-disc pl-4">
                  {(classification?.limitations as string[]).map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </DetailRow>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}

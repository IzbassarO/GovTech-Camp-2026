"use client";

import type { ProjectListItem } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { rankProjectsByMeta } from "@/lib/ui";
import { ErrorBlock, Section, SkeletonCard } from "@/components/primitives";
import { ProjectCard } from "@/components/ProjectCard";
import { MetaDisclaimer, MetaLegend } from "@/components/MetaAssessmentView";

export default function ProjectsPage() {
  const { data, error, loading } = useApi<ProjectListItem[]>("/api/projects");
  const rankedProjects = data ? rankProjectsByMeta(data) : null;
  const metaRankingAvailable = rankedProjects
    ? rankedProjects.some((project) => project.meta !== null)
    : null;

  return (
    <>
      {/* This page's only visual heading is the Section's h2 below; an
          sr-only h1 keeps the document outline valid for screen readers. */}
      <h1 className="sr-only">Проекты</h1>
      <Section
        title="Проекты"
        description={
          metaRankingAvailable === false
            ? "Валидные Meta-артефакты недоступны; проекты показаны без интегрального ранжирования."
            : "Пакеты с результатами P1–P4 упорядочены по интегральной приоритетности экспертной проверки."
        }
      >
        {metaRankingAvailable === false ? null : (
          <div className="space-y-3">
            <MetaDisclaimer />
            <MetaLegend />
          </div>
        )}
        {error ? (
          <ErrorBlock message={error} />
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {loading || !rankedProjects ? (
              <>
                <SkeletonCard />
                <SkeletonCard />
                <SkeletonCard />
                <SkeletonCard />
              </>
            ) : (
              rankedProjects.map((project) => (
                <ProjectCard key={project.project_id} project={project} />
              ))
            )}
          </div>
        )}
      </Section>
    </>
  );
}

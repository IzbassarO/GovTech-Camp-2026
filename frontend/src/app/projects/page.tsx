"use client";

import type { ProjectListItem } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { rankProjectsByMeta } from "@/lib/ui";
import { ErrorBlock, Section, SkeletonCard } from "@/components/primitives";
import { ProjectCard } from "@/components/ProjectCard";
import { MetaDisclaimer } from "@/components/MetaAssessmentView";

export default function ProjectsPage() {
  const { data, error, loading } = useApi<ProjectListItem[]>("/api/projects");
  const rankedProjects = data ? rankProjectsByMeta(data) : null;
  const metaRankingAvailable = rankedProjects
    ? rankedProjects.some((project) => project.meta !== null)
    : null;

  return (
    <Section
      title="Проекты"
      description={
        metaRankingAvailable === false
          ? "Валидные Meta-артефакты недоступны; проекты показаны без интегрального ранжирования."
          : "Пакеты с результатами P1–P4 упорядочены по интегральной приоритетности экспертной проверки."
      }
    >
      {metaRankingAvailable === false ? null : <MetaDisclaimer />}
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
  );
}

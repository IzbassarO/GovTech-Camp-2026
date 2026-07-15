"use client";

import type { ProjectListItem } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { ErrorBlock, Section, SkeletonCard } from "@/components/primitives";
import { ProjectCard } from "@/components/ProjectCard";

export default function ProjectsPage() {
  const { data, error, loading } = useApi<ProjectListItem[]>("/api/projects");

  return (
    <Section
      title="Проекты"
      description="Каждый проект — пакет экологической документации с результатами анализа P1 / P2 / P3."
    >
      {error ? (
        <ErrorBlock message={error} />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {loading || !data ? (
            <>
              <SkeletonCard />
              <SkeletonCard />
              <SkeletonCard />
              <SkeletonCard />
            </>
          ) : (
            data.map((project) => <ProjectCard key={project.project_id} project={project} />)
          )}
        </div>
      )}
    </Section>
  );
}

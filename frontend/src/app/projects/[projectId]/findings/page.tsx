"use client";

import { Suspense } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import { Section } from "@/components/primitives";
import { FindingsExplorer } from "@/components/FindingsExplorer";

function FindingsInner({ projectId }: { projectId: string }) {
  const searchParams = useSearchParams();
  const initialPillar = searchParams.get("pillar") ?? "";
  return <FindingsExplorer projectId={projectId} initialPillar={initialPillar} />;
}

export default function ProjectFindingsPage() {
  const params = useParams<{ projectId: string }>();
  const projectId = params.projectId;

  return (
    <div className="space-y-6">
      <Link
        href={`/projects/${projectId}`}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-slate-500 hover:text-slate-700"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden />
        К проекту
      </Link>
      <Section
        title="Замечания проекта"
        description="Фильтры по пиллару, серьёзности и типу. Нажмите строку для просмотра свидетельств."
      >
        <Suspense fallback={null}>
          <FindingsInner projectId={projectId} />
        </Suspense>
      </Section>
    </div>
  );
}

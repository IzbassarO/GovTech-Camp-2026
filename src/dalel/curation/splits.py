"""Document grouping and split PROPOSAL.

With only four projects a final train/test split is not created: any holdout
would contain a single project and no statistically reliable risk-model
training or evaluation is possible. The minimum split unit is the project
(pages/chunks of one project must never cross a split boundary).
"""

from __future__ import annotations

from typing import Any

from dalel.curation.schemas import CuratedDocument, CuratedProject, DocumentGroup


def build_document_groups(
    projects: list[CuratedProject], documents: list[CuratedDocument]
) -> list[DocumentGroup]:
    by_project: dict[str, list[CuratedDocument]] = {}
    for document in documents:
        by_project.setdefault(document.project_id, []).append(document)

    groups: list[DocumentGroup] = []
    for project in projects:
        docs = by_project.get(project.project_id, [])
        groups.append(
            DocumentGroup(
                group_id=f"group__{project.project_id}",
                project_id=project.project_id,
                region=project.region,
                industry=project.industry,
                languages=project.languages,
                download_year=project.download_year,
                company_id=project.company_id,
                developer_id=project.developer_id,
                document_ids=sorted(d.document_id for d in docs),
                document_types=sorted({d.document_type for d in docs}),
                ingestion_schema_versions=sorted({d.ingestion_schema_version for d in docs}),
                has_weak_findings=project.project_id == "project_002_azm",
                label_source_document_ids=project.label_source_document_ids,
            )
        )
    return groups


def build_split_proposal(groups: list[DocumentGroup]) -> dict[str, Any]:
    """A proposal only — explicitly NOT a final split."""
    return {
        "status": "proposal_only",
        "final_split_created": False,
        "reason": (
            "Only 4 projects are available. Any project-level holdout keeps a single"
            " project per fold; statistically reliable risk-model training and"
            " evaluation are NOT possible at this corpus size. No random page-level"
            " split is permitted (leakage via shared project context)."
        ),
        "minimum_split_unit": "project_id",
        "forbidden": [
            "random page-level splits",
            "random chunk-level splits",
            "splitting one project across train and test",
        ],
        "proposed_scheme": {
            "name": "leave-one-project-out cross-validation",
            "folds": [
                {
                    "fold_id": index + 1,
                    "held_out_group": group.group_id,
                    "held_out_project": group.project_id,
                    "train_groups": [g.group_id for g in groups if g is not group],
                }
                for index, group in enumerate(groups)
            ],
            "usage": (
                "Suitable only for qualitative error analysis and pipeline smoke"
                " evaluation until more projects are collected."
            ),
        },
        "known_confounders": [
            "region and industry are perfectly confounded with project identity",
            "single weak-label project (project_002_azm) — labels cover one fold only",
            "document_type mix differs per project (permit package vs construction EIA)",
            "mixed ingestion schema versions (1.0.0 / 1.1.0) correlate with project_004",
        ],
    }

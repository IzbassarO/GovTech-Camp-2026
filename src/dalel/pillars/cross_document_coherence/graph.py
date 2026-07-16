"""Lightweight JSON entity graph (no external graph database).

Nodes are the resolved entities; edges connect them with evidence-backed
relations. Every edge preserves the supporting claims and source documents, so
it can be re-derived and no unsupported relationship is invented.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dalel.pillars.cross_document_coherence.schemas import (
    Edge,
    Entity,
    deterministic_id,
)

# Attribute-entity relation by organization role and by document-level type.
_ORG_RELATION = {
    "operator": "document_identifies_operator",
    "designer": "document_names_designer",
    "unknown": "document_names_organization",
}
_DOC_LEVEL_RELATION = {
    "reporting_period": "document_covers_period",
    "administrative_location": "document_states_location",
    "activity": "document_describes_activity",
    "emission_source": "document_describes_emission_source",
}


@dataclass
class GraphResult:
    edges: list[Edge] = field(default_factory=list)


def build_graph(entities: list[Entity]) -> GraphResult:
    result = GraphResult()
    by_project: dict[str, list[Entity]] = {}
    for entity in entities:
        by_project.setdefault(entity.project_id, []).append(entity)

    for project_id in sorted(by_project):
        project_entities = by_project[project_id]
        project_entity = next((e for e in project_entities if e.entity_type == "project"), None)
        if project_entity is None:  # pragma: no cover - always present
            continue
        document_entities = {
            e.source_document_ids[0]: e for e in project_entities if e.entity_type == "document"
        }

        # project_contains_document
        for document_id in sorted(document_entities):
            document_entity = document_entities[document_id]
            _add_edge(
                result,
                project_id,
                project_entity.entity_id,
                document_entity.entity_id,
                "project_contains_document",
                [],
                [document_id],
                1.0,
            )

        # attribute edges
        for entity in project_entities:
            if entity.entity_type in ("project", "document"):
                continue
            relation, project_level = _relation_for(entity)
            if relation is None:
                continue
            if project_level or not entity.source_document_ids:
                _add_edge(
                    result,
                    project_id,
                    project_entity.entity_id,
                    entity.entity_id,
                    relation,
                    entity.claim_ids,
                    entity.source_document_ids,
                    entity.confidence,
                )
                continue
            for document_id in entity.source_document_ids:
                doc_entity = document_entities.get(document_id)
                if doc_entity is None:
                    continue
                _add_edge(
                    result,
                    project_id,
                    doc_entity.entity_id,
                    entity.entity_id,
                    relation,
                    entity.claim_ids,
                    [document_id],
                    entity.confidence,
                )

    result.edges.sort(key=lambda e: (e.project_id, e.relation, e.edge_id))
    return result


def _relation_for(entity: Entity) -> tuple[str | None, bool]:
    """Return ``(relation, is_project_level)`` for an attribute entity."""
    if entity.entity_type == "organization":
        return _ORG_RELATION.get(entity.role or "unknown", "document_names_organization"), False
    # region / industry metadata entities have no source documents.
    if entity.entity_type == "administrative_location" and not entity.source_document_ids:
        return "project_located_in", True
    if entity.entity_type == "activity" and not entity.source_document_ids:
        return "project_performs_activity", True
    relation = _DOC_LEVEL_RELATION.get(entity.entity_type)
    return relation, False


def _add_edge(
    result: GraphResult,
    project_id: str,
    source_entity_id: str,
    target_entity_id: str,
    relation: str,
    claim_ids: list[str],
    source_document_ids: list[str],
    confidence: float,
) -> None:
    edge_id = deterministic_id("P4G", project_id, relation, source_entity_id, target_entity_id)
    result.edges.append(
        Edge(
            edge_id=edge_id,
            project_id=project_id,
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            relation=relation,
            claim_ids=sorted(claim_ids),
            confidence=round(confidence, 2),
            source_document_ids=sorted(set(source_document_ids)),
        )
    )

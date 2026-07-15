"""Deterministic local retrieval over requirement-level records.

Compact TF-IDF retriever (no search framework, no embeddings, no network):

- requirement text = title + requirement_text + topics + tags + activities;
- query text = project evidence (document types, section headings, project
  context) — per document and once per package;
- score = TF-IDF dot product over shared terms, normalized by the
  requirement vector norm, plus DECLARED boosts (exact title terms,
  applicability-tag match, topic match), every boost recorded;
- ordering is fully deterministic: (-score, requirement_id); scores are
  rounded to a fixed number of decimals before ranking so serialized
  artifacts are byte-stable.

A requirement below MIN_RETRIEVAL_SCORE is NOT retrieved — weak topical
overlap must not force a regulation match.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

from dalel.pillars.regulatory_compliance.config import (
    APPLICABILITY_TAG_BOOST,
    EXACT_TERM_BOOST,
    EXACT_TERM_BOOST_CAP,
    MIN_RETRIEVAL_SCORE,
    SCORE_DECIMALS,
    TOPIC_BOOST,
)
from dalel.pillars.regulatory_compliance.evidence import ProjectEvidenceStore
from dalel.pillars.regulatory_compliance.normalization import token_set, tokenize
from dalel.pillars.regulatory_compliance.schemas import (
    RegulatoryRequirement,
    RetrievalRecord,
    deterministic_id,
)


@dataclass
class RequirementIndex:
    """Deterministic TF-IDF index over one loaded corpus."""

    requirements: list[RegulatoryRequirement]
    # term -> requirement_id -> tf weight
    weights: dict[str, dict[str, float]] = field(default_factory=dict)
    idf: dict[str, float] = field(default_factory=dict)
    norms: dict[str, float] = field(default_factory=dict)
    title_tokens: dict[str, frozenset[str]] = field(default_factory=dict)
    by_id: dict[str, RegulatoryRequirement] = field(default_factory=dict)


def requirement_search_text(requirement: RegulatoryRequirement) -> str:
    return " ".join(
        [
            requirement.title,
            requirement.requirement_text,
            " ".join(requirement.environmental_topics),
            " ".join(requirement.regulated_activities),
            " ".join(requirement.required_concepts),
            " ".join(tag.replace(":", " ") for tag in requirement.applicability_tags),
        ]
    )


def build_index(requirements: list[RegulatoryRequirement]) -> RequirementIndex:
    index = RequirementIndex(requirements=list(requirements))
    term_counts: dict[str, dict[str, int]] = {}
    for requirement in requirements:
        index.by_id[requirement.requirement_id] = requirement
        index.title_tokens[requirement.requirement_id] = token_set(requirement.title)
        for token in tokenize(requirement_search_text(requirement)):
            term_counts.setdefault(token, {}).setdefault(requirement.requirement_id, 0)
            term_counts[token][requirement.requirement_id] += 1
    total = len(requirements)
    for term, per_requirement in term_counts.items():
        index.idf[term] = math.log(1.0 + total / (1.0 + len(per_requirement))) + 1.0
        index.weights[term] = {
            requirement_id: (1.0 + math.log(count)) * index.idf[term]
            for requirement_id, count in per_requirement.items()
        }
    norm_squares: dict[str, float] = {}
    for per_requirement_weights in index.weights.values():
        for requirement_id, weight in per_requirement_weights.items():
            norm_squares[requirement_id] = norm_squares.get(requirement_id, 0.0) + weight * weight
    for requirement in requirements:
        norm_sq = norm_squares.get(requirement.requirement_id, 0.0)
        index.norms[requirement.requirement_id] = math.sqrt(norm_sq) or 1.0
    return index


@dataclass
class Query:
    query_id: str
    project_id: str
    kind: str  # "document" | "package"
    document_id: str | None
    document_type: str | None
    text: str
    evidence_ids: list[str]


def build_queries(store: ProjectEvidenceStore) -> list[Query]:
    """One query per document (type + its headings) and one package query
    (document types + industry context). Fully deterministic."""
    queries: list[Query] = []
    headings_by_document: dict[str, list[str]] = {}
    evidence_by_document: dict[str, list[str]] = {}
    document_types: dict[str, str] = {}
    package_evidence: list[str] = []
    package_bits: list[str] = []

    for item in store.ordered():
        if item.kind == "section_heading" and item.document_id is not None:
            headings_by_document.setdefault(item.document_id, []).append(item.text)
            evidence_by_document.setdefault(item.document_id, []).append(item.evidence_id)
        elif item.kind == "document_present" and item.document_id is not None:
            document_types[item.document_id] = item.document_type or ""
            evidence_by_document.setdefault(item.document_id, []).insert(0, item.evidence_id)
            package_evidence.append(item.evidence_id)
            package_bits.append(item.text)
        elif item.kind == "project_context":
            package_evidence.append(item.evidence_id)
            package_bits.append(item.text)

    for document_id in sorted(document_types):
        headings = headings_by_document.get(document_id, [])
        text = " ".join([f"документ типа {document_types[document_id]}", *headings])
        queries.append(
            Query(
                query_id=deterministic_id("P2Q", store.project_id, "document", document_id),
                project_id=store.project_id,
                kind="document",
                document_id=document_id,
                document_type=document_types[document_id],
                text=text,
                evidence_ids=evidence_by_document.get(document_id, []),
            )
        )
    queries.append(
        Query(
            query_id=deterministic_id("P2Q", store.project_id, "package"),
            project_id=store.project_id,
            kind="package",
            document_id=None,
            document_type=None,
            text=" ".join(package_bits),
            evidence_ids=package_evidence,
        )
    )
    return queries


def _boosts(
    requirement: RegulatoryRequirement,
    query: Query,
    store: ProjectEvidenceStore,
    query_tokens: frozenset[str],
    index: RequirementIndex,
) -> dict[str, float]:
    boosts: dict[str, float] = {}
    exact = len(index.title_tokens[requirement.requirement_id] & query_tokens)
    if exact:
        boosts["exact_term"] = round(min(EXACT_TERM_BOOST * exact, EXACT_TERM_BOOST_CAP), 6)
    tag_hit = False
    for tag in requirement.applicability_tags:
        key, _, value = tag.partition(":")
        if (
            key == "document_type"
            and (value == query.document_type or value in store.document_types)
        ) or (key in ("package", "industry") and value == "any"):
            tag_hit = True
    if requirement.required_document_type and (
        requirement.required_document_type in store.document_types
        or requirement.required_document_type == query.document_type
    ):
        tag_hit = True
    if tag_hit:
        boosts["applicability_tag"] = APPLICABILITY_TAG_BOOST
    if any(topic and topic in query_tokens for topic in requirement.environmental_topics):
        boosts["topic"] = TOPIC_BOOST
    return boosts


def retrieve(
    index: RequirementIndex,
    query: Query,
    store: ProjectEvidenceStore,
    top_k: int,
    min_score: float = MIN_RETRIEVAL_SCORE,
    ensure_ids: frozenset[str] = frozenset(),
) -> list[RetrievalRecord]:
    """Top-k requirements for one query, deterministic ordering.

    ``ensure_ids`` are appended after the regular top-k (real computed
    score, even below the threshold) — used for package-wide
    required-document checks, where the ABSENCE of the document weakens
    exactly the lexical signal that would have retrieved the requirement."""
    query_tokens_list = tokenize(query.text)
    query_tokens = frozenset(query_tokens_list)
    query_counts: dict[str, int] = {}
    for token in query_tokens_list:
        query_counts[token] = query_counts.get(token, 0) + 1

    scores: dict[str, float] = {}
    matched: dict[str, list[str]] = {}
    for term, count in query_counts.items():
        per_requirement = index.weights.get(term)
        if not per_requirement:
            continue
        query_weight = 1.0 + math.log(count)
        for requirement_id, weight in per_requirement.items():
            scores[requirement_id] = scores.get(requirement_id, 0.0) + query_weight * weight
            matched.setdefault(requirement_id, []).append(term)

    query_hash = hashlib.sha256(query.text.encode("utf-8")).hexdigest()
    scored: list[tuple[float, str, dict[str, float], float]] = []
    ensured: list[tuple[float, str, dict[str, float], float]] = []
    candidate_ids = set(scores) | set(ensure_ids)
    for requirement_id in candidate_ids:
        requirement = index.by_id[requirement_id]
        dot = scores.get(requirement_id, 0.0)
        lexical = round(dot / index.norms[requirement_id], SCORE_DECIMALS)
        boosts = _boosts(requirement, query, store, query_tokens, index)
        total = round(lexical + sum(boosts.values()), SCORE_DECIMALS)
        if total >= min_score:
            scored.append((total, requirement_id, boosts, lexical))
        elif requirement_id in ensure_ids:
            ensured.append((total, requirement_id, boosts, lexical))
    scored.sort(key=lambda item: (-item[0], item[1]))
    ensured.sort(key=lambda item: (-item[0], item[1]))
    selected = scored[:top_k]
    selected_ids = {requirement_id for _, requirement_id, _, _ in selected}
    # Ensured requirements missing from the top-k are appended with their
    # REAL score and explicit rationale — never silently promoted.
    for item in [*scored[top_k:], *ensured]:
        if item[1] in ensure_ids and item[1] not in selected_ids:
            selected.append(item)
            selected_ids.add(item[1])

    records: list[RetrievalRecord] = []
    for rank, (total, requirement_id, boosts, lexical) in enumerate(selected, start=1):
        backstop = total < min_score or rank > top_k
        records.append(
            RetrievalRecord(
                retrieval_id=deterministic_id("P2R", query.query_id, requirement_id),
                project_id=query.project_id,
                query_id=query.query_id,
                query_kind=query.kind,  # type: ignore[arg-type]
                query_document_id=query.document_id,
                query_text=query.text,
                query_hash=query_hash,
                requirement_id=requirement_id,
                rank=rank,
                lexical_score=lexical,
                boosts=boosts,
                score=total,
                matched_terms=sorted(set(matched.get(requirement_id, []))),
                evidence_ids=list(query.evidence_ids),
                rationale=(
                    "Обязательная проверка наличия документа для пакета"
                    " (включена по условию применимости, лексический сигнал"
                    " слаб — возможно, именно из-за отсутствия документа)."
                    if backstop
                    else (
                        f"Лексическое совпадение по"
                        f" {len(set(matched.get(requirement_id, [])))}"
                        f" терминам; бонусы: {', '.join(sorted(boosts)) or 'нет'}."
                    )
                ),
            )
        )
    return records


def package_check_ids(index: RequirementIndex) -> frozenset[str]:
    """Requirements that must ALWAYS be checked per package: package-wide
    required-document obligations (their lexical signal disappears exactly
    when the document is missing)."""
    return frozenset(
        r.requirement_id
        for r in index.requirements
        if r.obligation_type == "required_document"
        and r.required_document_type is not None
        and "package:any" in r.applicability_tags
    )


def retrieve_for_project(
    index: RequirementIndex,
    store: ProjectEvidenceStore,
    top_k: int,
    min_score: float = MIN_RETRIEVAL_SCORE,
) -> tuple[list[RetrievalRecord], dict[str, RetrievalRecord]]:
    """All query retrievals plus the best retrieval per requirement
    (max score; ties by earliest rank then retrieval_id)."""
    ensured = package_check_ids(index)
    all_records: list[RetrievalRecord] = []
    for query in build_queries(store):
        ensure = ensured if query.kind == "package" else frozenset()
        all_records.extend(retrieve(index, query, store, top_k, min_score, ensure))
    best: dict[str, RetrievalRecord] = {}
    for record in sorted(all_records, key=lambda r: (-r.score, r.rank, r.retrieval_id)):
        best.setdefault(record.requirement_id, record)
    return all_records, best

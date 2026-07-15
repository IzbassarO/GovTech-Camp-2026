#!/usr/bin/env python3
"""Validate the Phase 0 dataset foundation using only the standard library."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
ANNOTATIONS = DATA / "annotations"
PROJECTS_MANIFEST = DATA / "manifests" / "projects.jsonl"
FILE_INVENTORY = DATA / "manifests" / "file_inventory.jsonl"

EXPECTED_PROJECT_IDS = {
    "project_001_bereke",
    "project_002_azm",
    "project_003_bayterek",
    "project_004_sintez_ural",
}

ALLOWED_DOCUMENT_TYPES = {
    "ndv",
    "pek",
    "puo",
    "ovvos",
    "roos",
    "action_plan",
    "nontechnical_summary",
    "explanatory_note",
    "working_project_note",
    "hearing_protocol",
    "motivated_refusal",
    "map",
    "photo",
    "appendix",
    "archive",
    "unknown",
}

ALLOWED_ROLES = {
    "model_input",
    "label_source",
    "auxiliary",
    "auxiliary_archive",
}

POST_REVIEW_DOCUMENT_TYPES = {
    "hearing_protocol",
    "motivated_refusal",
}


class Validator:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.project_count = 0
        self.document_count = 0

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def relative(self, path: Path) -> str:
        try:
            return path.relative_to(ROOT).as_posix()
        except ValueError:
            return str(path)

    def resolve_repo_path(self, value: Any, context: str) -> Path | None:
        if not isinstance(value, str) or not value:
            self.error(f"{context}: expected a non-empty relative path")
            return None

        candidate = Path(value)
        if candidate.is_absolute():
            self.error(f"{context}: absolute paths are forbidden: {value}")
            return None

        resolved = (ROOT / candidate).resolve()
        try:
            resolved.relative_to(ROOT)
        except ValueError:
            self.error(f"{context}: path escapes the repository: {value}")
            return None
        return resolved

    def load_json(self, path: Path, context: str) -> dict[str, Any] | None:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self.error(f"{context}: file does not exist: {self.relative(path)}")
            return None
        except UnicodeDecodeError as exc:
            self.error(f"{context}: not valid UTF-8: {exc}")
            return None

        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            self.error(f"{context}: invalid JSON: {exc}")
            return None

        if not isinstance(value, dict):
            self.error(f"{context}: top-level value must be a JSON object")
            return None
        return value

    def load_jsonl(self, path: Path, context: str) -> list[dict[str, Any]]:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self.error(f"{context}: file does not exist: {self.relative(path)}")
            return []
        except UnicodeDecodeError as exc:
            self.error(f"{context}: not valid UTF-8: {exc}")
            return []

        records: list[dict[str, Any]] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                self.error(f"{context}:{line_number}: blank JSONL line")
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                self.error(f"{context}:{line_number}: invalid JSON: {exc}")
                continue
            if not isinstance(value, dict):
                self.error(f"{context}:{line_number}: line must contain a JSON object")
                continue
            records.append(value)
        return records

    @staticmethod
    def sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def validate_source_metadata(self) -> dict[str, dict[str, Any]]:
        metadata_by_project: dict[str, dict[str, Any]] = {}

        for project_id in sorted(EXPECTED_PROJECT_IDS):
            path = RAW / project_id / "source_metadata.json"
            metadata = self.load_json(path, f"source metadata for {project_id}")
            if metadata is None:
                continue

            required = {
                "schema_version",
                "project_id",
                "project_name",
                "source_url",
                "downloaded_at",
                "region",
                "industry",
                "languages",
                "label_quality",
                "source_platform",
                "notes",
                "metadata_confidence",
            }
            missing = sorted(required - metadata.keys())
            if missing:
                self.error(f"{self.relative(path)}: missing fields: {', '.join(missing)}")

            if metadata.get("schema_version") != "1.0":
                self.error(f"{self.relative(path)}: schema_version must be 1.0")
            if metadata.get("project_id") != project_id:
                self.error(f"{self.relative(path)}: project_id does not match its directory")
            if not isinstance(metadata.get("languages"), list) or not metadata.get("languages"):
                self.error(f"{self.relative(path)}: languages must be a non-empty list")
            if "language" in metadata:
                self.error(f"{self.relative(path)}: legacy 'language' field is not allowed; use 'languages'")
            if metadata.get("source_url") is None:
                self.warn(f"{self.relative(path)}: source_url is unknown and requires manual verification")

            metadata_by_project[project_id] = metadata

        return metadata_by_project

    def validate_projects_manifest(
        self, metadata_by_project: dict[str, dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], set[str]]:
        projects = self.load_jsonl(PROJECTS_MANIFEST, "projects manifest")
        if len(projects) != 4:
            self.error(f"projects manifest: expected exactly 4 records, found {len(projects)}")

        seen_projects: set[str] = set()
        seen_documents: set[str] = set()
        seen_paths: set[str] = set()

        for index, project in enumerate(projects, start=1):
            context = f"projects manifest record {index}"
            project_id = project.get("project_id")
            if not isinstance(project_id, str):
                self.error(f"{context}: project_id must be a string")
                continue
            if project_id in seen_projects:
                self.error(f"{context}: duplicate project_id: {project_id}")
            seen_projects.add(project_id)

            if project.get("schema_version") != "1.0":
                self.error(f"{context}: schema_version must be 1.0")

            metadata_path = self.resolve_repo_path(
                project.get("source_metadata_path"), f"{context}.source_metadata_path"
            )
            expected_metadata_path = RAW / project_id / "source_metadata.json"
            if metadata_path is not None:
                if metadata_path != expected_metadata_path.resolve():
                    self.error(f"{context}: source_metadata_path does not match project_id")
                if not metadata_path.is_file():
                    self.error(f"{context}: source_metadata_path does not exist")

            metadata = metadata_by_project.get(project_id)
            if metadata is not None:
                for field in ("source_url", "region", "industry", "languages"):
                    if project.get(field) != metadata.get(field):
                        self.error(f"{context}: {field} disagrees with source_metadata.json")

            documents = project.get("documents")
            if not isinstance(documents, list):
                self.error(f"{context}: documents must be a list")
                continue

            for doc_index, document in enumerate(documents, start=1):
                doc_context = f"{context} document {doc_index}"
                if not isinstance(document, dict):
                    self.error(f"{doc_context}: document must be an object")
                    continue

                document_id = document.get("document_id")
                if not isinstance(document_id, str) or not document_id:
                    self.error(f"{doc_context}: document_id must be a non-empty string")
                elif document_id in seen_documents:
                    self.error(f"{doc_context}: duplicate document_id: {document_id}")
                else:
                    seen_documents.add(document_id)

                local_path_value = document.get("local_path")
                local_path = self.resolve_repo_path(local_path_value, f"{doc_context}.local_path")
                if isinstance(local_path_value, str):
                    if local_path_value in seen_paths:
                        self.error(f"{doc_context}: duplicate local_path: {local_path_value}")
                    seen_paths.add(local_path_value)
                    expected_prefix = f"data/raw/{project_id}/"
                    if not local_path_value.startswith(expected_prefix):
                        self.error(f"{doc_context}: local_path is outside its project raw directory")

                document_type = document.get("document_type")
                role = document.get("role")
                use_as_feature = document.get("use_as_model_feature")
                label_timing = document.get("label_timing")

                if document_type not in ALLOWED_DOCUMENT_TYPES:
                    self.error(f"{doc_context}: invalid document_type: {document_type!r}")
                if role not in ALLOWED_ROLES:
                    self.error(f"{doc_context}: invalid role: {role!r}")
                if not isinstance(use_as_feature, bool):
                    self.error(f"{doc_context}: use_as_model_feature must be boolean")
                if label_timing not in {"pre_review", "post_review", None}:
                    self.error(f"{doc_context}: invalid label_timing: {label_timing!r}")

                if role == "label_source" and use_as_feature is not False:
                    self.error(f"{doc_context}: label_source must not be a model feature")
                if label_timing == "post_review" and use_as_feature is not False:
                    self.error(f"{doc_context}: post_review document must not be a model feature")
                if document_type in POST_REVIEW_DOCUMENT_TYPES:
                    if role != "label_source" or use_as_feature is not False:
                        self.error(
                            f"{doc_context}: {document_type} must be a non-feature label_source"
                        )
                if role == "model_input":
                    if use_as_feature is not True or label_timing != "pre_review":
                        self.error(
                            f"{doc_context}: model_input must be a pre_review model feature"
                        )
                if role in {"auxiliary", "auxiliary_archive"} and use_as_feature is not False:
                    self.error(f"{doc_context}: auxiliary document must not be a model feature")

                expected_hash = document.get("sha256")
                if not isinstance(expected_hash, str) or len(expected_hash) != 64:
                    self.error(f"{doc_context}: sha256 must be a 64-character string")
                elif local_path is not None:
                    if not local_path.is_file():
                        self.error(f"{doc_context}: file does not exist: {local_path_value}")
                    else:
                        actual_hash = self.sha256(local_path)
                        if actual_hash != expected_hash:
                            self.error(
                                f"{doc_context}: SHA-256 mismatch for {local_path_value}"
                            )

        missing_projects = EXPECTED_PROJECT_IDS - seen_projects
        extra_projects = seen_projects - EXPECTED_PROJECT_IDS
        if missing_projects:
            self.error(f"projects manifest: missing projects: {sorted(missing_projects)}")
        if extra_projects:
            self.error(f"projects manifest: unexpected projects: {sorted(extra_projects)}")

        self.project_count = len(seen_projects)
        self.document_count = len(seen_documents)
        return projects, seen_paths

    def validate_annotation_location_and_schema(self) -> None:
        for json_path in sorted(RAW.rglob("*.json")):
            if json_path.name != "source_metadata.json":
                self.error(
                    f"annotation-like JSON is forbidden in data/raw: {self.relative(json_path)}"
                )

        weak_path = ANNOTATIONS / "project_002_azm" / "weak_findings.json"
        weak = self.load_json(weak_path, "weak findings")
        if weak is None:
            return

        if weak.get("schema_version") != "1.0":
            self.error("weak findings: schema_version must be 1.0")
        if weak.get("project_id") != "project_002_azm":
            self.error("weak findings: unexpected project_id")
        if weak.get("annotation_type") != "weak_labels":
            self.error("weak findings: annotation_type must be weak_labels")
        if weak.get("review_status") != "not_expert_verified":
            self.error("weak findings: review_status must be not_expert_verified")

        source_documents = weak.get("source_documents")
        if not isinstance(source_documents, list) or not source_documents:
            self.error("weak findings: source_documents must be a non-empty list")
        else:
            for index, value in enumerate(source_documents, start=1):
                path = self.resolve_repo_path(value, f"weak findings source_documents[{index}]")
                if path is not None and not path.is_file():
                    self.error(f"weak findings source document does not exist: {value}")

        findings = weak.get("findings")
        if not isinstance(findings, list):
            self.error("weak findings: findings must be a list")
            return

        seen_findings: set[str] = set()
        for index, finding in enumerate(findings, start=1):
            context = f"weak finding {index}"
            if not isinstance(finding, dict):
                self.error(f"{context}: must be an object")
                continue
            finding_id = finding.get("finding_id")
            if not isinstance(finding_id, str) or not finding_id:
                self.error(f"{context}: finding_id must be a non-empty string")
            elif finding_id in seen_findings:
                self.error(f"{context}: duplicate finding_id: {finding_id}")
            else:
                seen_findings.add(finding_id)

            if finding.get("confidence") != "weak":
                self.error(f"{context}: confidence must remain weak")
            if finding.get("expert_verified") is not False:
                self.error(f"{context}: expert_verified must be false")
            source_page = finding.get("source_page")
            if source_page is not None and (
                not isinstance(source_page, int) or isinstance(source_page, bool) or source_page < 1
            ):
                self.error(f"{context}: source_page must be null or a positive integer")

            source_path = self.resolve_repo_path(
                finding.get("source_document"), f"{context}.source_document"
            )
            if source_path is not None and not source_path.is_file():
                self.error(f"{context}: source_document does not exist")

            targets = finding.get("target_documents")
            if not isinstance(targets, list):
                self.error(f"{context}: target_documents must be a list")
            else:
                for target_index, target in enumerate(targets, start=1):
                    path = self.resolve_repo_path(
                        target, f"{context}.target_documents[{target_index}]"
                    )
                    if path is not None and not path.is_file():
                        self.error(f"{context}: target document does not exist: {target}")

    def validate_file_inventory(self) -> None:
        records = self.load_jsonl(FILE_INVENTORY, "file inventory")
        seen_paths: set[str] = set()
        # Volatile OS artifacts (e.g. .DS_Store) are classified by the audit as
        # ignored non-dataset artifacts; Finder rewrites or deletes them at
        # will, so their drift is a warning rather than a foundation error.
        volatile_paths: set[str] = set()

        for index, record in enumerate(records, start=1):
            context = f"file inventory record {index}"
            relative_path = record.get("relative_path")
            path = self.resolve_repo_path(relative_path, f"{context}.relative_path")
            is_volatile_artifact = record.get("status") == "ignored_non_dataset_artifact"
            if isinstance(relative_path, str):
                if relative_path == "data/manifests/file_inventory.jsonl":
                    self.error(f"{context}: inventory must not contain an unstable self-reference")
                if relative_path in seen_paths:
                    self.error(f"{context}: duplicate relative_path: {relative_path}")
                seen_paths.add(relative_path)
                if is_volatile_artifact:
                    volatile_paths.add(relative_path)

            expected_hash = record.get("sha256")
            if not isinstance(expected_hash, str) or len(expected_hash) != 64:
                self.error(f"{context}: sha256 must be a 64-character string")
            if path is not None:
                if not path.is_file():
                    if is_volatile_artifact:
                        self.warn(f"{context}: volatile non-dataset artifact is absent: {relative_path}")
                    else:
                        self.error(f"{context}: file does not exist: {relative_path}")
                elif is_volatile_artifact:
                    if record.get("size_bytes") != path.stat().st_size or (
                        isinstance(expected_hash, str)
                        and len(expected_hash) == 64
                        and self.sha256(path) != expected_hash
                    ):
                        self.warn(
                            f"{context}: volatile non-dataset artifact drifted: {relative_path}"
                        )
                else:
                    if record.get("size_bytes") != path.stat().st_size:
                        self.error(f"{context}: size mismatch: {relative_path}")
                    if isinstance(expected_hash, str) and len(expected_hash) == 64:
                        if self.sha256(path) != expected_hash:
                            self.error(f"{context}: SHA-256 mismatch: {relative_path}")

        # Derived pipeline outputs live under data/ but are not part of the
        # immutable dataset foundation covered by the audited inventory:
        # data/processed (Phase 0 ingestion), data/curated (Phase 0.5 dataset),
        # data/results (pillar outputs) and the generated expert-review
        # templates (P1, P2, P3). Raw files, manifests, source metadata and
        # original annotations remain fully covered.
        derived_prefixes = [
            (DATA / "processed").resolve(),
            (DATA / "curated").resolve(),
            (DATA / "results").resolve(),
        ]
        derived_files = {
            (DATA / "annotations" / "p1_review_template.jsonl").resolve(),
            (DATA / "annotations" / "p2_review_template.jsonl").resolve(),
            (DATA / "annotations" / "p3_review_template.jsonl").resolve(),
        }

        def _is_derived(path: Path) -> bool:
            resolved = path.resolve()
            if resolved in derived_files:
                return True
            for prefix in derived_prefixes:
                try:
                    resolved.relative_to(prefix)
                    return True
                except ValueError:
                    continue
            return False

        expected_paths = {
            path.relative_to(ROOT).as_posix()
            for path in DATA.rglob("*")
            if path.is_file()
            and path.resolve() != FILE_INVENTORY.resolve()
            and not _is_derived(path)
        }
        missing = sorted(expected_paths - seen_paths)
        extra = sorted(seen_paths - expected_paths - volatile_paths)
        if missing:
            self.error(f"file inventory: missing physical files: {missing}")
        if extra:
            self.error(f"file inventory: paths not present on disk: {extra}")

    def validate_raw_structure(self) -> None:
        raw_project_dirs = {path.name for path in RAW.iterdir() if path.is_dir()}
        missing = EXPECTED_PROJECT_IDS - raw_project_dirs
        extra = raw_project_dirs - EXPECTED_PROJECT_IDS
        if missing:
            self.error(f"data/raw: missing project directories: {sorted(missing)}")
        if extra:
            self.warn(f"data/raw: unexpected directories: {sorted(extra)}")

        ds_store = RAW / ".DS_Store"
        if ds_store.exists():
            self.warn("data/raw/.DS_Store is a non-dataset OS artifact; it remains ignored by Git")

    def run(self) -> int:
        metadata_by_project = self.validate_source_metadata()
        self.validate_projects_manifest(metadata_by_project)
        self.validate_annotation_location_and_schema()
        self.validate_file_inventory()
        self.validate_raw_structure()

        for message in self.errors:
            print(f"ERROR: {message}")
        for message in self.warnings:
            print(f"WARNING: {message}")

        status = "READY" if not self.errors else "NOT READY"
        print(f"Projects validated: {self.project_count}")
        print(f"Documents validated: {self.document_count}")
        print(f"Errors: {len(self.errors)}")
        print(f"Warnings: {len(self.warnings)}")
        print(f"Dataset foundation status: {status}")
        return 0 if not self.errors else 1


if __name__ == "__main__":
    sys.exit(Validator().run())

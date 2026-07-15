"""Project dependency graph: typed inter-project edges; reverse edges yield the suspected impact set (C-023)."""
from __future__ import annotations
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from plan_manager.domain.entity import DataclassEntity
from plan_manager.domain.runtime_validation import RuntimeValidationError
from plan_manager.domain.runtime_integrity import detect_cycle
from plan_manager.domain.external_project_reference import is_valid_external_project_id

class DependencyType(str, Enum):
    LIBRARY = "library"
    RUNTIME_ADAPTER = "runtime_adapter"
    API_CONTRACT = "api_contract"
    PROTOCOL = "protocol"
    GENERATED_CODE = "generated_code"
    CONTAINER_BASE = "container_base"
    DEPLOYMENT_BASE = "deployment_base"
    SHARED_SCHEMA = "shared_schema"
    TOOLING = "tooling"
    TEST_DEPENDENCY = "test_dependency"

class DiscoverySource(str, Enum):
    MANUAL = "manual"
    PROJECT_METADATA = "project_metadata"
    PACKAGING = "packaging"
    IMPORTS = "imports"
    CONTAINER_MANIFEST = "container_manifest"
    RUNTIME_REGISTRATION = "runtime_registration"
    CODE_ANALYSIS_SERVER = "code_analysis_server"

class DependencyConfidence(str, Enum):
    CONFIRMED = "confirmed"
    UNCONFIRMED = "unconfirmed"
    SUSPECTED = "suspected"

DEPENDENCY_TYPES: frozenset[str] = frozenset(t.value for t in DependencyType)
DISCOVERY_SOURCES: frozenset[str] = frozenset(s.value for s in DiscoverySource)
DEPENDENCY_CONFIDENCES: frozenset[str] = frozenset(c.value for c in DependencyConfidence)

@dataclass(frozen=True)
class ProjectDependency(DataclassEntity):
    ENTITY_TYPE = "project_dependency"
    ENTITY_ID_FIELD = "dependency_uuid"
    TABLE_NAME = "project_dependency"

    dependency_uuid: uuid.UUID
    dependent_project_id: uuid.UUID
    depends_on_project_id: uuid.UUID
    dependency_type: str
    version_constraint: str | None
    discovery_source: str
    confidence: str
    active: bool
    created_by: str
    created_at: str
    updated_at: str
    deleted_at: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "uuid": str(self.dependency_uuid),
            "dependent_project_id": str(self.dependent_project_id),
            "depends_on_project_id": str(self.depends_on_project_id),
            "dependency_type": self.dependency_type,
            "version_constraint": self.version_constraint,
            "discovery_source": self.discovery_source,
            "confidence": self.confidence,
            "active": self.active,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }


def validate_dependency_type(value: str) -> str:
    if value not in DEPENDENCY_TYPES:
        raise RuntimeValidationError(f"invalid dependency_type: {value!r}")
    return value


def validate_discovery_source(value: str) -> str:
    if value not in DISCOVERY_SOURCES:
        raise RuntimeValidationError(f"invalid discovery_source: {value!r}")
    return value


def validate_confidence(value: str) -> str:
    if value not in DEPENDENCY_CONFIDENCES:
        raise RuntimeValidationError(f"invalid confidence: {value!r}")
    return value


def validate_dependency_project_ids(dependent_project_id: uuid.UUID, depends_on_project_id: uuid.UUID) -> None:
    if not is_valid_external_project_id(dependent_project_id) or not is_valid_external_project_id(depends_on_project_id):
        raise RuntimeValidationError("dependent_project_id and depends_on_project_id must be valid external project references")
    if dependent_project_id == depends_on_project_id:
        raise RuntimeValidationError("a project_dependency edge may not be self-referential")


def guard_discovery_not_silently_confirmed(discovery_source: str, confidence: str) -> None:
    if discovery_source != DiscoverySource.MANUAL.value and confidence == DependencyConfidence.CONFIRMED.value:
        raise RuntimeValidationError("an automatically discovered dependency may not be silently confirmed")


def guard_no_dependency_cycle(edges: list[tuple[str, str]]) -> None:
    detect_cycle(edges)


def suspected_impact_targets(edges: list[tuple[str, str]], source_project_id: uuid.UUID) -> list[uuid.UUID]:
    reverse: dict[str, list[str]] = {}
    for dependent, depends_on in edges:
        reverse.setdefault(depends_on, []).append(dependent)
    origin = str(source_project_id)
    visited: set[str] = set()
    frontier = [origin]
    while frontier:
        current = frontier.pop()
        for dependent in reverse.get(current, []):
            if dependent not in visited and dependent != origin:
                visited.add(dependent)
                frontier.append(dependent)
    return sorted((uuid.UUID(v) for v in visited), key=str)

"""Runtime overlay document model: frozen record types assembling a plan's runtime overlay state into one serializable snapshot, symmetrically round-tripping to and from a structured payload (C-034)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TodoItemsSection:
    records: list[dict[str, Any]]

    def to_payload(self) -> dict[str, Any]:
        return {"records": self.records}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "TodoItemsSection":
        return cls(records=list(payload.get("records", [])))


@dataclass(frozen=True)
class TodoLinksSection:
    records: list[dict[str, Any]]

    def to_payload(self) -> dict[str, Any]:
        return {"records": self.records}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "TodoLinksSection":
        return cls(records=list(payload.get("records", [])))


@dataclass(frozen=True)
class ModelBindingsSection:
    records: list[dict[str, Any]]

    def to_payload(self) -> dict[str, Any]:
        return {"records": self.records}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ModelBindingsSection":
        return cls(records=list(payload.get("records", [])))


@dataclass(frozen=True)
class RuntimeCommentsSection:
    records: list[dict[str, Any]]

    def to_payload(self) -> dict[str, Any]:
        return {"records": self.records}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "RuntimeCommentsSection":
        return cls(records=list(payload.get("records", [])))


@dataclass(frozen=True)
class ExecutionAttemptsSection:
    records: list[dict[str, Any]]

    def to_payload(self) -> dict[str, Any]:
        return {"records": self.records}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ExecutionAttemptsSection":
        return cls(records=list(payload.get("records", [])))


@dataclass(frozen=True)
class ReviewResultsSection:
    records: list[dict[str, Any]]

    def to_payload(self) -> dict[str, Any]:
        return {"records": self.records}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ReviewResultsSection":
        return cls(records=list(payload.get("records", [])))


@dataclass(frozen=True)
class EscalationsSection:
    records: list[dict[str, Any]]

    def to_payload(self) -> dict[str, Any]:
        return {"records": self.records}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "EscalationsSection":
        return cls(records=list(payload.get("records", [])))


@dataclass(frozen=True)
class BugReportsSection:
    records: list[dict[str, Any]]

    def to_payload(self) -> dict[str, Any]:
        return {"records": self.records}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "BugReportsSection":
        return cls(records=list(payload.get("records", [])))


@dataclass(frozen=True)
class BugImpactsSection:
    records: list[dict[str, Any]]

    def to_payload(self) -> dict[str, Any]:
        return {"records": self.records}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "BugImpactsSection":
        return cls(records=list(payload.get("records", [])))


@dataclass(frozen=True)
class ProjectDependenciesSection:
    records: list[dict[str, Any]]

    def to_payload(self) -> dict[str, Any]:
        return {"records": self.records}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ProjectDependenciesSection":
        return cls(records=list(payload.get("records", [])))


@dataclass(frozen=True)
class BugFixesSection:
    records: list[dict[str, Any]]

    def to_payload(self) -> dict[str, Any]:
        return {"records": self.records}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "BugFixesSection":
        return cls(records=list(payload.get("records", [])))


@dataclass(frozen=True)
class BugFixPropagationsSection:
    records: list[dict[str, Any]]

    def to_payload(self) -> dict[str, Any]:
        return {"records": self.records}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "BugFixPropagationsSection":
        return cls(records=list(payload.get("records", [])))


@dataclass(frozen=True)
class RuntimeAuditLogSection:
    records: list[dict[str, Any]]

    def to_payload(self) -> dict[str, Any]:
        return {"records": self.records}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "RuntimeAuditLogSection":
        return cls(records=list(payload.get("records", [])))


@dataclass(frozen=True)
class CascadeRequestsSection:
    records: list[dict[str, Any]]

    def to_payload(self) -> dict[str, Any]:
        return {"records": self.records}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "CascadeRequestsSection":
        return cls(records=list(payload.get("records", [])))


@dataclass(frozen=True)
class RuntimeOverlaySnapshot:
    plan_uuid: uuid.UUID | None
    generated_at: str
    todo_items: TodoItemsSection
    todo_links: TodoLinksSection
    model_bindings: ModelBindingsSection
    runtime_comments: RuntimeCommentsSection
    execution_attempts: ExecutionAttemptsSection
    review_results: ReviewResultsSection
    escalations: EscalationsSection
    bug_reports: BugReportsSection
    bug_impacts: BugImpactsSection
    project_dependencies: ProjectDependenciesSection
    bug_fixes: BugFixesSection
    bug_fix_propagations: BugFixPropagationsSection
    runtime_audit_log: RuntimeAuditLogSection
    cascade_requests: CascadeRequestsSection

    def to_payload(self) -> dict[str, Any]:
        return {
            "plan_uuid": str(self.plan_uuid) if self.plan_uuid is not None else None,
            "generated_at": self.generated_at,
            "todo_items": self.todo_items.to_payload(),
            "todo_links": self.todo_links.to_payload(),
            "model_bindings": self.model_bindings.to_payload(),
            "runtime_comments": self.runtime_comments.to_payload(),
            "execution_attempts": self.execution_attempts.to_payload(),
            "review_results": self.review_results.to_payload(),
            "escalations": self.escalations.to_payload(),
            "bug_reports": self.bug_reports.to_payload(),
            "bug_impacts": self.bug_impacts.to_payload(),
            "project_dependencies": self.project_dependencies.to_payload(),
            "bug_fixes": self.bug_fixes.to_payload(),
            "bug_fix_propagations": self.bug_fix_propagations.to_payload(),
            "runtime_audit_log": self.runtime_audit_log.to_payload(),
            "cascade_requests": self.cascade_requests.to_payload(),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "RuntimeOverlaySnapshot":
        plan_uuid_value = payload.get("plan_uuid")
        return cls(
            plan_uuid=uuid.UUID(plan_uuid_value) if plan_uuid_value is not None else None,
            generated_at=payload["generated_at"],
            todo_items=TodoItemsSection.from_payload(payload.get("todo_items", {})),
            todo_links=TodoLinksSection.from_payload(payload.get("todo_links", {})),
            model_bindings=ModelBindingsSection.from_payload(payload.get("model_bindings", {})),
            runtime_comments=RuntimeCommentsSection.from_payload(payload.get("runtime_comments", {})),
            execution_attempts=ExecutionAttemptsSection.from_payload(payload.get("execution_attempts", {})),
            review_results=ReviewResultsSection.from_payload(payload.get("review_results", {})),
            escalations=EscalationsSection.from_payload(payload.get("escalations", {})),
            bug_reports=BugReportsSection.from_payload(payload.get("bug_reports", {})),
            bug_impacts=BugImpactsSection.from_payload(payload.get("bug_impacts", {})),
            project_dependencies=ProjectDependenciesSection.from_payload(payload.get("project_dependencies", {})),
            bug_fixes=BugFixesSection.from_payload(payload.get("bug_fixes", {})),
            bug_fix_propagations=BugFixPropagationsSection.from_payload(payload.get("bug_fix_propagations", {})),
            runtime_audit_log=RuntimeAuditLogSection.from_payload(payload.get("runtime_audit_log", {})),
            cascade_requests=CascadeRequestsSection.from_payload(payload.get("cascade_requests", {})),
        )

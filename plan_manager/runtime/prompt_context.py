from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PromptContextTodo:
    todo_uuid: uuid.UUID
    title: str
    kind: str
    status: str
    priority_nice: int


@dataclass(frozen=True)
class PromptContextBug:
    bug_uuid: uuid.UUID
    title: str
    severity: str
    status: str


@dataclass(frozen=True)
class PromptContextNote:
    comment_uuid: uuid.UUID
    kind: str
    visibility: str
    body: str


@dataclass(frozen=True)
class PromptContextAttempt:
    attempt_uuid: uuid.UUID
    status: str
    result_summary: str | None
    error: str | None


@dataclass(frozen=True)
class PromptContextReview:
    review_uuid: uuid.UUID
    status: str
    findings: str | None


@dataclass(frozen=True)
class PromptContextModelBinding:
    source_binding_uuid: uuid.UUID
    effective_provider: str
    effective_model: str
    source: str


@dataclass(frozen=True)
class PromptContextEscalation:
    escalation_uuid: uuid.UUID
    reason: str
    status: str


@dataclass(frozen=True)
class PromptContextLimits:
    """Size limits; the assembler truncates to these and sets truncated=True when anything is dropped."""
    max_todos: int = 5
    max_bugs: int = 5
    max_notes: int = 10
    max_attempts: int = 3
    max_reviews: int = 3
    max_escalations: int = 3


DEFAULT_PROMPT_CONTEXT_LIMITS = PromptContextLimits()


@dataclass(frozen=True)
class RuntimePromptContext:
    target_plan_uuid: uuid.UUID | None
    target_step_uuid: uuid.UUID | None
    target_step_path: str | None
    context_kind: str
    todos: list[PromptContextTodo] = field(default_factory=list)
    blocker_bugs: list[PromptContextBug] = field(default_factory=list)
    notes: list[PromptContextNote] = field(default_factory=list)
    failed_attempts: list[PromptContextAttempt] = field(default_factory=list)
    review_findings: list[PromptContextReview] = field(default_factory=list)
    model_binding: PromptContextModelBinding | None = None
    escalations: list[PromptContextEscalation] = field(default_factory=list)
    truncated: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "target_plan_uuid": str(self.target_plan_uuid) if self.target_plan_uuid is not None else None,
            "target_step_uuid": str(self.target_step_uuid) if self.target_step_uuid is not None else None,
            "target_step_path": self.target_step_path,
            "context_kind": self.context_kind,
            "todos": [
                {
                    "todo_uuid": str(t.todo_uuid),
                    "title": t.title,
                    "kind": t.kind,
                    "status": t.status,
                    "priority_nice": t.priority_nice,
                }
                for t in self.todos
            ],
            "blocker_bugs": [
                {
                    "bug_uuid": str(b.bug_uuid),
                    "title": b.title,
                    "severity": b.severity,
                    "status": b.status,
                }
                for b in self.blocker_bugs
            ],
            "notes": [
                {
                    "comment_uuid": str(n.comment_uuid),
                    "kind": n.kind,
                    "visibility": n.visibility,
                    "body": n.body,
                }
                for n in self.notes
            ],
            "failed_attempts": [
                {
                    "attempt_uuid": str(a.attempt_uuid),
                    "status": a.status,
                    "result_summary": a.result_summary,
                    "error": a.error,
                }
                for a in self.failed_attempts
            ],
            "review_findings": [
                {
                    "review_uuid": str(r.review_uuid),
                    "status": r.status,
                    "findings": r.findings,
                }
                for r in self.review_findings
            ],
            "model_binding": (
                None
                if self.model_binding is None
                else {
                    "source_binding_uuid": str(self.model_binding.source_binding_uuid),
                    "effective_provider": self.model_binding.effective_provider,
                    "effective_model": self.model_binding.effective_model,
                    "source": self.model_binding.source,
                }
            ),
            "escalations": [
                {
                    "escalation_uuid": str(e.escalation_uuid),
                    "reason": e.reason,
                    "status": e.status,
                }
                for e in self.escalations
            ],
            "truncated": self.truncated,
        }

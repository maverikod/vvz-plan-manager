"""Answer-envelope domain: the stored discriminated answer form of a batch call (C-010)."""
from __future__ import annotations
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from plan_manager.domain.entity import DataclassEntity
from plan_manager.domain.runtime_validation import RuntimeValidationError


class AnswerEnvelopeKind(str, Enum):
    RESULT = "result"
    ESCALATION = "escalation"
    TOOL_CALL = "tool_call"


ANSWER_ENVELOPE_KINDS: frozenset[str] = frozenset(k.value for k in AnswerEnvelopeKind)

DEFAULT_ENVELOPE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class AnswerEnvelope(DataclassEntity):
    ENTITY_TYPE = "answer_envelope"
    ENTITY_ID_FIELD = "envelope_uuid"
    TABLE_NAME = "answer_envelope"

    envelope_uuid: uuid.UUID
    kind: str
    schema_version: int
    payload: dict[str, Any]
    anchor_plan_uuid: uuid.UUID | None
    anchor_step_uuid: uuid.UUID | None
    attempt_uuid: uuid.UUID | None
    created_by: str
    created_at: str
    updated_at: str
    deleted_at: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "uuid": str(self.envelope_uuid),
            "envelope_uuid": str(self.envelope_uuid),
            "kind": self.kind,
            "schema_version": self.schema_version,
            "payload": self.payload,
            "anchor_plan_uuid": str(self.anchor_plan_uuid) if self.anchor_plan_uuid is not None else None,
            "anchor_step_uuid": str(self.anchor_step_uuid) if self.anchor_step_uuid is not None else None,
            "attempt_uuid": str(self.attempt_uuid) if self.attempt_uuid is not None else None,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }


def validate_answer_envelope_kind(value: str) -> str:
    if value in ANSWER_ENVELOPE_KINDS:
        return value
    raise RuntimeValidationError(f"invalid answer envelope kind: {value!r}")


def validate_answer_envelope(kind: str, schema_version: int, payload: dict[str, Any]) -> None:
    validate_answer_envelope_kind(kind)
    if not isinstance(schema_version, int) or schema_version < 1:
        raise RuntimeValidationError(f"schema_version must be an int >= 1, got {schema_version!r}")
    if not isinstance(payload, dict):
        raise RuntimeValidationError(f"payload must be a dict, got {type(payload).__name__}")

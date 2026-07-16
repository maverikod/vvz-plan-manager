"""Produced-artifact-versus-frozen-step comparison support for
step_prompt_verify (C-006).

Builds on the shipped per-field content-hashing foundation (C-007):
plan_manager.views.step_fingerprint.step_field_hash, consumed unchanged.
This module adds candidate-content resolution, frozen-target-content
selection (whole step, one field, or one fenced code block within a
step's field text), and the fenced-code-block extraction helper. Every
function in this module is a pure, read-only computation: none of them
mutate the database or the Step objects passed to them.
"""

from __future__ import annotations

import base64
import binascii
import difflib
import hashlib
import re

from plan_manager.domain.step import Step
from plan_manager.storage.canonical import content_hash
from plan_manager.views.prompt_assembly import step_content
from plan_manager.views.step_fingerprint import step_field_hash

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

_FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


def resolve_candidate_bytes(
    candidate_base64: str | None, candidate_sha256: str | None
) -> tuple[bytes | None, str]:
    """Resolve the candidate content input to (candidate_bytes, candidate_digest).

    Exactly one of candidate_base64 or candidate_sha256 must be given.

    Args:
        candidate_base64: Candidate content as standard base64 text, or
            None.
        candidate_sha256: Candidate content as a lowercase hex sha256
            digest, or None.

    Returns:
        A tuple (candidate_bytes, candidate_digest): candidate_bytes is
        the decoded bytes when candidate_base64 was given, else None;
        candidate_digest is the sha256 hex digest of candidate_bytes when
        candidate_base64 was given, else the validated candidate_sha256
        value unchanged.

    Raises:
        ValueError: If neither or both of candidate_base64 and
            candidate_sha256 are given, if candidate_base64 is not valid
            base64, or if candidate_sha256 does not match
            ^[0-9a-f]{64}$.
    """
    if (candidate_base64 is None) == (candidate_sha256 is None):
        raise ValueError(
            "provide exactly one of candidate_base64 or candidate_sha256"
        )
    if candidate_base64 is not None:
        try:
            decoded = base64.b64decode(candidate_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"candidate_base64 is not valid base64: {exc}") from exc
        return decoded, hashlib.sha256(decoded).hexdigest()
    if not _SHA256_HEX_RE.match(candidate_sha256):
        raise ValueError(
            "candidate_sha256 is not a valid lowercase hex sha256 digest"
        )
    return None, candidate_sha256


def extract_fenced_block(text: str, block_index: int) -> str:
    """Extract the body text of the block_index-th fenced code block in text.

    Fenced code blocks are delimited by a line starting with three
    backticks (optionally followed by a language tag) and a closing line
    of three backticks, matched with the regular expression
    r"```[^\\n]*\\n(.*?)```" in re.DOTALL mode. block_index is 0-based, in
    the order blocks appear in text.

    Args:
        text: The text to search (a step field's value).
        block_index: 0-based index of the fenced block to extract.

    Returns:
        The exact text between the opening and closing fence lines of the
        block_index-th match, unmodified.

    Raises:
        ValueError: If text contains fewer than block_index + 1 fenced
            code blocks.
    """
    matches = _FENCE_RE.findall(text)
    if block_index >= len(matches):
        raise ValueError(
            f"block_index {block_index} out of range: text contains "
            f"{len(matches)} fenced code block(s)"
        )
    return matches[block_index]


def resolve_target_content(
    step: Step, field: str | None, block_index: int | None
) -> tuple[str, str]:
    """Resolve the frozen target content and its canonical hash for one step.

    Exactly one selector mode applies: whole-step, field, or
    field-plus-block. field and block_index may each independently be
    None; block_index is only meaningful together with a non-None field.

    Args:
        step: The frozen Step being verified against.
        field: When given, the key into step.fields whose value is the
            target content; when None together with block_index None,
            the target content is the whole step's canonical content via
            step_content(step).
        block_index: When given together with field, the 0-based index
            of the fenced code block to extract from
            str(step.fields[field]) as the target content, in place of
            the whole field value.

    Returns:
        A tuple (target_content, canonical_hash): target_content is the
        selected text; canonical_hash is step_field_hash(step, field)
        when field is given, or content_hash of a dict with keys
        step_id, level, depends_on, concepts, project_id, status, fields
        (taken from the matching step attributes) when field is None.

    Raises:
        KeyError: If field is given but is not a key of step.fields.
        ValueError: If block_index is given but field is None, or if the
            field's value contains fewer than block_index + 1 fenced
            code blocks.
    """
    if field is None:
        if block_index is not None:
            raise ValueError("block_index requires field to be given")
        whole_text = step_content(step)
        whole_hash = content_hash(
            {
                "step_id": step.step_id,
                "level": step.level,
                "depends_on": step.depends_on,
                "concepts": step.concepts,
                "project_id": step.project_id,
                "status": step.status,
                "fields": step.fields,
            }
        )
        return whole_text, whole_hash
    field_hash = step_field_hash(step, field)
    field_value = step.fields[field]
    if block_index is None:
        return str(field_value), field_hash
    block_text = extract_fenced_block(str(field_value), block_index)
    return block_text, content_hash(block_text)


def compare_verdict(
    target_content: str,
    candidate_bytes: bytes | None,
    candidate_digest: str,
    canonical_hash: str,
) -> dict:
    """Compute the match verdict for one step_prompt_verify comparison.

    Args:
        target_content: The frozen target content text, as resolved by
            resolve_target_content.
        candidate_bytes: The decoded candidate bytes, or None when only a
            digest was supplied.
        candidate_digest: The sha256 hex digest of the candidate content.
        canonical_hash: The canonical content hash of target_content, as
            returned by resolve_target_content.

    Returns:
        A dict with keys:
        - "match": True when candidate_digest equals the sha256 hex
          digest of target_content.encode("utf-8"), else False.
        - "canonical_content_hash": canonical_hash, unchanged.
        - "unified_diff": present only when match is False and
          candidate_bytes is not None; the unified diff produced by
          difflib.unified_diff(target_content.splitlines(keepends=True),
          candidate_bytes.decode("utf-8", errors="replace").splitlines(keepends=True),
          fromfile="target", tofile="candidate"), joined into one string
          with "".join(...).
        - "first_divergence_offset": present only when match is False and
          candidate_bytes is not None; the 0-based byte offset of the
          first byte at which target_content.encode("utf-8") and
          candidate_bytes differ, computed by scanning both byte
          sequences in lockstep from offset 0 and stopping at the first
          index where the bytes differ, or at the length of the shorter
          sequence when one is a strict prefix of the other.
    """
    target_bytes = target_content.encode("utf-8")
    target_digest = hashlib.sha256(target_bytes).hexdigest()
    match = target_digest == candidate_digest
    result: dict = {"match": match, "canonical_content_hash": canonical_hash}
    if not match and candidate_bytes is not None:
        candidate_text = candidate_bytes.decode("utf-8", errors="replace")
        diff_lines = difflib.unified_diff(
            target_content.splitlines(keepends=True),
            candidate_text.splitlines(keepends=True),
            fromfile="target",
            tofile="candidate",
        )
        result["unified_diff"] = "".join(diff_lines)
        offset = 0
        shorter = min(len(target_bytes), len(candidate_bytes))
        while offset < shorter and target_bytes[offset] == candidate_bytes[offset]:
            offset += 1
        result["first_divergence_offset"] = offset
    return result

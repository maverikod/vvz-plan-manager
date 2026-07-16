"""Metadata for the step_prompt_verify command (C-006)."""

from typing import Any


def get_step_prompt_verify_metadata(cls: type) -> dict[str, Any]:
    """Return the full metadata dictionary for StepPromptVerifyCommand.

    Args:
        cls: The StepPromptVerifyCommand class, providing name, version,
            descr, category, author, email class attributes.

    Returns:
        dict: Metadata dictionary conforming to metadatastd.yaml
            required_fields: name, version, description, category,
            author, email, detailed_description, parameters,
            return_value, usage_examples, error_cases, best_practices.
    """
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Server-side byte/hash verification of a produced artifact against a frozen "
            "step prompt (C-006): resolves a step by path or uuid, resolves candidate "
            "content supplied as base64 bytes or a sha256 digest, optionally narrows the "
            "comparison to one step field or to one fenced code block within a field's "
            "text, and returns a single match verdict with the canonical per-field content "
            "hash, plus a unified diff or the first-divergence byte offset on mismatch when "
            "candidate bytes were supplied. Reuses the shipped step_field_hash content-"
            "hashing foundation (C-007) unchanged. Read-only: never mutates a step or any "
            "other plan artifact. Returns one verdict object, not a paginated list."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (name or uuid) resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            "step": {
                "description": "Step reference (uuid, canonical path, or step_id) of the frozen step to verify against.",
                "type": "string",
                "required": True,
            },
            "candidate_base64": {
                "description": "Candidate artifact content as standard base64 text; provide either this or candidate_sha256, not both.",
                "type": "string",
                "required": False,
            },
            "candidate_sha256": {
                "description": "Candidate artifact content as a precomputed lowercase hex sha256 digest; provide either this or candidate_base64, not both.",
                "type": "string",
                "required": False,
            },
            "field": {
                "description": "Optional step field name to narrow the comparison to one field; omit to compare the whole step content.",
                "type": "string",
                "required": False,
            },
            "block_index": {
                "description": "Optional 0-based index of a fenced code block within the named field's text to narrow the comparison further; requires field to be given.",
                "type": "integer",
                "required": False,
            },
        },
        "return_value": {
            "success": {
                "description": (
                    "The single verdict of comparing candidate content against the "
                    "resolved step's target content."
                ),
                "data": {
                    "step": "Canonical path of the verified step.",
                    "field": "The field name used to narrow the comparison, or null when the whole step content was compared.",
                    "block_index": "The fenced-block index used to narrow the comparison further, or null.",
                    "match": "True when candidate content matches the target content exactly.",
                    "canonical_content_hash": "The canonical content hash of the target content that was compared.",
                    "unified_diff": "Unified diff between target and candidate content, present only on mismatch when candidate bytes were supplied.",
                    "first_divergence_offset": "Byte offset of the first divergent byte, present only on mismatch when candidate bytes were supplied.",
                },
                "example": {
                    "step": "G-003/T-001",
                    "field": "description",
                    "block_index": None,
                    "match": False,
                    "canonical_content_hash": "3b1c...e2a9",
                    "unified_diff": "--- target\n+++ candidate\n@@ -1 +1 @@\n-old text\n+new text\n",
                    "first_divergence_offset": 3,
                },
            },
            "error": {
                "description": (
                    "Domain error returned when the plan or step cannot be resolved, "
                    "the field/block selector is unknown, or the candidate content is malformed."
                ),
                "code": "PLAN_NOT_FOUND | STEP_NOT_FOUND | AMBIGUOUS_STEP_ID | UNKNOWN_STEP_SELECTOR | INVALID_CANDIDATE_CONTENT",
                "message": "Human-readable message identifying the error condition.",
                "details": "Additional context specific to the error type.",
            },
        },
        "usage_examples": [
            {
                "description": "Verify a produced artifact's bytes against a step's whole content.",
                "command": {
                    "plan": "plan_manager",
                    "step": "G-003/T-001",
                    "candidate_base64": "eyJmb28iOiAiYmFyIn0=",
                },
                "explanation": "Decodes the base64 candidate, compares it against the whole canonical content of G-003/T-001, and returns the match verdict.",
            },
            {
                "description": "Verify only one fenced code block of a step's prompt field against a precomputed digest.",
                "command": {
                    "plan": "plan_manager",
                    "step": "G-003/T-001/A-001",
                    "candidate_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                    "field": "prompt",
                    "block_index": 0,
                },
                "explanation": "Extracts the first fenced code block from the prompt field of A-001 and compares its canonical hash against the supplied digest.",
            },
        ],
        "error_cases": {
            "STEP_NOT_FOUND": {
                "description": "The step reference does not resolve to any step in the plan.",
                "message": "step not found: {step}",
                "solution": "Call step_tree to list valid step identifiers for the plan.",
            },
            "AMBIGUOUS_STEP_ID": {
                "description": "A bare local step_id such as T-001 or A-001 resolves to more than one step.",
                "message": "step_id {step} resolves to multiple steps",
                "solution": "Retry with the canonical step path or the step UUID.",
            },
            "UNKNOWN_STEP_SELECTOR": {
                "description": "The field parameter names a field absent from the step, or block_index is out of range for that field's fenced code blocks, or block_index was given without field.",
                "message": "unknown field or block selector on step {step}",
                "solution": "Call step_get on the step to inspect its actual field names and prompt content before retrying.",
            },
            "INVALID_CANDIDATE_CONTENT": {
                "description": "Neither or both of candidate_base64 and candidate_sha256 were given, candidate_base64 is not valid base64, or candidate_sha256 is not a valid lowercase hex sha256 digest.",
                "message": "candidate content is invalid",
                "solution": "Provide exactly one of candidate_base64 (valid base64 text) or candidate_sha256 (a 64-character lowercase hex digest).",
            },
        },
        "best_practices": [
            "Omit both field and block_index to compare against the whole step's canonical content.",
            "Use field alone to compare against one step field's value; add block_index only to narrow further to one fenced code block within that field.",
            "Prefer candidate_sha256 when the artifact is large and only a digest is available; unified_diff and first_divergence_offset are only produced when candidate_base64 was supplied.",
            "Use canonical_content_hash to cache verified results without re-fetching the step.",
            "This command never mutates the step; re-run it after any step_update to confirm the new frozen content.",
        ],
    }

"""BranchPromptCommand: assemble the deterministic executor prompt for one branch."""
from typing import Any, Dict


def get_branch_prompt_metadata(cls: type) -> Dict[str, Any]:
    """Return extended AI/documentation metadata for BranchPromptCommand.

    :param cls: The command class requesting its metadata
        (BranchPromptCommand). The returned dict reads cls.name,
        cls.version, cls.descr, cls.category, cls.author, cls.email.
    :return: A dictionary with the required metadata fields: name,
        version, description, category, author, email,
        detailed_description, parameters, return_value, usage_examples,
        error_cases, best_practices.
    """
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Resolves one branch of the plan tree by its global step, "
            "tactical step, and atomic step identifiers, assembles the "
            "deterministic executor prompt for that branch in the fixed "
            "concatenation order (MRS excerpt, HRS slice, GS, TS, AS "
            "delta), and returns the prompt text together with a token "
            "estimate compared against the plan's user-set context "
            "budget (plan data, default 4000 tokens, never server "
            "configuration). This command is read-only: it does not "
            "modify the plan, the branch, or any stored artifact. An "
            "unknown plan yields PLAN_NOT_FOUND; an unknown step id in "
            "the branch path yields STEP_NOT_FOUND naming the missing "
            "step."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (name or UUID) resolved against the plan catalog.",
                "type": "string",
                "required": True,
            },
            "gs_step_id": {
                "description": "The level-3 global step id (e.g. 'G-005') of the branch.",
                "type": "string",
                "required": True,
            },
            "ts_step_id": {
                "description": "The level-4 tactical step id (e.g. 'T-008') of the branch.",
                "type": "string",
                "required": True,
            },
            "as_step_id": {
                "description": "The level-5 atomic step id (e.g. 'A-001') of the branch.",
                "type": "string",
                "required": True,
            },
        },
        "return_value": {
            "success": {
                "description": "The assembled prompt with its token estimate and budget verdict.",
                "data": {
                    "prompt": "The assembled executor prompt text.",
                    "token_estimate": "Estimated token count of the prompt text.",
                    "context_budget": "The plan's user-set context budget in tokens.",
                    "within_budget": "True when token_estimate does not exceed context_budget.",
                },
                "example": {
                    "prompt": "...",
                    "token_estimate": 1200,
                    "context_budget": 4000,
                    "within_budget": True,
                },
            },
            "error": {
                "description": "The plan or one of the three step identifiers could not be resolved.",
                "code": "PLAN_NOT_FOUND | STEP_NOT_FOUND",
                "message": "Human-readable description of the missing entity.",
                "details": "Additional diagnostic fields when available.",
            },
        },
        "usage_examples": [
            {
                "description": "Assemble the executor prompt for one atomic step.",
                "command": {
                    "plan": "plan_manager",
                    "gs_step_id": "G-005",
                    "ts_step_id": "T-008",
                    "as_step_id": "A-001",
                },
                "explanation": "Returns the prompt text, its token estimate, and the budget verdict.",
            }
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a plan in the catalog.",
                "message": "Plan not found: {plan}",
                "solution": "Call the plan catalog command and retry with a valid plan identifier.",
            },
            "STEP_NOT_FOUND": {
                "description": "One of gs_step_id, ts_step_id, or as_step_id does not resolve within the plan.",
                "message": "Step not found: {step_id}",
                "solution": "Call the plan tree command to discover valid step ids and retry.",
            },
            "PROMPT_ASSEMBLY_FAILED": {
                "description": "The prompt assembler could not resolve a concept_id referenced by the branch's MRS/GS/TS/AS content to an existing concept row while building the deterministic prompt.",
                "message": "no concept row for {concept_id}",
                "solution": "Fix the dangling concept_id reference in the branch's content (or add the missing concept via concept_add) and retry.",
            },
        },
        "best_practices": [
            "Check within_budget before handing the prompt to a coder model; a False value means the assembled prompt exceeds the plan's context budget and the branch should be split further.",
            "This command is read-only and safe to call repeatedly; it never mutates the plan.",
        ],
    }

"""Extended AI/documentation metadata for the files_report command."""

from typing import Any

def get_files_report_metadata(cls: type) -> dict[str, Any]:
    """Return the extended metadata dictionary for FilesReportCommand.

    Args:
        cls: The FilesReportCommand class object, used to source identity
            attributes (name, version, category, author, email) so the
            metadata dictionary never drifts from the class definition.

    Returns:
        A dictionary with the required metadata fields: name, version,
        description, category, author, email, detailed_description,
        parameters, return_value, usage_examples, error_cases,
        best_practices.
    """
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Returns the target_file to writer-steps matrix for a plan "
            "scope (FilesWriterReport, C-004): for every target_file "
            "touched by an atomic step in scope, lists the writing steps "
            "in ascending priority order together with each writer's "
            "operation kind (create_file, modify_file, delete_file, or "
            "rename_file), and flags an ordering conflict when two "
            "writers of the same file have no directed dependency path "
            "between them. Output is paginated per UniformPagination "
            "(C-001): each page carries its file entries alongside "
            "total_count, the count of matching file entries before "
            "pagination. This is a read-only command: it never mutates "
            "the plan and performs no admission or cascade checks."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or name) resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            "scope": {
                "description": "Optional scope: whole_plan, G-NNN, or G-NNN/T-NNN. Defaults to whole_plan.",
                "type": "string",
                "required": False,
            },
            "limit": {
                "description": "Maximum number of file entries to return (default 50, max 200).",
                "type": "integer",
                "required": False,
            },
            "offset": {
                "description": "Number of file entries to skip before returning results (default 0).",
                "type": "integer",
                "required": False,
            },
        },
        "return_value": {
            "success": {
                "description": "A page of file-entry payloads plus the total match count before pagination.",
                "data": {
                    "files": (
                        "List of {target_file, writers, ordering_conflict} entries, "
                        "sorted ascending by target_file. Each writers entry is a "
                        "list of {step, priority, operation} dicts sorted ascending "
                        "by priority."
                    ),
                    "total_count": "Total count of matching file entries before pagination.",
                },
                "example": {
                    "files": [
                        {
                            "target_file": "plan_manager/commands/example_command.py",
                            "writers": [
                                {
                                    "step": "G-002/T-003/A-001",
                                    "priority": 1,
                                    "operation": "create_file",
                                },
                                {
                                    "step": "G-002/T-004/A-002",
                                    "priority": 1,
                                    "operation": "modify_file",
                                },
                            ],
                            "ordering_conflict": True,
                        }
                    ],
                    "total_count": 1,
                },
            },
            "error": {
                "description": "A domain error result carrying a stable string code.",
                "code": "Stable domain error code (see error_cases).",
                "message": "Human-readable error message.",
                "details": "Additional diagnostic fields when available.",
            },
        },
        "usage_examples": [
            {
                "description": "List the files-to-writers report for the whole plan.",
                "command": {"plan": "plan_manager"},
                "explanation": "Returns the first page of target_file entries across the whole plan.",
            },
            {
                "description": "List the files-to-writers report scoped to one global step.",
                "command": {"plan": "plan_manager", "scope": "G-002", "limit": 20},
                "explanation": "Restricts the matrix to atomic steps structurally contained in G-002.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a plan in the catalog.",
                "message": "plan not found: {plan}",
                "solution": "Call the plan catalog command and retry with a valid plan identifier.",
            },
            "INVALID_SCOPE": {
                "description": "scope is not omitted, 'whole_plan', 'G-NNN', or 'G-NNN/T-NNN'.",
                "message": "scope must be omitted, 'whole_plan', 'G-NNN', or 'G-NNN/T-NNN'",
                "solution": "Retry with a valid scope string.",
            },
            "STEP_NOT_FOUND": {
                "description": "scope names a G-NNN or G-NNN/T-NNN branch that does not exist in the plan.",
                "message": "no global step found for scope {scope} (or no tactical step found for scope {scope})",
                "solution": "Call step_tree to list valid step_id values for the plan.",
            },
            "INVALID_PAGINATION": {
                "description": "limit or offset is out of range or not an integer.",
                "message": "limit must be >= 1, got {limit} (or offset must be >= 0, got {offset})",
                "solution": "Retry with limit in [1, 200] and a non-negative offset.",
            },
        },
        "best_practices": [
            "Use scope to restrict the report to one global step or tactical step branch instead of paging through the whole plan.",
            "ordering_conflict flags a file whenever two writers of it have no directed dependency path between them; add an explicit depends_on edge (or a same-file priority chain under one parent) to resolve it.",
            "total_count reflects the number of distinct target_file entries before pagination, not the page size — use it to detect additional pages.",
        ],
    }

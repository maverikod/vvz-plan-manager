"""Cascade preview command: reports the open cascade's change set and gate."""

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.cascade.record import get_open_cascade
from plan_manager.cascade.preview import preview_cascade
from plan_manager.commands.cascade_preview_metadata import get_cascade_preview_metadata
from plan_manager.commands.cascade_preview_projection import (
    category_metadata_params,
    category_schema_properties,
    filter_entries,
    parse_category,
    summarize,
)
from plan_manager.commands.list_projection import VIEW_SUMMARY, parse_view
from plan_manager.commands.cascade_preview_projection import view_metadata_params, view_schema_properties
from plan_manager.commands.runtime_filtering import (
    filter_metadata_params,
    filter_schema_properties,
    pagination_metadata_params,
    pagination_schema_properties,
    parse_filters,
    parse_pagination,
)

# entity_type/step/status are the pre-existing generic filter vocabulary
# (runtime_filtering.FILTER_FIELDS); category/check_id are cascade_preview-
# specific (cascade_preview_projection). Together they cover the spec's
# "change kind", "entity level/type", "step/status/revision scope", and
# "review/gate category" filter dimensions (todo 3c762bfe) -- "revision"
# scope is not applicable here (base/tip are the cascade's own fixed
# endpoints, not a caller-selectable axis).
_GENERIC_DETAIL_FILTER_FIELDS = ["entity_type", "step", "status"]


class CascadePreviewCommand(Command):
    """Read-only report of the open cascade's change set and gate verdict."""

    name = "cascade_preview"
    version = "1.1.0"
    descr = (
        "Report compact summary counts (added/removed/changed/needs_review/"
        "gate_findings) of a plan's open cascade by default; view=full adds "
        "the paginated, filterable detail entries."
    )
    category = "cascade"
    author = "Vasiliy Zdanovskiy"
    email = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue = False

    @classmethod
    def get_schema(cls) -> dict:
        """Return the JSON Schema for cascade_preview input parameters.

        Returns:
            A JSON Schema object requiring "plan" and accepting the
            optional view/pagination/category/check_id/entity_type/step/
            status detail-projection parameters.
        """
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan UUID or unique plan name.",
                },
                **view_schema_properties(),
                **pagination_schema_properties(),
                **category_schema_properties(),
                **filter_schema_properties(_GENERIC_DETAIL_FILTER_FIELDS),
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict:
        """Return the extended documentation metadata for cascade_preview.

        Returns:
            The dictionary produced by get_cascade_preview_metadata(cls).
        """
        return get_cascade_preview_metadata(cls)

    def validate_params(self, params: dict) -> dict:
        """Validate cascade_preview input parameters.

        Args:
            params: Raw input parameters as received by the command.

        Returns:
            The validated parameters dictionary.
        """
        params = super().validate_params(params)
        return params

    async def execute(
        self,
        plan: str,
        view: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        category: str | None = None,
        check_id: str | None = None,
        entity_type: str | None = None,
        step: str | None = None,
        status: str | None = None,
        context: object | None = None,
    ):
        """Return the open cascade's summary counts and, with view=full, paginated detail.

        Args:
            plan: Plan UUID or unique plan name.
            view: "summary" (default) for compact counts only, or "full"
                for counts plus the paginated/filtered "entries" list.
            limit: Maximum entries per page when view=full (default 50, max 200).
            offset: Entries to skip before the returned page when view=full.
            category: Restrict entries to one of added/removed/changed/
                needs_review/gate_finding.
            check_id: Restrict gate_finding entries to one mechanical-gate check_id.
            entity_type: Restrict entries to one resolved entity_type.
            step: Restrict entries to one step UUID (entity_uuid equality).
            status: Restrict entries to one step_status value.
            context: Unused; present for command-protocol uniformity.

        Returns:
            A SuccessResult wrapping {cascade_uuid, base_revision_uuid,
            tip_revision_uuid, gate_green, summary} (view=summary, the
            default), plus {entries, total, limit, offset,
            gate_report_json} when view=full; an ErrorResult with code
            CASCADE_REQUIRED when the plan has no open cascade; or an
            ErrorResult produced by map_exception on other failures.
        """
        try:
            view_value = parse_view(view, default=VIEW_SUMMARY)
            category_value = parse_category(category)
            raw_params = {"entity_type": entity_type, "step": step, "status": status, "limit": limit, "offset": offset}
            filters = parse_filters(raw_params, _GENERIC_DETAIL_FILTER_FIELDS)
            pagination = parse_pagination(raw_params)
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                if get_open_cascade(conn, p.uuid) is None:
                    return domain_error(
                        "CASCADE_REQUIRED",
                        f"plan {p.name} has no open cascade",
                    )
                data = preview_cascade(conn, p.uuid)
                response = {
                    "cascade_uuid": data["cascade_uuid"],
                    "base_revision_uuid": data["base_revision_uuid"],
                    "tip_revision_uuid": data["tip_revision_uuid"],
                    "gate_green": data["gate_green"],
                    "summary": summarize(data["entries"]),
                }
                if view_value == "full":
                    matched = filter_entries(
                        data["entries"],
                        category=category_value,
                        entity_type=filters.get("entity_type"),
                        step=filters.get("step"),
                        status=filters.get("status"),
                        check_id=check_id,
                    )
                    response["entries"] = matched[pagination.offset : pagination.offset + pagination.limit]
                    response["total"] = len(matched)
                    response["limit"] = pagination.limit
                    response["offset"] = pagination.offset
                    response["gate_report_json"] = data["gate_report_json"]
                return SuccessResult(data=response)
        except Exception as exc:
            return map_exception(exc)

#!/usr/bin/env python3
"""One-shot maintenance script for legacy fields.objects normalization."""

from __future__ import annotations

import argparse
import json
import sys
import uuid

from plan_manager.cascade.record import get_open_cascade
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.main import build_app
from plan_manager.maintenance.step_objects_normalize import (
    persist_step_object_rewrites,
    plan_step_object_rewrites,
)
from plan_manager.runtime.context import db_connection, init_runtime
from plan_manager.storage.version_store import get_ref
from plan_manager.views.dependency_graph import load_steps
from plan_manager.commands.step_ref import canonical_step_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Normalize legacy level-5 fields.objects bare-string declarations."
    )
    parser.add_argument("--config", required=True, help="Path to the plan_manager JSON config file.")
    parser.add_argument("--plan", required=True, help="Plan identifier (UUID or name).")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the normalization and record one revision. Without this flag, the script is dry-run only.",
    )
    parser.add_argument(
        "--cascade-uuid",
        help="Optional open cascade UUID to record the normalization under instead of advancing head directly.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    init_runtime(args.config)
    with db_connection() as conn:
        plan = resolve_plan(conn, args.plan)
        open_cascade = get_open_cascade(conn, plan.uuid)
        if args.cascade_uuid is None:
            if open_cascade is not None:
                raise SystemExit(
                    json.dumps(
                        {
                            "success": False,
                            "error": "plan has an open cascade; pass --cascade-uuid",
                            "cascade_uuid": str(open_cascade.uuid),
                        }
                    )
                )
            ref_name = None
            parent_revision_uuid = plan.head_revision_uuid
            current_revision = str(plan.head_revision_uuid) if plan.head_revision_uuid else None
        else:
            if open_cascade is None or str(open_cascade.uuid) != args.cascade_uuid:
                raise SystemExit(
                    json.dumps(
                        {
                            "success": False,
                            "error": "cascade id does not match the open cascade",
                            "cascade_uuid": args.cascade_uuid,
                        }
                    )
                )
            ref_name = open_cascade.name
            parent_revision_uuid = get_ref(conn, plan.uuid, open_cascade.name)
            current_revision = str(parent_revision_uuid)

        nodes = load_steps(conn, plan.uuid)
        rewrites, invalid_steps = plan_step_object_rewrites(
            nodes,
            lambda step: canonical_step_path(nodes, step),
        )
        if invalid_steps:
            print(
                json.dumps(
                    {
                        "success": False,
                        "error": "one or more atomic steps have non-convertible object declarations",
                        "invalid_steps": invalid_steps,
                        "convertible_steps": [rewrite.path for rewrite in rewrites],
                    },
                    indent=2,
                )
            )
            return 1
        revision_uuid = current_revision
        applied = False
        if args.apply and rewrites:
            new_revision = persist_step_object_rewrites(
                conn,
                plan.uuid,
                rewrites,
                parent_revision_uuid=parent_revision_uuid,
                ref_name=ref_name,
                author="script",
                message=f"step_objects_normalize: {len(rewrites)} step(s)",
            )
            revision_uuid = str(new_revision) if new_revision is not None else current_revision
            applied = new_revision is not None
        print(
            json.dumps(
                {
                    "success": True,
                    "applied": applied,
                    "dry_run": not args.apply,
                    "converted_count": len(rewrites),
                    "converted_steps": [rewrite.path for rewrite in rewrites],
                    "revision_uuid": revision_uuid,
                },
                indent=2,
            )
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

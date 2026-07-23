"""Command: create a semantic tree snapshot (SRT), the sole write operation of the SRT command surface."""

from __future__ import annotations

import dataclasses
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.commands.srt_command_metadata import BASE_PARAMETERS, srt_metadata
from plan_manager.runtime.context import app_config, db_connection
from plan_manager.scoring.reproduction_input import (
    assemble_reproduction_input,
    warm_embedding_cache,
)
from plan_manager.scoring.reproduction_tree import build_tree
from plan_manager.storage.srt_snapshot_store import insert_srt_snapshot
from plan_manager.views.context_blocks import resolve_context_revision


class SrtSnapshotCreateCommand(Command):
    name: ClassVar[str] = "srt_snapshot_create"
    version: ClassVar[str] = "1.1.0"
    descr: ClassVar[str] = (
        "Create a semantic tree snapshot: the sole write operation of the SRT "
        "command surface. Snapshots the committed head revision by default; "
        "pass cascade_uuid to snapshot an open cascade's working tip instead."
    )
    category: ClassVar[str] = "srt"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = True

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan": {"type": "string", "description": "Plan identifier."},
                "algorithm_version": {"type": "string", "description": "Version identifier of the SRT computation algorithm."},
                "summarizer_version": {"type": "string", "description": "Version identifier of the summarizer used."},
                "embedding_model": {"type": "string", "description": "Identifier of the embedding model used."},
                "revision": {"type": "string", "description": "Optional current head revision UUID; mutually exclusive with cascade_uuid. Only the plan's actual current head is accepted (historical reconstruction is not available); omit both for the same committed-head behavior."},
                "cascade_uuid": {"type": "string", "description": "Optional open cascade UUID; mutually exclusive with revision. When supplied, the snapshot is recorded against that cascade's current working-tip revision instead of the committed head, and must be the plan's actual open cascade."},
            },
            "required": ["plan", "algorithm_version", "summarizer_version", "embedding_model"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "algorithm_version": {"description": "Version identifier of the SRT computation algorithm.", "type": "string", "required": True},
            "summarizer_version": {"description": "Version identifier of the summarizer used.", "type": "string", "required": True},
            "embedding_model": {"description": "Identifier of the embedding model used.", "type": "string", "required": True},
            "revision": {"description": "Optional current head revision UUID; mutually exclusive with cascade_uuid. Only the plan's actual current head is accepted (historical reconstruction is not available); omit both for the same committed-head behavior.", "type": "string", "required": False},
            "cascade_uuid": {"description": "Optional open cascade UUID; mutually exclusive with revision. When supplied, the snapshot is recorded against that cascade's current working-tip revision instead of the committed head, and must be the plan's actual open cascade.", "type": "string", "required": False},
        }
        return srt_metadata(
            cls,
            params,
            {
                "success": {
                    "description": (
                        "The persisted SemanticTreeSnapshot payload (revision_uuid "
                        "and tree_hash are the ACTUAL revision/hash used), "
                        "deduplicated by content hash, plus 'cascade_uuid' (the "
                        "open cascade the snapshot was taken against, or null for "
                        "committed-head mode) and 'snapshot_mode' ('cascade_tip' "
                        "or 'committed_head')."
                    )
                }
            },
            [
                {
                    "description": "Compute and snapshot the tree for the current committed head revision (default).",
                    "command": {
                        "plan": "plan_manager",
                        "algorithm_version": "1.0.0",
                        "summarizer_version": "1.0.0",
                        "embedding_model": "text-embedding-3-small",
                    },
                },
                {
                    "description": "Snapshot the open cascade's current working tip instead of the committed head.",
                    "command": {
                        "plan": "plan_manager",
                        "algorithm_version": "1.0.0",
                        "summarizer_version": "1.0.0",
                        "embedding_model": "text-embedding-3-small",
                        "cascade_uuid": "6f1c2e2a-1111-4a2b-9c3d-4e5f6a7b8c9d",
                    },
                },
            ],
            error_cases={
                "CASCADE_CONFLICT": {
                    "description": "Both revision and cascade_uuid were supplied, or cascade_uuid does not name the plan's actual open cascade.",
                    "message": "revision and cascade_uuid are mutually exclusive",
                    "solution": "Supply at most one of revision/cascade_uuid, and only the plan's currently open cascade_uuid.",
                },
                "REVISION_NOT_FOUND": {
                    "description": "The supplied revision is not the plan's current head (historical reconstruction is not available).",
                    "message": "revision not available for live context compilation: {revision}",
                    "solution": "Omit revision for the current head, or supply cascade_uuid for the open cascade's working tip.",
                },
            },
            extra_best_practices=[
                "Omit both revision and cascade_uuid for the explicit committed-head mode (unchanged default behavior).",
                "Pass cascade_uuid (not revision) to snapshot an open cascade's working-tip state; the recorded revision_uuid/tree_hash reflect that tip, never a silent substitution of the committed head.",
            ],
        )

    async def execute(
        self,
        plan: str,
        algorithm_version: str,
        summarizer_version: str,
        embedding_model: str,
        revision: str | None = None,
        cascade_uuid: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                context_revision = resolve_context_revision(conn, p, revision=revision, cascade_uuid=cascade_uuid)
                cfg = app_config()
                root, embed_fn = assemble_reproduction_input(
                    conn, p.uuid, cfg.embedding_url, timeout=cfg.embedding_timeout
                )
                # Warm the pgvector cache for every node chunk in one batched
                # pre-pass so build_tree's per-text embeds become cache hits
                # instead of ~108 sequential one-text embed jobs.
                warm_embedding_cache(
                    conn, root, cfg.embedding_url, timeout=cfg.embedding_timeout
                )
                tree = build_tree(root, cfg.embedding_url, embed_fn)
                tree_content = dataclasses.asdict(tree)
                record = insert_srt_snapshot(
                    conn,
                    p.uuid,
                    context_revision.revision_uuid,
                    algorithm_version,
                    summarizer_version,
                    embedding_model,
                    tree_content,
                )
                payload = record.to_payload()
                payload["cascade_uuid"] = str(context_revision.cascade_uuid) if context_revision.cascade_uuid else None
                payload["snapshot_mode"] = "cascade_tip" if context_revision.cascade_uuid else "committed_head"
                return SuccessResult(data=payload)
        except Exception as exc:
            return map_exception(exc)

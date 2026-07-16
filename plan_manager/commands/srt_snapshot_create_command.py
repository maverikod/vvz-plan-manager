"""Command: create a semantic tree snapshot (SRT), the sole write operation of the SRT command surface."""

from __future__ import annotations

import dataclasses
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.srt_command_metadata import BASE_PARAMETERS, srt_metadata
from plan_manager.runtime.context import app_config, db_connection
from plan_manager.scoring.reproduction_input import (
    assemble_reproduction_input,
    warm_embedding_cache,
)
from plan_manager.scoring.reproduction_tree import build_tree
from plan_manager.storage.srt_snapshot_store import insert_srt_snapshot


class SrtSnapshotCreateCommand(Command):
    name: ClassVar[str] = "srt_snapshot_create"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Create a semantic tree snapshot: the sole write operation of the SRT command surface."
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
        }
        return srt_metadata(
            cls,
            params,
            {"success": {"description": "The persisted SemanticTreeSnapshot payload, deduplicated by content hash."}},
            [{
                "description": "Compute and snapshot the tree for the current head revision.",
                "command": {
                    "plan": "plan_manager",
                    "algorithm_version": "1.0.0",
                    "summarizer_version": "1.0.0",
                    "embedding_model": "text-embedding-3-small",
                },
            }],
        )

    async def execute(
        self,
        plan: str,
        algorithm_version: str,
        summarizer_version: str,
        embedding_model: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
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
                    p.head_revision_uuid,
                    algorithm_version,
                    summarizer_version,
                    embedding_model,
                    tree_content,
                )
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)

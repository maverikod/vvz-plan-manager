"""ExportReadCommand: serve export-file bytes in bounded base64 chunks (bug f58e7302).

plan_manager owns the files it writes under the configured export root, so it also serves their
bytes back over JSON-RPC rather than coupling clients to a private adapter transfer session store.
A file is addressed strictly under ``<export_root>/<plan>/`` and returned as base64 chunks bounded
by ``limit`` (decoded-byte cap 262144), together with the whole file's size and sha256 so a client
can reassemble and verify byte-identity without any polling.
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.export_read_metadata import get_export_read_metadata
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import app_config, db_connection


# Maximum number of DECODED bytes a single chunk may carry ({tk6y} security contract).
_MAX_CHUNK_BYTES: int = 262144


def _resolve_export_file(export_root: str, plan_name: str, file: str) -> Path | None:
    """Safely resolve ``<export_root>/<plan_name>/<file>`` for reading.

    Defense-in-depth path resolver mirroring plan_delete's _remove_export_layout: the plan name
    must be a single safe path segment, the file must be a non-empty relative path, and the fully
    resolved candidate (symlinks followed) must stay strictly inside the resolved plan export
    directory. Any attempt to escape the plan directory returns None.

    Args:
        export_root: Configured export root directory (as configured; not necessarily resolved).
        plan_name: The owning plan's catalog name; must be a single path segment.
        file: Plan-relative file path to read (may contain subdirectories).

    Returns:
        The resolved Path when it is safely inside ``<export_root>/<plan_name>/``; otherwise None.
    """
    if not plan_name or plan_name in (".", ".."):
        return None
    if "/" in plan_name or os.sep in plan_name or "\\" in plan_name:
        return None
    if os.altsep and os.altsep in plan_name:
        return None
    if not file or not isinstance(file, str):
        return None

    root = Path(export_root).resolve()
    plan_root = (Path(export_root) / plan_name).resolve()
    if plan_root.parent != root:
        return None

    candidate = (plan_root / file).resolve()
    if candidate != plan_root and plan_root not in candidate.parents:
        return None
    return candidate


def _sha256_file(path: Path) -> str:
    """Return the hex sha256 of the whole file, read in bounded blocks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class ExportReadCommand(Command):
    """Read a bounded base64 chunk of an export file under the plan's export root, read-only."""

    name: ClassVar[str] = "export_read"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Read a byte range of a file under <export_root>/<plan>/ as a base64 chunk, with the "
        "whole file's size and sha256 for byte-identical reassembly and verification."
    )
    category: ClassVar[str] = "exchange"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan identifier (UUID or catalog name) whose export directory owns the file.",
                },
                "file": {
                    "type": "string",
                    "description": (
                        "Plan-relative path of the file to read under <export_root>/<plan>/. "
                        "May contain subdirectories but must resolve strictly inside the plan "
                        "export directory; paths escaping it are refused."
                    ),
                },
                "offset": {
                    "type": "integer",
                    "description": "Zero-based byte offset to start reading from. Must be in [0, total_size].",
                    "minimum": 0,
                    "default": 0,
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        "Maximum number of decoded bytes to return in this chunk. Must be in "
                        "[1, 262144]."
                    ),
                    "minimum": 1,
                    "maximum": _MAX_CHUNK_BYTES,
                    "default": _MAX_CHUNK_BYTES,
                },
            },
            "required": ["plan", "file"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return get_export_read_metadata(cls)

    async def execute(
        self,
        plan: str,
        file: str,
        offset: int = 0,
        limit: int = _MAX_CHUNK_BYTES,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
                return domain_error(
                    "INVALID_PAGINATION", "offset must be an integer >= 0", {"offset": offset}
                )
            if (
                not isinstance(limit, int)
                or isinstance(limit, bool)
                or limit < 1
                or limit > _MAX_CHUNK_BYTES
            ):
                return domain_error(
                    "INVALID_PAGINATION",
                    f"limit must be an integer in [1, {_MAX_CHUNK_BYTES}]",
                    {"limit": limit, "max_chunk_bytes": _MAX_CHUNK_BYTES},
                )

            with db_connection() as conn:
                p = resolve_plan(conn, plan)

            path = _resolve_export_file(app_config().export_root, p.name, file)
            if path is None:
                return domain_error(
                    "EXPORT_PATH_INVALID",
                    "file does not resolve to a path inside the plan export directory",
                    {"file": file},
                )
            if not path.is_file():
                return domain_error(
                    "EXPORT_FILE_NOT_FOUND",
                    "no export file at the requested path",
                    {"file": file},
                )

            total_size = path.stat().st_size
            sha256 = _sha256_file(path)
            if offset > total_size:
                return domain_error(
                    "INVALID_PAGINATION",
                    "offset is past the end of the file",
                    {"offset": offset, "total_size": total_size},
                )

            with path.open("rb") as handle:
                handle.seek(offset)
                chunk = handle.read(limit)

            return SuccessResult(
                data={
                    "plan": p.name,
                    "file": file,
                    "offset": offset,
                    "limit": limit,
                    "chunk_base64": base64.b64encode(chunk).decode("ascii"),
                    "chunk_size": len(chunk),
                    "total_size": total_size,
                    "sha256": sha256,
                    "eof": offset + len(chunk) >= total_size,
                }
            )
        except Exception as exc:
            return map_exception(exc)

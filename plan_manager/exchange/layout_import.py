"""Filesystem helpers for validating and ingesting a standard-layout plan export tree."""

import re
from pathlib import Path

import yaml

from plan_manager.cascade.write import step_snapshot
from plan_manager.domain.step import validate_ts_inputs_outputs
from plan_manager.domain.step_store import create_step

_DIR_PATTERN = re.compile(r"^([GT])-(\d{3})-[a-z0-9-]+$")
_AS_FILENAME_PATTERN = re.compile(r"^(A-\d{3})-[a-z0-9-]+\.yaml$")


def validate_descriptor_dir(dir_path: Path, expected_prefix: str) -> list[str]:
    """Validate one G-* or T-* step directory name and its README.yaml descriptor."""
    match = _DIR_PATTERN.match(dir_path.name)
    if match is None or match.group(1) != expected_prefix:
        return [f"invalid directory name: {dir_path}"]

    declared_id = f"{match.group(1)}-{match.group(2)}"
    readme_path = dir_path / "README.yaml"
    if not readme_path.is_file():
        return [f"missing README.yaml: {readme_path}"]

    try:
        data = yaml.safe_load(readme_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [f"{readme_path}: invalid YAML: {exc}"]

    if not isinstance(data, dict) or "step_id" not in data:
        return [f"{readme_path}: missing step_id"]
    if data["step_id"] != declared_id:
        return [
            f"{readme_path}: step_id {data['step_id']!r} does not match directory {declared_id!r}"
        ]
    issues: list[str] = []
    if expected_prefix == "T":
        # Bug 26fa21a5: catch a malformed nested inputs/outputs item shape
        # during the pre-flight (dry-run-safe) layout validation pass, before
        # import_steps ever reaches the write boundary in
        # _create_step_from_descriptor below.
        for problem in validate_ts_inputs_outputs(data):
            issues.append(f"{readme_path}: {problem['message']}")
    return issues


def validate_as_file(as_path: Path) -> list[str]:
    """Validate one atomic-step descriptor file name and content."""
    match = _AS_FILENAME_PATTERN.match(as_path.name)
    if match is None:
        return [f"invalid atomic step filename: {as_path}"]

    declared_id = match.group(1)
    try:
        data = yaml.safe_load(as_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [f"{as_path}: invalid YAML: {exc}"]

    if not isinstance(data, dict) or "step_id" not in data:
        return [f"{as_path}: missing step_id"]
    if data["step_id"] != declared_id:
        return [
            f"{as_path}: step_id {data['step_id']!r} does not match filename {declared_id!r}"
        ]
    return []


def _create_step_from_descriptor(conn, plan_uuid, descriptor_path: Path, name: str, level: int, parent_step_uuid):
    """Create one Step (C-005) from a parsed descriptor and verify its assigned identifier."""
    data = yaml.safe_load(descriptor_path.read_text(encoding="utf-8"))
    declared_id = data["step_id"]
    slug = name[len(declared_id) + 1 :]
    fields = {
        k: v
        for k, v in data.items()
        if k not in {"step_id", "depends_on", "concepts", "project_id", "status"}
    }
    if level == 4:
        # Bug 26fa21a5: last-resort defense at the actual write boundary --
        # validate_descriptor_dir above already screens this during
        # validate_layout, but a caller that invokes import_steps directly
        # must still get atomic rejection (the surrounding db_connection()
        # transaction rolls back on this exception, so nothing partial is
        # persisted).
        problems = validate_ts_inputs_outputs(fields)
        if problems:
            raise ValueError(
                f"{descriptor_path}: invalid TS inputs/outputs item shape: "
                + "; ".join(problem["message"] for problem in problems)
            )
    step = create_step(
        conn,
        plan_uuid,
        parent_step_uuid,
        level,
        slug,
        fields,
        data.get("depends_on", []),
        data.get("concepts", []),
        data.get("project_id"),
    )
    if step.step_id != declared_id:
        raise ValueError(
            f"identifier mismatch on import: expected {declared_id} got {step.step_id}"
        )
    return step


def import_steps(conn, plan_uuid, root: Path) -> list[tuple]:
    """Walk a validated standard-layout tree and create every step it declares."""
    changes: list[tuple] = []
    gs_dirs = sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith("G-"))
    for gs_dir in gs_dirs:
        gs_step = _create_step_from_descriptor(
            conn, plan_uuid, gs_dir / "README.yaml", gs_dir.name, 3, None
        )
        changes.append((gs_step.uuid, step_snapshot(gs_step, gs_step.status)))

        ts_dirs = sorted(p for p in gs_dir.iterdir() if p.is_dir() and p.name.startswith("T-"))
        for ts_dir in ts_dirs:
            ts_step = _create_step_from_descriptor(
                conn, plan_uuid, ts_dir / "README.yaml", ts_dir.name, 4, gs_step.uuid
            )
            changes.append((ts_step.uuid, step_snapshot(ts_step, ts_step.status)))

            as_dir = ts_dir / "atomic_steps"
            if as_dir.is_dir():
                as_files = sorted(as_dir.glob("*.yaml"))
                for as_file in as_files:
                    as_step = _create_step_from_descriptor(
                        conn, plan_uuid, as_file, as_file.stem, 5, ts_step.uuid
                    )
                    changes.append((as_step.uuid, step_snapshot(as_step, as_step.status)))
    return changes

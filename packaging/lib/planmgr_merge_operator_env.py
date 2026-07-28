"""Restore operator env values after a dangerous planmgr conffile overwrite."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

KEY_RE = re.compile(r"^([A-Z0-9_]+)=(.*)$")

# Keep the freshly installed package version even when restoring the rest of
# the operator-managed environment from a saved dpkg-old file.
KEEP_CURRENT_KEYS = frozenset({"PLANMGR_IMAGE_VERSION"})

# Trigger only on the dangerous overwrite pattern observed on Sunday, July 26,
# 2026: the freshly installed conffile disables proxy registration and blanks
# the advertised host and registration URL, while the dpkg-old backup still
# holds the live operator values.
CURRENT_DANGEROUS_DEFAULTS = {
    "PLANMGR_REGISTRATION_ENABLED": "false",
    "PLANMGR_ADVERTISED_HOST": "",
    "PLANMGR_REGISTRATION_URL": "",
}

PREVIOUS_OPERATOR_SIGNAL_KEYS = (
    "PLANMGR_REGISTRATION_ENABLED",
    "PLANMGR_ADVERTISED_HOST",
    "PLANMGR_REGISTRATION_URL",
    "PLANMGR_PORT",
    "PLANMGR_EMBEDDING_URL",
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_env(text: str) -> dict[str, str]:
    """Parse shell-style KEY=value lines from an EnvironmentFile."""

    values: dict[str, str] = {}
    for line in text.splitlines():
        match = KEY_RE.match(line.strip())
        if not match:
            continue
        key, value = match.groups()
        values[key] = value
    return values


def should_restore_operator_env(current: dict[str, str], previous: dict[str, str]) -> bool:
    """Return True when the current file matches the dangerous overwrite pattern."""

    if not previous:
        return False
    if any(current.get(key, "") != expected for key, expected in CURRENT_DANGEROUS_DEFAULTS.items()):
        return False
    if previous.get("PLANMGR_REGISTRATION_ENABLED", "").lower() == "true":
        return True
    return any(previous.get(key, "") not in ("", current.get(key, "")) for key in PREVIOUS_OPERATOR_SIGNAL_KEYS)


def merge_operator_env_text(current_text: str, previous_text: str) -> str:
    """Restore operator values into the current env file when restoration is needed."""

    current = parse_env(current_text)
    previous = parse_env(previous_text)
    if not should_restore_operator_env(current, previous):
        return current_text

    merged_lines: list[str] = []
    for line in current_text.splitlines():
        match = KEY_RE.match(line)
        if not match:
            merged_lines.append(line)
            continue
        key, _value = match.groups()
        if key in KEEP_CURRENT_KEYS or key not in previous:
            merged_lines.append(line)
            continue
        merged_lines.append(f"{key}={previous[key]}")
    suffix = "\n" if current_text.endswith("\n") else ""
    return "\n".join(merged_lines) + suffix


def merge_operator_env_file(current_path: Path, previous_path: Path) -> bool:
    """Rewrite the current file in place when restoration is required."""

    current_text = _read_text(current_path)
    previous_text = _read_text(previous_path)
    merged_text = merge_operator_env_text(current_text, previous_text)
    if merged_text == current_text:
        return False

    stat_result = current_path.stat()
    tmp_path = current_path.with_suffix(current_path.suffix + ".tmp")
    tmp_path.write_text(merged_text, encoding="utf-8")
    os.chmod(tmp_path, stat_result.st_mode)
    os.replace(tmp_path, current_path)
    return True


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", required=True, help="Current /etc/default/planmgr path")
    parser.add_argument("--previous", required=True, help="Previous dpkg-old environment file path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    changed = merge_operator_env_file(Path(args.current), Path(args.previous))
    if changed:
        print("planmgr: restored operator environment values from dpkg-old backup")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

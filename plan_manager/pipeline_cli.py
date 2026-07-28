"""Single verification entrypoint for the project contract: ``pipeline``."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence

from plan_manager.pipeline_checks.registry import CHECKS, default_checks, get_check, repo_root


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(prog="pipeline")
    parser.add_argument("check", nargs="?", help="Run only this named check.")
    parser.add_argument("--list", action="store_true", help="List available named checks and exit.")
    parser.add_argument("--base-url", help="Base URL for the optional live-smoke check.")
    parser.add_argument("--expect-version", help="Expected server version for the optional live-smoke check.")
    parser.add_argument("--cert", help="Client certificate path for the optional live-smoke check.")
    parser.add_argument("--key", help="Client private key path for the optional live-smoke check.")
    parser.add_argument("--ca", help="CA bundle path for the optional live-smoke check.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Forward JSON output mode to the optional live-smoke check.",
    )
    return parser


def _live_smoke_argv(args: argparse.Namespace) -> tuple[str, ...] | None:
    """Build argv for the optional live-smoke check from CLI args, if requested."""
    if not args.base_url:
        return None
    argv: list[str] = [sys.executable, "scripts/live_smoke.py", "--base-url", args.base_url]
    if args.expect_version:
        argv.extend(["--expect-version", args.expect_version])
    if args.cert:
        argv.extend(["--cert", args.cert])
    if args.key:
        argv.extend(["--key", args.key])
    if args.ca:
        argv.extend(["--ca", args.ca])
    if args.json:
        argv.append("--json")
    return tuple(argv)


def _resolve_checks(args: argparse.Namespace) -> tuple[tuple[str, tuple[str, ...], str], ...]:
    """Resolve the requested check set into runnable subprocess argv triples."""
    if args.check:
        if args.check == "live-smoke":
            argv = _live_smoke_argv(args)
            if argv is None:
                raise SystemExit("pipeline live-smoke requires --base-url")
            return (("live-smoke", argv, "Run the live smoke pipeline against a deployed server."),)
        spec = get_check(args.check)
        return ((spec.name, spec.argv, spec.description),)

    resolved = [(spec.name, spec.argv, spec.description) for spec in default_checks()]
    live_smoke = _live_smoke_argv(args)
    if live_smoke is not None:
        resolved.append(("live-smoke", live_smoke, "Run the live smoke pipeline against a deployed server."))
    return tuple(resolved)


def _run_check(name: str, argv: Sequence[str]) -> int:
    """Run one named check and return its subprocess exit code."""
    root = repo_root()
    env = os.environ.copy()
    pythonpath_entries = [str(root), str(root / "client")]
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        pythonpath_entries.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
    print(f"[pipeline] {name}: {' '.join(argv)}", flush=True)
    completed = subprocess.run(tuple(argv), cwd=root, env=env)
    return int(completed.returncode)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.list:
        for spec in CHECKS:
            print(f"{spec.name}: {spec.description}")
        print("live-smoke: Run the live smoke pipeline against a deployed server (requires --base-url).")
        return 0

    resolved = _resolve_checks(args)
    for name, check_argv, _description in resolved:
        code = _run_check(name, check_argv)
        if code != 0:
            print(f"[pipeline] stopped on failed check: {name}", file=sys.stderr, flush=True)
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

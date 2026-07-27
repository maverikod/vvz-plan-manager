"""Contract tests for the project-wide ``pipeline`` CLI."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

from plan_manager import pipeline_cli
from plan_manager.pipeline_checks.registry import CHECKS


def test_pipeline_list_prints_registered_checks(capsys) -> None:
    code = pipeline_cli.main(["--list"])
    out = capsys.readouterr().out

    assert code == 0
    for spec in CHECKS:
        assert spec.name in out
    assert "live-smoke" in out


def test_pipeline_no_args_runs_every_registered_check(monkeypatch) -> None:
    seen: list[str] = []

    def _fake_run_check(name: str, argv) -> int:
        seen.append(name)
        return 0

    monkeypatch.setattr(pipeline_cli, "_run_check", _fake_run_check)

    code = pipeline_cli.main([])

    assert code == 0
    assert seen == [spec.name for spec in CHECKS]


def test_pipeline_stops_on_first_failed_check(monkeypatch, capsys) -> None:
    seen: list[str] = []

    def _fake_run_check(name: str, argv) -> int:
        seen.append(name)
        return 1 if name == CHECKS[1].name else 0

    monkeypatch.setattr(pipeline_cli, "_run_check", _fake_run_check)

    code = pipeline_cli.main([])
    err = capsys.readouterr().err

    assert code == 1
    assert seen == [CHECKS[0].name, CHECKS[1].name]
    assert CHECKS[1].name in err


def test_pipeline_live_smoke_requires_base_url() -> None:
    try:
        pipeline_cli.main(["live-smoke"])
    except SystemExit as exc:
        assert "requires --base-url" in str(exc)
    else:
        raise AssertionError("pipeline live-smoke without --base-url must stop")


def test_run_check_exports_repo_and_client_to_pythonpath(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_run(argv, *, cwd, env):
        captured["argv"] = tuple(argv)
        captured["cwd"] = cwd
        captured["env"] = env
        return subprocess.CompletedProcess(tuple(argv), 0)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    monkeypatch.setenv("PYTHONPATH", "/tmp/already-present")

    code = pipeline_cli._run_check("repo-tests", ("python", "-m", "pytest"))

    assert code == 0
    assert captured["cwd"] == pipeline_cli.repo_root()
    env = captured["env"]
    assert isinstance(env, dict)
    pythonpath = env["PYTHONPATH"].split(os.pathsep)
    root = str(Path(pipeline_cli.repo_root()))
    assert pythonpath[:2] == [root, str(Path(root) / "client")]
    assert pythonpath[-1] == "/tmp/already-present"

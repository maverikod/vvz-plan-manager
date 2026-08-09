"""Pipeline check for bug 0040585c using a real isolated Plan Manager server.

The check starts a disposable PostgreSQL container and a Plan Manager HTTP
server from the selected repository root, then runs live-smoke R43. R43
exercises the real ``step_transition(require_green=true)`` path on a
throwaway plan and verifies that the freeze gate reports the open cascade's
working tip rather than the base head.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any
import uuid


DEFAULT_IMAGE = "pgvector/pgvector:pg16"
PASSWORD = "planmgr-test-password"


def _run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, text=True, **kwargs)


def _check(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    completed = _run(argv, **kwargs)
    if completed.returncode != 0:
        detail = ""
        if completed.stdout:
            detail += f"\nstdout:\n{completed.stdout}"
        if completed.stderr:
            detail += f"\nstderr:\n{completed.stderr}"
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(argv)}{detail}")
    return completed


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_tcp(port: int, process: subprocess.Popen[str], timeout: float = 40.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server exited early with code {process.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"server did not listen on 127.0.0.1:{port} within {timeout}s")


def _postgres_port(container: str) -> int:
    completed = _check(["docker", "port", container, "5432/tcp"], capture_output=True)
    value = completed.stdout.strip().splitlines()[0]
    return int(value.rsplit(":", 1)[1])


def _start_postgres(image: str) -> str:
    name = f"planmgr-0040585c-{uuid.uuid4().hex[:12]}"
    _check(
        [
            "docker",
            "run",
            "--rm",
            "-d",
            "--name",
            name,
            "-e",
            "POSTGRES_USER=planmgr",
            "-e",
            f"POSTGRES_PASSWORD={PASSWORD}",
            "-e",
            "POSTGRES_DB=planmgr",
            "-p",
            "127.0.0.1::5432",
            image,
        ],
        capture_output=True,
    )
    for _ in range(60):
        ready = _run(
            ["docker", "exec", name, "psql", "-U", "planmgr", "-d", "planmgr", "-c", "SELECT 1"],
            capture_output=True,
        )
        if ready.returncode == 0:
            return name
        time.sleep(0.5)
    raise RuntimeError("postgres container did not become ready")


def _psql(container: str, sql: str) -> None:
    try:
        _check(
            ["docker", "exec", "-i", container, "psql", "-v", "ON_ERROR_STOP=1", "-U", "planmgr", "-d", "planmgr"],
            input=sql,
            capture_output=True,
        )
    except Exception as exc:
        logs = _run(["docker", "logs", container], capture_output=True)
        raise RuntimeError(f"{exc}\ncontainer logs:\n{logs.stdout}\n{logs.stderr}") from exc


def _apply_migrations(repo_root: Path, container: str) -> None:
    migrations_dir = repo_root / "plan_manager_db" / "migrations"
    _psql(
        container,
        "CREATE TABLE IF NOT EXISTS schema_migration "
        "(filename text PRIMARY KEY, applied_at timestamptz NOT NULL);\n",
    )
    for path in sorted(migrations_dir.glob("*.sql")):
        _psql(container, path.read_text(encoding="utf-8"))
        _psql(
            container,
            "INSERT INTO schema_migration (filename, applied_at) "
            f"VALUES ('{path.name}', now()) ON CONFLICT (filename) DO NOTHING;\n",
        )


def _write_config(root: Path, db_port: int, server_port: int) -> tuple[Path, Path]:
    export_root = root / "export"
    export_root.mkdir()
    secrets = root / "db_password"
    secrets.write_text(PASSWORD, encoding="utf-8")
    config = root / "config.json"
    config.write_text(
        json.dumps(
            {
                "server": {
                    "host": "127.0.0.1",
                    "port": server_port,
                    "protocol": "http",
                },
                "registration": {"enabled": False},
                "plan_manager": {
                    "database": {
                        "host": "127.0.0.1",
                        "port": db_port,
                        "dbname": "planmgr",
                        "user": "planmgr",
                    },
                    "embedding": {"url": None, "timeout": 1.0},
                    "code_analysis": {"url": None, "timeout": 1.0},
                    "export_root": str(export_root),
                },
            }
        ),
        encoding="utf-8",
    )
    return config, secrets


def _print_smoke_summary(stdout: str) -> None:
    payload_start = stdout.find("{")
    json_text = stdout[payload_start:] if payload_start != -1 else stdout
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError:
        print(stdout, end="")
        return
    counts = payload.get("counts")
    failed = payload.get("failed")
    exit_code = payload.get("exit_code")
    print(f"live_smoke_r43 counts={counts} failed={failed} exit_code={exit_code}")
    for item in payload.get("results", []):
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.startswith("R43_1ddea076_"):
            continue
        detail = item.get("detail")
        status = item.get("status")
        if detail:
            print(f"{status} {name}: {detail}")
        else:
            print(f"{status} {name}")


def run_check(repo_root: Path, smoke_root: Path, python: Path, image: str) -> int:
    temp_root = Path(tempfile.mkdtemp(prefix="planmgr-0040585c-"))
    container: str | None = None
    server: subprocess.Popen[str] | None = None
    try:
        container = _start_postgres(image)
        db_port = _postgres_port(container)
        _apply_migrations(repo_root, container)
        server_port = _free_port()
        config_path, secrets_path = _write_config(temp_root, db_port, server_port)
        env = os.environ.copy()
        env["PLANMGR_SECRETS"] = str(secrets_path)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(repo_root), str(repo_root / "client"), env.get("PYTHONPATH", "")]
        )
        server_log = (temp_root / "server.log").open("w", encoding="utf-8")
        server = subprocess.Popen(
            [str(python), "-m", "plan_manager.main", "--config", str(config_path)],
            cwd=repo_root,
            env=env,
            stdout=server_log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            _wait_tcp(server_port, server)
        except Exception:
            print((temp_root / "server.log").read_text(encoding="utf-8"), file=sys.stderr)
            raise
        smoke = _run(
            [
                str(python),
                str(smoke_root / "scripts" / "live_smoke.py"),
                "--base-url",
                f"http://127.0.0.1:{server_port}",
                "--protocol-override",
                "http",
                "--test",
                "r43",
                "--json",
            ],
            cwd=smoke_root,
            env=env,
            capture_output=True,
        )
        _print_smoke_summary(smoke.stdout)
        if smoke.stderr:
            print(smoke.stderr, file=sys.stderr, end="")
        return int(smoke.returncode)
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)
        if container is not None:
            _run(["docker", "rm", "-f", container], capture_output=True)
        shutil.rmtree(temp_root, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--smoke-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--postgres-image", default=DEFAULT_IMAGE)
    args = parser.parse_args(argv)
    return run_check(
        Path(args.repo_root).resolve(),
        Path(args.smoke_root).resolve(),
        Path(args.python),
        args.postgres_image,
    )


if __name__ == "__main__":
    raise SystemExit(main())

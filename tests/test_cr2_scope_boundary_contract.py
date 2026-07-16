from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CLIENT_ROOT = _REPO_ROOT / "client"


def _python_files(*roots: Path) -> list[Path]:
    """Every .py file under the given roots, skipping caches and virtualenvs."""
    skip = {"__pycache__", ".venv", "venv", "build", "dist", ".git"}
    files: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        files.extend(
            p
            for p in root.rglob("*.py")
            if not skip.intersection(p.parts)
        )
    return files


def test_client_library_does_not_route_through_the_proxy() -> None:
    """The client's connections are direct to their server by design."""
    client_files = _python_files(_CLIENT_ROOT)

    # Sanity check: ensure the client package has shipped.
    assert (
        client_files
    ), "Client package has not shipped yet (no .py files found under client/)"

    offenders = []
    for file_path in client_files:
        content = file_path.read_text(encoding="utf-8")
        if "call_server(" in content:
            offenders.append(file_path)

    assert (
        not offenders
    ), f"Client library files must not use call_server(); found in: {offenders}"


def test_no_scheduler_or_batch_delivery_machinery() -> None:
    """CR-2 ships no batch or scheduled deliveries."""
    server_files = _python_files(_REPO_ROOT / "plan_manager")
    client_files = _python_files(_CLIENT_ROOT)
    all_files = server_files + client_files

    forbidden_imports = [
        "import apscheduler",
        "from apscheduler",
        "import croniter",
        "from croniter",
        "import celery",
        "from celery",
    ]

    offenders = []
    for file_path in all_files:
        content = file_path.read_text(encoding="utf-8")
        for forbidden in forbidden_imports:
            if forbidden in content:
                offenders.append((file_path, forbidden))

    assert (
        not offenders
    ), f"No scheduler/batch machinery allowed; found: {offenders}"


def test_no_server_to_server_push_to_code_analysis() -> None:
    """plan_manager never pushes to the code-analysis service."""
    server_files = _python_files(_REPO_ROOT / "plan_manager")

    push_methods = ["requests.post", "httpx.post", "aiohttp"]

    offenders = []
    for file_path in server_files:
        content = file_path.read_text(encoding="utf-8")
        has_code_analysis = "code_analysis" in content
        has_push = any(method in content for method in push_methods)

        if has_code_analysis and has_push:
            offenders.append(file_path)

    assert (
        not offenders
    ), (
        f"Server must not push to code-analysis service; "
        f"found files with both code_analysis and push methods: {offenders}"
    )


def test_no_subprocess_git_on_the_server_side() -> None:
    """The code-analysis client's git functionality is never reimplemented on server."""
    command_files = _python_files(_REPO_ROOT / "plan_manager" / "commands")

    offenders = []
    for file_path in command_files:
        content = file_path.read_text(encoding="utf-8")
        has_subprocess = "subprocess" in content
        has_git = "git" in content.lower()

        if has_subprocess and has_git:
            offenders.append(file_path)

    assert (
        not offenders
    ), (
        f"Server commands must not shell out to git; "
        f"found files with both subprocess and git: {offenders}"
    )


def test_server_side_additions_are_exactly_the_two_declared_commands() -> None:
    """The change request adds exactly two server commands.

    This is a heuristic guard on the declared boundary, not a full inventory diff:
    it checks for the declared exports and blocks common delivery-shaped patterns.
    """
    # Assert the two declared commands exist.
    export_archive = _REPO_ROOT / "plan_manager" / "commands" / "export_archive_command.py"
    export_cleanup = _REPO_ROOT / "plan_manager" / "commands" / "export_cleanup_command.py"

    assert export_archive.exists(), f"Expected {export_archive} to exist"
    assert export_cleanup.exists(), f"Expected {export_cleanup} to exist"

    # Assert no other delivery-shaped commands have appeared.
    command_files = list(
        (_REPO_ROOT / "plan_manager" / "commands").glob("*_command.py")
    )

    forbidden_substrings = ["push", "deliver", "schedule"]
    offenders = []

    for file_path in command_files:
        filename = file_path.name
        for forbidden in forbidden_substrings:
            if forbidden in filename:
                offenders.append(filename)
                break

    assert (
        not offenders
    ), f"No delivery-shaped commands allowed; found: {offenders}"

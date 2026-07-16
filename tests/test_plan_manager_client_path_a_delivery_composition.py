"""Composition tests for plan_manager client library's Path A (project-path) delivery.

Tests the delivery pipeline (archive → upload → commit) against stubs only:
no code-analysis service, no network, no plan_manager server.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import tarfile
from unittest.mock import AsyncMock

import pytest

from plan_manager_client.delivery.archive import (
    ArchiveEntryRefusedError,
    ArchiveIntegrityError,
    materialize_tree,
)
from plan_manager_client.delivery.atomicity import build_delivery_outcome
from plan_manager_client.delivery.commit import build_commit_message, stage_and_commit
from plan_manager_client.delivery.upload import (
    DigestMismatchError,
    PendingEntry,
    verify_and_upload_tree,
)


# --- Helpers for archive construction ----------------------------------------

_TREE: dict[str, bytes] = {
    "spec.yaml": b"concepts: []\n",
    "G-001-frame/README.yaml": b"step_id: G-001\n",
    "G-001-frame/T-001-decl/README.yaml": b"step_id: T-001\n",
}


def _build_archive(tree: dict[str, bytes]) -> tuple[bytes, str]:
    """Return (gzip-tar bytes, sha256 hex of those bytes) for the given tree."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for relative_path, content in tree.items():
            info = tarfile.TarInfo(name=relative_path)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    archive_bytes = buffer.getvalue()
    return archive_bytes, hashlib.sha256(archive_bytes).hexdigest()


def _build_archive_with_trailing_member(
    tree: dict[str, bytes],
    member: tarfile.TarInfo,
    content: bytes | None = None,
) -> tuple[bytes, str]:
    """Return (gzip-tar bytes, sha256) for tree followed by member as the LAST entry.

    Every member of tree is valid; member is appended last so that a refusal it
    triggers can only be caught by a validation pass that completes before any
    materialization begins.
    """
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for relative_path, entry_content in tree.items():
            info = tarfile.TarInfo(name=relative_path)
            info.size = len(entry_content)
            tar.addfile(info, io.BytesIO(entry_content))
        if content is None:
            tar.addfile(member)
        else:
            member.size = len(content)
            tar.addfile(member, io.BytesIO(content))
    archive_bytes = buffer.getvalue()
    return archive_bytes, hashlib.sha256(archive_bytes).hexdigest()


def _symlink_member(name: str, target: str) -> tarfile.TarInfo:
    """A tar member that is neither a regular file nor a directory."""
    info = tarfile.TarInfo(name=name)
    info.type = tarfile.SYMTYPE
    info.linkname = target
    info.size = 0
    return info


def _escaping_file_member(name: str = "../escape.yaml") -> tarfile.TarInfo:
    """A regular-file member whose stored path escapes the destination."""
    return tarfile.TarInfo(name=name)


def _make_ca_client() -> AsyncMock:
    """Build a fresh stub ca_client per test."""
    ca_client = AsyncMock()
    ca_client.file_sessions.upload_new = AsyncMock(return_value="new-1")
    ca_client.file_sessions.upload = AsyncMock(return_value="existing-1")
    ca_client.commands.git_add = AsyncMock(return_value=None)
    ca_client.commands.git_commit = AsyncMock(return_value={"commit_hash": "abc123"})
    return ca_client


# --- Tests: materialize_tree -------------------------------------------------


def test_materialize_tree_preserves_nested_relative_paths() -> None:
    """Nested relative paths are preserved; same bare name in different dirs do not collide."""
    archive_bytes, correct_sha = _build_archive(_TREE)
    entries = materialize_tree(archive_bytes, correct_sha)
    relative_paths = [e.relative_path for e in entries]

    assert relative_paths == list(_TREE)
    for entry in entries:
        assert entry.content == _TREE[entry.relative_path]
        assert entry.sha256 == hashlib.sha256(entry.content).hexdigest()

    # Explicitly verify the two same-named files are both present as distinct entries.
    assert "G-001-frame/README.yaml" in relative_paths
    assert "G-001-frame/T-001-decl/README.yaml" in relative_paths


def test_archive_digest_mismatch_aborts_before_unpacking() -> None:
    """Archive is verified before it is opened."""
    archive_bytes, _ = _build_archive(_TREE)
    with pytest.raises(ArchiveIntegrityError):
        materialize_tree(archive_bytes, "0" * 64)


def test_entry_escaping_the_destination_is_refused() -> None:
    """REFUSAL CLAUSE (ii): entry path contains '..' or starts with '/'."""
    archive_bytes, correct_sha = _build_archive_with_trailing_member(
        _TREE, _escaping_file_member("../escape.yaml"), b"x"
    )
    with pytest.raises(ArchiveEntryRefusedError):
        materialize_tree(archive_bytes, correct_sha)


def test_entry_that_is_neither_regular_file_nor_directory_is_refused() -> None:
    """REFUSAL CLAUSE (i): entry type is neither regular file nor directory.

    The member's stored path is deliberately benign (not escaping, not absolute),
    so only the not-a-regular-file-or-directory clause can refuse it.
    """
    archive_bytes, correct_sha = _build_archive_with_trailing_member(
        _TREE, _symlink_member("link.yaml", "spec.yaml")
    )
    with pytest.raises(ArchiveEntryRefusedError):
        materialize_tree(archive_bytes, correct_sha)


def test_refusal_on_the_last_member_materializes_nothing() -> None:
    """ALL-OR-NOTHING PROPERTY: refusal of any member (including last) returns nothing.

    An implementation that validated each member only before its own materialization
    would return a truncated list of earlier entries. An exhaustive validation pass
    that completes first yields nothing whatsoever.
    """
    # Test with trailing escaping-file member.
    archive_bytes_escaping, sha_escaping = _build_archive_with_trailing_member(
        _TREE, _escaping_file_member("../escape.yaml"), b"x"
    )
    with pytest.raises(ArchiveEntryRefusedError):
        materialize_tree(archive_bytes_escaping, sha_escaping)

    # Test with trailing symlink member.
    archive_bytes_symlink, sha_symlink = _build_archive_with_trailing_member(
        _TREE, _symlink_member("link.yaml", "spec.yaml")
    )
    with pytest.raises(ArchiveEntryRefusedError):
        materialize_tree(archive_bytes_symlink, sha_symlink)


# --- Tests: verify_and_upload_tree -------------------------------------------


def test_new_destination_path_uses_create_mode_upload() -> None:
    """Entry with already_indexed=False uses create mode (upload_new)."""
    ca_client = _make_ca_client()

    async def _run():
        entry = PendingEntry(
            relative_path="spec.yaml",
            destination_path="docs/export/spec.yaml",
            content=b"x",
            declared_digest=hashlib.sha256(b"x").hexdigest(),
            already_indexed=False,
        )
        results = await verify_and_upload_tree(ca_client, "proj-1", [entry])
        return results

    results = asyncio.run(_run())
    assert len(results) == 1
    assert results[0].mode == "create"
    assert results[0].ca_file_id == "new-1"
    ca_client.file_sessions.upload_new.assert_called_once_with(
        project_id="proj-1", file_path="docs/export/spec.yaml", content=b"x"
    )
    ca_client.file_sessions.upload.assert_not_called()


def test_known_destination_path_uses_update_mode_upload() -> None:
    """Entry with already_indexed=True uses update mode (upload)."""
    ca_client = _make_ca_client()

    async def _run():
        entry = PendingEntry(
            relative_path="spec.yaml",
            destination_path="docs/export/spec.yaml",
            content=b"x",
            declared_digest=hashlib.sha256(b"x").hexdigest(),
            already_indexed=True,
        )
        results = await verify_and_upload_tree(ca_client, "proj-1", [entry])
        return results

    results = asyncio.run(_run())
    assert len(results) == 1
    assert results[0].mode == "update"
    assert results[0].ca_file_id == "existing-1"
    ca_client.file_sessions.upload.assert_called_once_with(
        file_id="docs/export/spec.yaml", content=b"x"
    )
    ca_client.file_sessions.upload_new.assert_not_called()


def test_tree_is_preserved_under_the_destination_subdirectory() -> None:
    """Multiple entries preserve nested structure under destination subdirectory."""
    ca_client = _make_ca_client()

    async def _run():
        entries = [
            PendingEntry(
                relative_path=rel_path,
                destination_path=f"docs/export/{rel_path}",
                content=_TREE[rel_path],
                declared_digest=hashlib.sha256(_TREE[rel_path]).hexdigest(),
                already_indexed=False,
            )
            for rel_path in _TREE
        ]
        results = await verify_and_upload_tree(ca_client, "proj-1", entries)
        return results

    results = asyncio.run(_run())
    assert len(results) == 3

    # Verify the set of file_path arguments.
    file_paths_used = {
        call.kwargs["file_path"]
        for call in ca_client.file_sessions.upload_new.call_args_list
    }
    expected_paths = {
        "docs/export/spec.yaml",
        "docs/export/G-001-frame/README.yaml",
        "docs/export/G-001-frame/T-001-decl/README.yaml",
    }
    assert file_paths_used == expected_paths

    # Verify each result's relative_path matches its source.
    for result in results:
        assert result.relative_path in _TREE


def test_staging_and_commit_are_explicit_and_ordered() -> None:
    """Upload calls precede git_add, which precedes git_commit."""
    ca_client = _make_ca_client()

    async def _run():
        entries = [
            PendingEntry(
                relative_path=rel_path,
                destination_path=f"docs/export/{rel_path}",
                content=_TREE[rel_path],
                declared_digest=hashlib.sha256(_TREE[rel_path]).hexdigest(),
                already_indexed=False,
            )
            for rel_path in _TREE
        ]
        results = await verify_and_upload_tree(ca_client, "proj-1", entries)
        written_paths = [r.destination_path for r in results]

        receipt = await stage_and_commit(
            ca_client,
            "proj-1",
            written_paths,
            plan_name="demo-plan",
            export_revision_uuid="rev-1",
            per_entry_digest_set={
                p: hashlib.sha256(_TREE[p]).hexdigest() for p in _TREE
            },
        )
        return receipt

    receipt = asyncio.run(_run())

    # Verify git_add and git_commit were called exactly once.
    ca_client.commands.git_add.assert_called_once()
    ca_client.commands.git_commit.assert_called_once()

    # Verify order: all upload calls, then git_add, then git_commit.
    call_sequence = [call[0] for call in ca_client.mock_calls]
    upload_calls = [
        i for i, call in enumerate(call_sequence)
        if "upload_new" in str(call) or "upload" in str(call)
    ]
    git_add_index = next(
        i for i, call in enumerate(call_sequence) if "git_add" in str(call)
    )
    git_commit_index = next(
        i for i, call in enumerate(call_sequence) if "git_commit" in str(call)
    )

    assert all(idx < git_add_index for idx in upload_calls)
    assert git_add_index < git_commit_index

    # Verify commit hash.
    assert receipt.commit_hash == "abc123"


def test_commit_message_is_keyed_by_relative_path_and_sorted() -> None:
    """Commit message is sorted by relative path with deterministic format."""
    message = build_commit_message(
        "demo-plan",
        "rev-1",
        {p: hashlib.sha256(_TREE[p]).hexdigest() for p in _TREE},
    )

    lines = message.split("\n")
    assert lines[0] == "plan_manager export delivery: demo-plan (revision rev-1)"

    # Remaining lines should be sorted by relative path.
    remaining = lines[1:]
    expected_lines = [
        f"  {p}: sha256:{hashlib.sha256(_TREE[p]).hexdigest()}"
        for p in sorted(_TREE.keys())
    ]
    assert remaining == expected_lines

    # Verify both same-named files are distinct.
    assert "  G-001-frame/README.yaml: sha256:" in message
    assert "  G-001-frame/T-001-decl/README.yaml: sha256:" in message


# --- Tests: failure atomicity ------------------------------------------------


def test_failure_atomicity_report_names_partial_writes() -> None:
    """Digest mismatch on second entry aborts upload; partial write is recorded."""
    ca_client = _make_ca_client()

    async def _run():
        entries = [
            PendingEntry(
                relative_path="spec.yaml",
                destination_path="docs/export/spec.yaml",
                content=b"x",
                declared_digest=hashlib.sha256(b"x").hexdigest(),
                already_indexed=False,
            ),
            PendingEntry(
                relative_path="wrong.yaml",
                destination_path="docs/export/wrong.yaml",
                content=b"y",
                declared_digest="0" * 64,  # Deliberately wrong.
                already_indexed=False,
            ),
        ]
        with pytest.raises(DigestMismatchError):
            await verify_and_upload_tree(ca_client, "proj-1", entries)

    asyncio.run(_run())

    # First entry should have been uploaded; second should not.
    ca_client.file_sessions.upload_new.assert_called_once()
    assert ca_client.file_sessions.upload_new.call_count == 1

    # Build outcome: partial write with no commit.
    outcome = build_delivery_outcome(
        written_paths=["docs/export/spec.yaml"],
        commit_hash=None,
        failure_point="digest_verification",
    )
    assert outcome.written_paths == ["docs/export/spec.yaml"]
    assert outcome.commit_made is False
    assert outcome.failure_point == "digest_verification"


def test_archive_failure_points_are_representable() -> None:
    """Failure points for archive-level aborts are representable."""
    outcome_verify = build_delivery_outcome(
        [], None, failure_point="archive_verification"
    )
    assert outcome_verify.failure_point == "archive_verification"
    assert outcome_verify.written_paths == []
    assert outcome_verify.commit_made is False

    outcome_refused = build_delivery_outcome(
        [], None, failure_point="archive_entry_refused"
    )
    assert outcome_refused.failure_point == "archive_entry_refused"
    assert outcome_refused.written_paths == []
    assert outcome_refused.commit_made is False

    # Invalid failure point raises ValueError.
    with pytest.raises(ValueError):
        build_delivery_outcome([], None, failure_point="not_a_stage")

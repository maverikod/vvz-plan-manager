"""Tests for plan_manager client's Path B (no-project) export fetch chain:
request archive -> fetch bytes -> verify digest -> unpack tree.
Exercises the full integration against a stubbed JSON-RPC endpoint.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import tarfile
from pathlib import Path
from typing import Any

import pytest

from plan_manager_client.export_fetch_request import (
    ExportArchiveRef,
    request_export_archive,
)
from plan_manager_client.export_fetch_chunks import (
    ReassembledFile,
    fetch_export_file,
)
from plan_manager_client.export_fetch_verify import (
    ExportIntegrityError,
    VerifiedFile,
    verify_reassembled_file,
)
from plan_manager_client.export_fetch_unpack import (
    ExportUnpackError,
    unpack_verified_archive,
    build_retrieval_report,
)


# --- Helpers: build real archives in memory --------------------------------

_TREE: dict[str, bytes] = {
    "source_spec.md": b"# spec\n",
    "spec.yaml": b"concepts: []\n",
    "G-001-frame/README.yaml": b"step_id: G-001\n",
    "G-001-frame/T-001-decl/README.yaml": b"step_id: T-001\n",
    "G-001-frame/T-001-decl/atomic_steps/A-001-doc.yaml": b"step_id: A-001\n",
}


def _build_archive(tree: dict[str, bytes]) -> bytes:
    """Return gzip-tar bytes carrying every path of tree at its stored position."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for relative_path, content in tree.items():
            info = tarfile.TarInfo(name=relative_path)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def _build_archive_with_trailing_member(
    tree: dict[str, bytes],
    member: tarfile.TarInfo,
    content: bytes | None = None,
) -> bytes:
    """Return gzip-tar bytes for tree followed by member as the LAST entry.

    Every member of tree is valid; member is appended last, so a refusal it
    triggers can only leave nothing behind if validation completes before any
    write begins.
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
    return buffer.getvalue()


def _symlink_member(name: str, target: str) -> tarfile.TarInfo:
    """A tar member that is neither a regular file nor a directory."""
    info = tarfile.TarInfo(name=name)
    info.type = tarfile.SYMTYPE
    info.linkname = target
    info.size = 0
    return info


def _verified(archive_bytes: bytes) -> VerifiedFile:
    """Wrap raw archive bytes as an already-verified archive."""
    return VerifiedFile(filename="export.tar.gz", content=archive_bytes)


# --- Stub: client satisfying both protocols --------------------------------

class _StubClient:
    def __init__(self, archive_bytes: bytes, declared_sha256: str, first_chunk_size: int = 8) -> None:
        self.archive_bytes = archive_bytes
        self.declared_sha256 = declared_sha256
        self.first_chunk_size = first_chunk_size
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def plan_export(self, plan: str, revision: str | None = None) -> dict[str, Any]:
        self.calls.append(("plan_export", {"plan": plan, "revision": revision}))
        return {"root": f"/exports/{plan}", "files": len(_TREE), "revision": "rev-1"}

    async def export_archive(self, plan: str) -> dict[str, Any]:
        self.calls.append(("export_archive", {"plan": plan}))
        return {
            "plan": plan,
            "archive": "export.tar.gz",
            "size_bytes": len(self.archive_bytes),
            "sha256": self.declared_sha256,
            "file_count": len(_TREE),
        }

    async def export_read(self, plan: str, file: str, offset: int = 0, limit: int = 262144) -> dict[str, Any]:
        self.calls.append(("export_read", {"plan": plan, "file": file, "offset": offset, "limit": limit}))
        end = min(offset + min(limit, self.first_chunk_size), len(self.archive_bytes))
        chunk = self.archive_bytes[offset:end]
        return {
            "chunk_base64": base64.b64encode(chunk).decode("ascii"),
            "chunk_size": len(chunk),
            "total_size": len(self.archive_bytes),
            "sha256": self.declared_sha256,
            "eof": end >= len(self.archive_bytes),
        }


# --- Tests ----------------------------------------------------------------

def test_archive_is_requested_synchronously_after_export(tmp_path: Path) -> None:
    """Archive is requested (not guessed); export precedes archive; archive carries no revision."""
    archive_bytes = _build_archive(_TREE)
    correct_digest = hashlib.sha256(archive_bytes).hexdigest()
    stub = _StubClient(archive_bytes, correct_digest)

    async def run_test() -> ExportArchiveRef:
        return await request_export_archive(stub, plan="demo", revision="rev-1")

    ref = asyncio.run(run_test())

    assert ref.name == "export.tar.gz"
    assert ref.sha256 == correct_digest
    assert ref.file_count == len(_TREE)

    # Verify call order and arguments
    assert len(stub.calls) >= 2
    plan_export_call = stub.calls[0]
    archive_call = stub.calls[1]

    assert plan_export_call[0] == "plan_export"
    assert plan_export_call[1]["plan"] == "demo"
    assert plan_export_call[1]["revision"] == "rev-1"

    assert archive_call[0] == "export_archive"
    assert archive_call[1]["plan"] == "demo"
    assert "revision" not in archive_call[1], "export_archive must not receive revision argument"


def test_archive_is_retrieved_by_its_returned_name(tmp_path: Path) -> None:
    """Archive is fetched by the exact name returned by archive command, not a guessed one."""
    archive_bytes = _build_archive(_TREE)
    correct_digest = hashlib.sha256(archive_bytes).hexdigest()
    stub = _StubClient(archive_bytes, correct_digest)

    async def run_test() -> tuple[ExportArchiveRef, ReassembledFile]:
        ref = await request_export_archive(stub, plan="demo", revision="rev-1")
        reassembled = await fetch_export_file(stub, plan="demo", file=ref.name)
        return ref, reassembled

    ref, reassembled = asyncio.run(run_test())

    # Every export_read call must use the returned name
    for call_name, call_args in stub.calls:
        if call_name == "export_read":
            assert call_args["file"] == "export.tar.gz", f"export_read called with wrong file name: {call_args['file']}"

    # Multi-chunk reassembly must preserve order and content
    assert reassembled.content == archive_bytes


def test_digest_is_verified_before_unpacking(tmp_path: Path) -> None:
    """Verification is a separate call that succeeds before unpack."""
    archive_bytes = _build_archive(_TREE)
    correct_digest = hashlib.sha256(archive_bytes).hexdigest()
    stub = _StubClient(archive_bytes, correct_digest)

    async def run_test() -> tuple[VerifiedFile, list[str]]:
        ref = await request_export_archive(stub, plan="demo", revision="rev-1")
        reassembled = await fetch_export_file(stub, plan="demo", file=ref.name)
        verified = verify_reassembled_file(reassembled)
        unpacked_paths = unpack_verified_archive(verified, tmp_path)
        return verified, unpacked_paths

    verified, unpacked_paths = asyncio.run(run_test())

    assert verified.content == archive_bytes
    assert len(unpacked_paths) > 0
    # Files should exist at their unpacked paths
    for path in unpacked_paths:
        assert (tmp_path / path).exists()


def test_digest_mismatch_aborts_and_leaves_nothing_written(tmp_path: Path) -> None:
    """Verification mismatch raises ExportIntegrityError and writes nothing."""
    archive_bytes = _build_archive(_TREE)
    stub = _StubClient(archive_bytes, declared_sha256="0" * 64)

    async def run_test() -> ReassembledFile:
        ref = await request_export_archive(stub, plan="demo", revision="rev-1")
        reassembled = await fetch_export_file(stub, plan="demo", file=ref.name)
        return reassembled

    reassembled = asyncio.run(run_test())

    with pytest.raises(ExportIntegrityError) as exc_info:
        verify_reassembled_file(reassembled)

    error = exc_info.value
    assert error.expected_sha256 == "0" * 64
    assert error.actual_sha256 == hashlib.sha256(archive_bytes).hexdigest()
    assert list(tmp_path.iterdir()) == []


def test_unpack_reproduces_the_exact_tree(tmp_path: Path) -> None:
    """Unpacking reproduces every file byte-for-byte at its original nested path."""
    archive_bytes = _build_archive(_TREE)
    correct_digest = hashlib.sha256(archive_bytes).hexdigest()
    stub = _StubClient(archive_bytes, correct_digest)

    async def run_test() -> list[str]:
        ref = await request_export_archive(stub, plan="demo", revision="rev-1")
        reassembled = await fetch_export_file(stub, plan="demo", file=ref.name)
        verified = verify_reassembled_file(reassembled)
        unpacked_paths = unpack_verified_archive(verified, tmp_path)
        return unpacked_paths

    unpacked_paths = asyncio.run(run_test())

    # Returned list equals _TREE keys in archive order
    assert unpacked_paths == list(_TREE)

    # Every file exists with byte-identical content
    for path, content in _TREE.items():
        full_path = tmp_path / path
        assert full_path.exists(), f"Expected file {path} does not exist"
        assert full_path.read_bytes() == content, f"Content mismatch for {path}"

    # Two same-named files are distinct (nested structure is preserved)
    assert (tmp_path / "G-001-frame" / "README.yaml").exists()
    assert (tmp_path / "G-001-frame" / "T-001-decl" / "README.yaml").exists()
    assert (tmp_path / "G-001-frame" / "README.yaml").read_bytes() == b"step_id: G-001\n"
    assert (tmp_path / "G-001-frame" / "T-001-decl" / "README.yaml").read_bytes() == b"step_id: T-001\n"


def test_entry_escaping_the_destination_is_refused(tmp_path: Path) -> None:
    """REFUSAL CLAUSE (ii): member whose path escapes the destination is refused whole."""
    archive_bytes = _build_archive_with_trailing_member(
        _TREE,
        tarfile.TarInfo(name="../escape.yaml"),
        b"x"
    )
    verified = _verified(archive_bytes)

    with pytest.raises(ExportUnpackError):
        unpack_verified_archive(verified, tmp_path)

    # Archive was refused whole; no partial tree
    assert list(tmp_path.iterdir()) == []
    # Nothing landed outside the destination
    assert not (tmp_path.parent / "escape.yaml").exists()


def test_entry_that_is_neither_regular_file_nor_directory_is_refused(tmp_path: Path) -> None:
    """REFUSAL CLAUSE (i): member that is not regular file/dir is refused whole.

    The symlink's path is deliberately benign (not escaping), so this test
    cannot pass via clause (ii). A symlink must be refused for being neither
    a regular file nor a directory, not followed.
    """
    archive_bytes = _build_archive_with_trailing_member(
        _TREE,
        _symlink_member("link.yaml", "spec.yaml")
    )
    verified = _verified(archive_bytes)

    with pytest.raises(ExportUnpackError):
        unpack_verified_archive(verified, tmp_path)

    # Archive was refused whole; no partial tree
    assert list(tmp_path.iterdir()) == []


def test_refusal_on_the_last_member_writes_nothing_at_all(tmp_path: Path) -> None:
    """ALL-OR-NOTHING PROPERTY: offender as last member leaves destination completely empty.

    This discriminating case proves validation completes over ALL members
    before ANY write begins. An implementation validating each before its own
    write would already have written every earlier _TREE file before reaching
    the offender.
    """
    # Test refusal clause (ii): path escape
    escape_archive = _build_archive_with_trailing_member(
        _TREE,
        tarfile.TarInfo(name="../escape.yaml"),
        b"x"
    )
    escape_dest = tmp_path / "escape_test"
    escape_dest.mkdir()

    with pytest.raises(ExportUnpackError):
        unpack_verified_archive(_verified(escape_archive), escape_dest)

    assert list(escape_dest.iterdir()) == [], "Escape refusal wrote partial tree"
    for path in _TREE:
        assert not (escape_dest / path).exists(), f"Earlier-valid file {path} was written despite offender"

    # Test refusal clause (i): neither regular file nor directory (symlink)
    symlink_archive = _build_archive_with_trailing_member(
        _TREE,
        _symlink_member("link.yaml", "spec.yaml")
    )
    symlink_dest = tmp_path / "symlink_test"
    symlink_dest.mkdir()

    with pytest.raises(ExportUnpackError):
        unpack_verified_archive(_verified(symlink_archive), symlink_dest)

    assert list(symlink_dest.iterdir()) == [], "Symlink refusal wrote partial tree"
    for path in _TREE:
        assert not (symlink_dest / path).exists(), f"Earlier-valid file {path} was written despite offender"


def test_retrieval_report_names_what_landed(tmp_path: Path) -> None:
    """Retrieval report names unpacked files and empty not_retrieved."""
    archive_bytes = _build_archive(_TREE)
    correct_digest = hashlib.sha256(archive_bytes).hexdigest()
    stub = _StubClient(archive_bytes, correct_digest)

    async def run_test() -> list[str]:
        ref = await request_export_archive(stub, plan="demo", revision="rev-1")
        reassembled = await fetch_export_file(stub, plan="demo", file=ref.name)
        verified = verify_reassembled_file(reassembled)
        unpacked_paths = unpack_verified_archive(verified, tmp_path)
        return unpacked_paths

    unpacked_paths = asyncio.run(run_test())

    report = build_retrieval_report(unpacked_paths)
    assert report.unpacked == tuple(_TREE)
    assert report.not_retrieved == ()

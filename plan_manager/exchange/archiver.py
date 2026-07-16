"""Pack a produced export tree into one gzip-compressed tar archive (C-016).

plan_manager owns the files it writes under the configured export root. The
export layout is a tree (source_spec.md and spec.yaml at the top, one
G-NNN-<slug>/ directory per global step holding its README.yaml, one
T-NNN-<slug>/ directory per tactical step nested inside it holding its own
README.yaml, and every atomic step in that tactical step's atomic_steps/
subdirectory as A-NNN-<slug>.yaml), and no command enumerates it: the export
production command reports a file COUNT, not a file list. This module packs
that whole tree into ONE archive written INSIDE the plan's own export
directory, so the shipped export_read command serves it back by a single
known name with no new transfer machinery, and one digest covers the whole
delivery.

Entries are stored with paths relative to the plan export directory, so
unpacking reproduces every file byte-for-byte under its original name and
relative position. Re-archiving replaces the previous archive rather than
accumulating copies, and the archive never contains itself.

The export-root boundary rule is not restated here: it lives once in
plan_manager.exchange.export_paths and is imported.
"""

from __future__ import annotations

import hashlib
import os
import tarfile
from pathlib import Path

from plan_manager.exchange.export_paths import resolve_export_subdirectory


# The single known name the archive is always written under, relative to the
# plan's export directory. A caller obtains the whole tree by requesting this
# one name through export_read; nothing has to enumerate the export.
ARCHIVE_FILENAME = "export.tar.gz"

# Prefix of the temporary archive written next to the final one before the
# atomic replace. Excluded from packing so an interrupted run cannot leak into
# a later archive.
_TEMP_ARCHIVE_PREFIX = ".export.tar.gz.tmp."


class ExportArchiveError(RuntimeError):
    """Base class for export-archive failures."""


class ExportArchiveBoundaryError(ExportArchiveError):
    """Raised when the plan name does not resolve inside the export root."""


class ExportArchiveTreeMissingError(ExportArchiveError):
    """Raised when the plan has no produced export tree to archive."""


def _sha256_file(path: Path) -> str:
    """Return the hex sha256 of the whole file, read in bounded blocks.

    Args:
        path: Absolute path of the file to digest.

    Returns:
        str: The lowercase hex sha256 digest of the file's bytes.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_files(plan_dir: Path) -> list[Path]:
    """List every packable regular file of the export tree, deterministically.

    Walks plan_dir recursively and collects each regular file's path relative
    to plan_dir. Symlinks are skipped so an archive can never carry an escape
    out of the export root. The archive itself and any temporary archive are
    skipped so the archive never contains itself.

    Args:
        plan_dir: Absolute path of the plan's export directory.

    Returns:
        list[Path]: Relative paths of every packable file, sorted by their
            POSIX string form for a deterministic packing order.
    """
    found: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(plan_dir):
        for filename in filenames:
            absolute = Path(dirpath) / filename
            if absolute.is_symlink():
                continue
            if not absolute.is_file():
                continue
            if filename == ARCHIVE_FILENAME:
                continue
            if filename.startswith(_TEMP_ARCHIVE_PREFIX):
                continue
            found.append(absolute.relative_to(plan_dir))
    return sorted(found, key=lambda item: item.as_posix())


def create_export_archive(export_root: str, plan_name: str) -> dict:
    """Pack a plan's produced export tree into one archive inside its own directory.

    Packs every regular file of ``<export_root>/<plan_name>/`` into a
    gzip-compressed tar archive at ``<export_root>/<plan_name>/export.tar.gz``,
    storing each entry under its path relative to that directory so unpacking
    reproduces the tree byte-for-byte with original names and relative
    positions. The archive is built as a temporary file in the same directory
    and atomically moved onto the final name, so re-archiving replaces the
    previous archive rather than accumulating copies and a failed run leaves no
    partial archive behind. The archive and any temporary of it are excluded
    from packing, so the archive never contains itself.

    Args:
        export_root: Configured export root directory.
        plan_name: The owning plan's canonical catalog name, which names its
            export directory under the export root.

    Returns:
        dict: {"archive": the archive's plan-relative name (str),
            "size_bytes": the archive's size in bytes (int), "sha256": the
            archive's whole-file hex sha256 (str), "file_count": the number of
            files packed (int)}.

    Raises:
        ExportArchiveBoundaryError: plan_name does not resolve to a direct
            child of the resolved export root.
        ExportArchiveTreeMissingError: the plan's export directory does not
            exist, or contains no packable file.
    """
    plan_dir = resolve_export_subdirectory(export_root, plan_name)
    if plan_dir is None:
        raise ExportArchiveBoundaryError(
            "plan export directory does not resolve inside the export root"
        )
    if not plan_dir.is_dir():
        raise ExportArchiveTreeMissingError("no export directory for this plan")

    members = _tree_files(plan_dir)
    if not members:
        raise ExportArchiveTreeMissingError("no exported files to archive for this plan")

    archive_path = plan_dir / ARCHIVE_FILENAME
    temp_path = plan_dir / f"{_TEMP_ARCHIVE_PREFIX}{os.getpid()}"
    try:
        with tarfile.open(temp_path, "w:gz") as tar:
            for relative in members:
                tar.add(plan_dir / relative, arcname=relative.as_posix())
        os.replace(temp_path, archive_path)
    except BaseException:
        if temp_path.exists():
            temp_path.unlink()
        raise

    return {
        "archive": ARCHIVE_FILENAME,
        "size_bytes": archive_path.stat().st_size,
        "sha256": _sha256_file(archive_path),
        "file_count": len(members),
    }

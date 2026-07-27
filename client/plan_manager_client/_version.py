"""Resolve the client package version from the single release source."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as installed_version
from pathlib import Path
import configparser
import tomllib


_DIST_NAME = "plan-manager-client"


def version_from_source_tree(module_file: Path | None = None) -> str:
    """Read the version from the repository root or, in an sdist, its frozen metadata."""
    here = (module_file or Path(__file__)).resolve()
    source_roots = (
        here.parents[2] / "pyproject.toml",
        here.parents[1] / "PKG-INFO",
        here.parents[1] / "setup.cfg",
    )
    for candidate in source_roots:
        if not candidate.is_file():
            continue
        if candidate.name == "pyproject.toml":
            data = tomllib.loads(candidate.read_text(encoding="utf-8"))
            return data["project"]["version"]
        if candidate.name == "PKG-INFO":
            for line in candidate.read_text(encoding="utf-8").splitlines():
                if line.startswith("Version: "):
                    return line.removeprefix("Version: ").strip()
            continue
        if candidate.name == "setup.cfg":
            parser = configparser.ConfigParser()
            parser.read(candidate, encoding="utf-8")
            if parser.has_option("metadata", "version"):
                return parser.get("metadata", "version").strip()
    raise RuntimeError("could not resolve plan-manager-client version from source metadata")


def resolve_version() -> str:
    """Return the installed distribution version, or the source-tree version before install."""
    try:
        return installed_version(_DIST_NAME)
    except PackageNotFoundError:
        return version_from_source_tree()


__version__ = resolve_version()


__all__ = ["__version__", "resolve_version", "version_from_source_tree"]

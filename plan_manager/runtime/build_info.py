"""Reader for the build-time embedded payloads carried by
``plan_manager._build``.

This module reads the build information mapping and the operator
documentation text that the release pipeline embeds into the
dedicated ``plan_manager._build`` package-data subpackage at build
time. It performs no rendering and no network access: it only reads
what the build embedded. The absence of an embedded payload at
runtime is a packaging defect surfaced as an explicit
:class:`RuntimeError` naming the missing payload; generated or
default content is never substituted.
"""

import json

BUILD_PACKAGE: str = "plan_manager._build"
BUILD_INFO_RESOURCE: str = "build_info.json"
OPERATOR_DOC_RESOURCE: str = "operator_doc.md"
REQUIRED_BUILD_KEYS: tuple[str, ...] = (
    "product",
    "package_version",
    "adapter_version",
    "build_date",
    "image_tag",
)


def _read_resource(name: str, missing_message: str) -> str:
    """Read the text content of one embedded build-time resource.

    :param name: file name of the resource inside the ``BUILD_PACKAGE``
        package-data subpackage (for example ``BUILD_INFO_RESOURCE`` or
        ``OPERATOR_DOC_RESOURCE``).
    :param missing_message: the exact message to raise as a
        :class:`RuntimeError` when the resource is absent or cannot be
        read.
    :returns: the UTF-8 text content of the resource.
    :raises RuntimeError: with ``missing_message`` when the resource is
        absent (``FileNotFoundError``, ``ModuleNotFoundError``) or
        otherwise unreadable (``OSError``). Never substitutes generated
        or default content.
    """
    from importlib.resources import files

    try:
        return (files(BUILD_PACKAGE) / name).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        raise RuntimeError(missing_message)


def build_info() -> dict:
    """Return the build information mapping embedded at build time.

    Reads ``BUILD_INFO_RESOURCE`` from ``BUILD_PACKAGE`` through
    :func:`_read_resource`, parses it as JSON, and validates that it
    is a mapping containing every key of ``REQUIRED_BUILD_KEYS`` with
    a non-empty string value.

    :returns: the parsed build information mapping, containing at
        least the keys "product", "package_version",
        "adapter_version", "build_date", and "image_tag", each mapped
        to a non-empty string.
    :raises RuntimeError: ``"build info payload missing"`` when the
        embedded resource is absent; ``"build info payload malformed:
        not valid JSON"`` when the resource content is not valid
        JSON; ``"build info payload malformed: missing or invalid key
        '<key>'"`` when the parsed value is not a mapping, or is
        missing one of ``REQUIRED_BUILD_KEYS``, or maps one of those
        keys to a value that is not a non-empty string.
    """
    text = _read_resource(BUILD_INFO_RESOURCE, "build info payload missing")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError("build info payload malformed: not valid JSON")
    for key in REQUIRED_BUILD_KEYS:
        if (
            not isinstance(data, dict)
            or not isinstance(data.get(key), str)
            or not data.get(key)
        ):
            raise RuntimeError(
                f"build info payload malformed: missing or invalid key {key!r}"
            )
    return data


def operator_doc() -> str:
    """Return the operator documentation text embedded at build time.

    Reads ``OPERATOR_DOC_RESOURCE`` from ``BUILD_PACKAGE`` through
    :func:`_read_resource`.

    :returns: the embedded operator documentation text, UTF-8 Markdown
        rendered from the single documentation source that also
        produces the installed man and info pages.
    :raises RuntimeError: with the exact message "operator
        documentation payload missing" when the embedded resource is
        absent. This exact message is a frozen contract with the
        command layer.
    """
    return _read_resource(OPERATOR_DOC_RESOURCE, "operator documentation payload missing")

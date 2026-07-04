"""Canonical JSON serialization for content-addressed storage."""
import hashlib
import json


def canonical_json(value: object) -> bytes:
    """Serialize ``value`` to canonical JSON bytes.

    Canonical JSON is defined as ``json.dumps`` with sorted keys, no ASCII
    escaping of non-ASCII characters, and no insignificant whitespace
    (comma/colon separators without trailing spaces), encoded as UTF-8.

    :param value: JSON-serializable Python value (e.g. dict, list, str,
        int, float, bool, None) to serialize.
    :return: canonical JSON encoding of ``value`` as UTF-8 bytes.
    """
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def content_hash(value: object) -> str:
    """Compute the SHA-256 hex digest of the canonical JSON of ``value``.

    :param value: JSON-serializable Python value to hash.
    :return: lowercase hexadecimal SHA-256 digest string of
        ``canonical_json(value)``.
    """
    return hashlib.sha256(canonical_json(value)).hexdigest()

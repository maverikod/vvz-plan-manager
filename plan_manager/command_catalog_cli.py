"""Offline CLI entry point: dump the complete command catalog (C-007) as JSON.

Realises the offline surface of the CommandCatalog object: an entry point
that emits the complete catalog in the same per-entry shape as the online
command_catalog_dump JSON-RPC command, generated from the live command
inventory rather than hand-maintained.
"""

from __future__ import annotations

import json
import sys

from plan_manager.views.command_catalog import build_command_catalog

def main() -> int:
    """Print the complete command catalog as JSON to stdout and return 0.

    :return: Exit code 0 on success.
    :rtype: int
    """
    catalog = build_command_catalog()
    json.dump(catalog, sys.stdout, indent=2, sort_keys=False)
    sys.stdout.write("\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())

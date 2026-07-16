"""Plan import/export helpers for the standard exchange layout.

Delivery integration frame (CR-2, ExportDeliveryIntegration, C-001): the
export/transfer delivery gap is closed by integrating delivery into the
toolchain, not by exposing raw transfer plumbing to callers. Two delivery
paths are owned by this decision, selected by whether a code-analysis
project is specified:

* Path A (project specified): the exported files are written into the
  project's documentation area on the code-analysis service and committed
  to git by that service's own commands, so the external project picks the
  export up from its repository.
* Path B (no project specified): a Python client library, based on the
  adapter's existing client, translates all API calls, hides every network
  interaction, and retrieves the export files byte-identically to the
  caller's local filesystem.

An MCP-only caller completes either path without shell access, raw HTTP
access to internal hosts, or manual byte reconstruction. The byte source
underlying both paths is the plan_manager export_read command (module
plan_manager.commands.export_read_command, class ExportReadCommand); the
adapter's generic chunk-transfer builtins stay deliberately unwired from
export output. Both paths are realised by later branches of this change
request; this declaration is their single authoritative anchor.
"""

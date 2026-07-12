# Block ID: cas-preview-addressing

Server:
- `code-analysis-server-vvz`

Primary command:
- `universal_file_preview`

Confirmed navigation rules:
- Healthy structured file:
  - preview root
  - drill down by returned integer `node_ref` / short_id
  - use `selector` only as block filtering, not as line addressing
- Whole small file:
  - set `full_text_max_lines` high enough to inline the whole tree
- Invalid/unparseable file:
  - use `preview_offset` and `max_chars`
  - `node_ref` / `selector` are rejected until syntax is fixed

Confirmed anti-patterns:
- Do not use line/string addressing on healthy structured files
- Do not treat MAP UUIDs as public addressing
- Do not reuse stale identifiers after the file changed without re-preview

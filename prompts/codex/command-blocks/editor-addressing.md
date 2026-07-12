# Block ID: editor-addressing

Server:
- `ai-editor-server-vvz`

Confirmed addressing rules:
- Python / JSON / YAML / Markdown in healthy structured mode:
  - use `node_id` / `node_ref` values derived from preview
  - prefer marked-tree integer short_id round-tripped as strings where required
- Invalid parse fallback or plain text:
  - use line-based edits only after the session is in fallback/text mode

Confirmed anti-patterns:
- Parent + child Python targets in one batch are forbidden
- Reusing old line numbers after prior edits is unsafe; re-preview first
- Line-based addressing is not the default for healthy structured files

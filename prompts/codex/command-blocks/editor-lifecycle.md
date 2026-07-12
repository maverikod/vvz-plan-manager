# Block ID: editor-lifecycle

Server:
- `ai-editor-server-vvz`

Upstream dependency:
- CA `session_create` from `code-analysis-server-vvz`

Confirmed lifecycle:
1. `session_create` on CAS
2. `universal_file_open`
3. `universal_file_preview`
4. `universal_file_edit`
5. `universal_file_write` with `write_mode=preview`
6. `universal_file_write` with `write_mode=commit`
7. `universal_file_close`

Confirmed laws:
- Content mutation belongs to AI Editor
- `open` does internal lock/download orchestration; do not split it manually
- `edit` changes draft only
- `write preview` is diff only
- `write commit` validates then uploads
- `close` is mandatory

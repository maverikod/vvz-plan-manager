# Block ID: terminal-sandbox

Server:
- `mcp-terminal-vvz`

Use for:
- Running code in sandbox
- CAS capability fallback when necessary

Confirmed command group:
- `terminal_session_create`
- `terminal_run`
- `terminal_get_status`
- `terminal_read`, `terminal_tail`, `terminal_stat`
- `terminal_attach`, `terminal_send`, `terminal_read_shell`, `terminal_detach`
- `terminal_delete`

Confirmed laws:
- `terminal_run` is always asynchronous
- Poll status; queue completion is not command success
- Sandbox is the normal terminal mode
- Host execution is separate and not the same lifecycle

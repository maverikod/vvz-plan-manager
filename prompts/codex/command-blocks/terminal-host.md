# Block ID: terminal-host

Server:
- `mcp-terminal-vvz`

Primary command:
- `terminal_host_exec`

Confirmed laws:
- Host execution is separate from sandbox execution
- It requires explicit user authorization
- It runs through SSH, not through sandbox container lifecycle
- Preferred style is explicit `argv`
- Poll with `terminal_get_status`; read with `terminal_read` / `terminal_tail`

Authorization policy:
- default deny
- authorization must name host, remote user, allowed purposes, and time or action scope
- valid scope examples:
  - one action
  - several named actions
  - one hour
  - one day
- do not reuse host authorization outside its granted scope

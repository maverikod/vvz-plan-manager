# Block ID: mac-model-access

Server:
- `mac-server`

Use for:
- Session-based model access through the Model Access Core

Confirmed command group:
- `model_session_create`
- `model_chat`
- `model_providers`
- `model_provider_status`
- `model_health`
- `model_count_tokens`
- `model_estimate_request_capacity`

Confirmed facts:
- `model_session_create` performs capability checks and returns a reusable session
- `model_chat` supports session-bound or inline identity calls
- streaming is not supported in the documented MVP path

# Block ID: embedding-service

Server:
- `embedding-service-vvz`

Use for:
- Text embeddings, model inventory, queue-backed vectorization diagnostics

Confirmed command group:
- `embed_execute`
- `models`
- `health`
- `info`

Confirmed facts:
- `embed_execute` creates embeddings for input texts and is queue-backed in service workflow
- `models` returns available embedding models
- health reports queue, GPU, and model readiness metrics

# Homelab Runbook (sample document)

This is a sample document so the first `ansible-playbook playbooks/ingest.yml`
run has something to embed. Replace this directory (or point
`ingest_local_docs_dir` somewhere else) with your real notes.

## Restarting the stack

All services live under `/opt/ask-my-docs/<service>` as Docker Compose
projects. To restart one:

    cd /opt/ask-my-docs/ollama && docker compose restart

## Where data lives

- Ollama models: `ollama_data` Docker volume
- Vector embeddings: `qdrant_data` Docker volume
- Chat history: `openwebui_data` Docker volume
- Traces: Langfuse Postgres + ClickHouse volumes

## Backup policy

Snapshot the Docker volumes weekly. Qdrant supports point-in-time snapshots
via `POST /collections/{name}/snapshots`.

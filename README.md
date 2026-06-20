# Ask My Docs

An Ansible-deployed, local RAG chatbot on a single Ubuntu server. Upload
your docs and notes, chat with them through Open WebUI, and trace every
query and ingestion run in Langfuse Cloud. Inference and storage stay on
the machine; the only data that leaves is the traces you send to Langfuse.

```
Ansible (your laptop)
    │  SSH
    ▼
Ubuntu server ── Docker Compose
    ├── Ollama       LLM + embedding inference (Llama 3.2 3B, nomic-embed-text)
    ├── Qdrant       vector store for document embeddings
    ├── Open WebUI   chat frontend with native Qdrant-backed RAG
    └── Pipelines    runs the Langfuse filter that traces every chat
                          │
                          ▼ (chat traces + ingestion traces)
                  Langfuse Cloud   observability for queries + ingestion
```

Ollama and Qdrant bind to localhost and talk to Open WebUI over the compose
network; only Open WebUI (port 3000) is published. Network access to the box
is expected to be gated upstream (e.g. Tailscale), so the playbook does not
manage a host firewall.

## Layout

Nine files of substance — the whole system is readable in one sitting:

```
inventory.yml.example     → copy to inventory.yml, set server IP/user (gitignored)
vars/
  main.yml                  every tunable: images, ports, models, chunking
  secrets.yml.example     → copy to secrets.yml, fill keys, ansible-vault encrypt
playbooks/
  deploy.yml                THE playbook: Docker → compose up → pull models
  ingest.yml                one-shot: ship docs → embed via Ollama → upsert to Qdrant
  templates/
    docker-compose.yml.j2   the entire stack, one file
    ingest.env.j2           config handed to the ingest script
  files/
    ingest.py               chunk → embed → upsert, Langfuse-traced
    requirements.txt
docs-sample/                sample doc so the first ingest run has input
```

Docker installation is delegated to the battle-tested `geerlingguy.docker`
role rather than hand-rolled apt tasks. Everything is idempotent: compose
reconciles container state, model pulls are skipped when the model exists,
and ingestion uses deterministic point IDs so re-runs overwrite instead of
duplicating.

## Prerequisites

- Target: Ubuntu 22.04/24.04, ≥ 8 GB RAM (Llama 3.2 3B Q4 needs ~2 GB; CPU-only is fine),
  ≥ 30 GB disk, and working DNS resolution. Passwordless sudo is assumed; if your
  user needs a sudo password, add `-K` to the deploy commands.
- Control machine: Ansible ≥ 2.15 (`pipx install ansible`).
- A free [Langfuse Cloud](https://cloud.langfuse.com) project (for traces).

## Quick start

```bash
# 1. Install the Ansible collections + Docker role
make setup

# 2. Point Ansible at your server
cp inventory.yml.example inventory.yml && $EDITOR inventory.yml

# 3. Create and encrypt secrets
cp vars/secrets.yml.example vars/secrets.yml
$EDITOR vars/secrets.yml     # openssl rand -hex 32 for the WebUI key,
                             # Langfuse keys from cloud.langfuse.com
make encrypt                 # ansible-vault encrypt vars/secrets.yml

# 4. Verify connectivity, then deploy (first run pulls several GB: images + model)
make ping
make deploy                  # prompts for the vault password (assumes passwordless sudo)

# 5. Chat: http://<server>:3000  (first signup becomes admin)
```

Tip: put your vault password in `.vault-password` (gitignored) and
uncomment `vault_password_file` in `ansible.cfg` to skip the prompt.

## Ingesting your documents

```bash
make ingest DOCS=~/notes     # defaults to docs-sample/ if DOCS is omitted
```

This copies your `.md`/`.txt` files to the server, chunks them (~800 chars,
120 overlap), embeds each chunk with `nomic-embed-text` via Ollama, and
upserts into the `ask_my_docs` Qdrant collection. Each run appears in
Langfuse as one trace with a span per file.

### How RAG works in the chat UI

Open WebUI is configured with `VECTOR_DB=qdrant` and Ollama-backed
embeddings, so documents you upload through the UI (Workspace → Knowledge,
or `#` in chat) are embedded locally and stored in Qdrant. `ingest.py` is
the scripted, repeatable path for bulk-loading a docs folder — same Qdrant,
same embedding model, traced in Langfuse.

### Chat tracing

The `pipelines` container loads the official Langfuse filter on startup and
registers with Open WebUI as an OpenAI-compatible connection. The filter
fires on every chat completion (it applies to all models), so each question
you ask shows up in Langfuse as a trace with the prompt, the model response,
latency, and — when RAG is used — the retrieved document context. Chat still
runs on Ollama; the filter only observes. The Langfuse keys come from
`secrets.yml` via the container's environment, so there's nothing to click
in the UI.

Two requirements for traces to appear: the keys in `secrets.yml` must be
valid, and the server needs outbound internet on first boot (the filter is
downloaded and its `langfuse` dependency pip-installed). If keys are blank,
chat works normally and tracing is simply silent.

## Day-2 operations

```bash
make deploy                          # re-run everything (idempotent)
make check                           # dry-run with diff

# Change the chat model: edit chat_model in vars/main.yml, then make deploy

# On the server
ssh <server> 'cd /opt/ask-my-docs && docker compose logs -f openwebui'
ssh <server> 'cd /opt/ask-my-docs && docker compose restart ollama'
```

## Design decisions

- **No Terraform** — the target is an existing machine; `inventory.yml`
  *is* the provisioning interface.
- **Flat playbooks, not roles** — at four containers, role scaffolding
  hides more than it organizes. `deploy.yml` reads top-to-bottom as the
  full deployment story.
- **One compose file** — the whole architecture is visible in one place,
  and compose's default network gives service discovery for free.
- **Langfuse Cloud, not self-hosted** — self-hosting Langfuse v3 means six
  extra containers (Postgres, ClickHouse, Redis, MinIO, web, worker).
  Tracing is the one piece where SaaS buys the most simplicity; swapping in
  self-hosted later is a one-variable change (`langfuse_host`) plus its own
  deployment project.
- **Pinned images, vaulted secrets, idempotent everything** — upgrades are
  deliberate var changes in git; `make deploy` twice is a no-op.

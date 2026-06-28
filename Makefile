.PHONY: setup ping encrypt platform deploy up check ingest lint

# One-time local setup: install required Ansible collections + roles
setup:
	ansible-galaxy install -r requirements.yml

# Verify SSH connectivity to the target
ping:
	ansible llm_servers -m ping

# Encrypt the secrets file (prompts you to create a vault password)
encrypt:
	ansible-vault encrypt vars/secrets.yml

# Deploy the inference platform (Ollama + LiteLLM + Postgres).
# Assumes passwordless sudo; add -K if your user needs a sudo password.
platform:
	ansible-playbook platform/platform.yml --ask-vault-pass

# Deploy the AI stack (Open WebUI + Qdrant + Pipelines).
deploy:
	ansible-playbook playbooks/deploy.yml --ask-vault-pass

# Bring up everything in order: platform first, then the AI stack.
up:
	$(MAKE) platform
	$(MAKE) deploy

# Dry-run the AI stack deploy
check:
	ansible-playbook playbooks/deploy.yml --ask-vault-pass --check --diff

# Embed documents into Qdrant (override docs dir: make ingest DOCS=~/notes)
DOCS ?=
ingest:
	ansible-playbook playbooks/ingest.yml --ask-vault-pass $(if $(DOCS),-e ingest_docs_dir=$(DOCS))

# Lint everything
lint:
	yamllint .
	ansible-lint

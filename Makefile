.PHONY: setup ping encrypt deploy check ingest lint

# One-time local setup: install required Ansible collections + roles
setup:
	ansible-galaxy install -r requirements.yml

# Verify SSH connectivity to the target
ping:
	ansible llm_servers -m ping

# Encrypt the secrets file (prompts you to create a vault password)
encrypt:
	ansible-vault encrypt vars/secrets.yml

# Deploy the full stack. Assumes passwordless sudo on the server; only the
# vault password is prompted (--ask-vault-pass). If your user needs a sudo
# password, add -K to these commands.
deploy:
	ansible-playbook playbooks/deploy.yml --ask-vault-pass

# Dry-run the deploy
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

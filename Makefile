UV ?= uv
INVENTORY ?= inventory/local.yml

.PHONY: setup build test lint check syntax plan apply demo
setup:
	$(UV) sync --locked
	$(UV) run ansible-galaxy collection install -r requirements.yml
build:
	$(UV) run python scripts/build_cli.py
test:
	$(UV) run pytest -q
lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .
syntax: build
	ANSIBLE_BECOME_ASK_PASS=False $(UV) run ansible-playbook -i inventory/example.yml site.yml --syntax-check
check: lint test syntax
plan: build
	$(UV) run ansible-playbook -i $(INVENTORY) site.yml --check --diff
apply: build
	$(UV) run ansible-playbook -i $(INVENTORY) site.yml -e homeinfra_apply=true
demo:
	$(UV) run python examples/hello/app.py

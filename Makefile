# Developer entry points. Everything runs inside the toolchain container unless
# IN_CONTAINER=1 (the container itself sets it), so no local Python 3.14 is required.

RUN ?= docker compose run --rm -e IN_CONTAINER=1 test
ifeq ($(IN_CONTAINER),1)
RUN :=
endif

.DEFAULT_GOAL := help

.PHONY: help
help: ## List the available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

.PHONY: build
build: ## Build the toolchain image
	docker compose build test

.PHONY: lint
lint: ## ruff check + format check
	$(RUN) ruff check .
	$(RUN) ruff format --check .

.PHONY: format
format: ## ruff format + autofix
	$(RUN) ruff check --fix .
	$(RUN) ruff format .

.PHONY: type
type: ## mypy --strict
	$(RUN) mypy

.PHONY: test
test: ## pytest with coverage
	$(RUN) pytest --cov --cov-report=term-missing --cov-report=xml

.PHONY: libtest
libtest: ## pytest for the pyngbsicon library only
	$(RUN) pytest lib/pyngbsicon/tests

.PHONY: check
check: lint type test ## Everything CI runs (mandatory before a commit)

.PHONY: fixtures
fixtures: ## Capture and anonymise controller responses into tests/fixtures (needs .env)
	python3 scripts/record_fixtures.py

.PHONY: ha-up
ha-up: ## Start the development Home Assistant (http://localhost:8123)
	./scripts/dev-ha.sh up

.PHONY: ha-down
ha-down: ## Stop the development Home Assistant
	./scripts/dev-ha.sh down

.PHONY: ha-logs
ha-logs: ## Follow the development Home Assistant log (integration lines)
	./scripts/dev-ha.sh logs

.PHONY: deploy
deploy: ## Deploy the integration to the Home Assistant in .env (ARGS=--dry-run to inspect only)
	$(RUN) python scripts/deploy_ha.py $(ARGS)

.PHONY: zip
zip: ## Build dist/ngbs_icon.zip (integration + vendored pyngbsicon at the zip root)
	./scripts/build-zip.sh

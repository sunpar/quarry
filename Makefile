.PHONY: deps hooks smoke check coverage check-commit pr linux-build linux-check linux-shell linux-serve linux-down

LINUX_PLATFORM ?= $(shell docker version --format '{{.Server.Os}}/{{.Server.Arch}}')
LINUX_PLATFORM_TAG = $(subst /,-,$(LINUX_PLATFORM))
LINUX_COMPOSE = LINUX_PLATFORM="$(LINUX_PLATFORM)" LINUX_PLATFORM_TAG="$(LINUX_PLATFORM_TAG)" docker compose --project-name "quarry-$(LINUX_PLATFORM_TAG)"

# Downloads happen only during setup. Other checks use installed local tools.
deps:
	node scripts/local-checks.mjs deps

hooks:
	node scripts/git-gate.mjs install

smoke:
	node scripts/git-gate.mjs commit

check:
	node scripts/local-checks.mjs full

coverage:
	node scripts/local-checks.mjs coverage

check-commit:
	node scripts/git-gate.mjs check $(REF)

# Core PR options; for example ARGS='--draft --title "..." --body-file ...'
pr:
	node scripts/git-gate.mjs pr $(ARGS)

# Resolve Docker only when a Linux target runs, once per invocation.
linux-build:
	$(eval LINUX_PLATFORM := $(LINUX_PLATFORM))
	$(LINUX_COMPOSE) build check

linux-check: linux-build
	$(LINUX_COMPOSE) run --rm check

linux-shell: linux-build
	$(LINUX_COMPOSE) run --rm check /bin/bash

linux-serve:
	$(eval LINUX_PLATFORM := $(LINUX_PLATFORM))
	$(LINUX_COMPOSE) build quarry
	$(LINUX_COMPOSE) up quarry relay

linux-down:
	$(eval LINUX_PLATFORM := $(LINUX_PLATFORM))
	$(LINUX_COMPOSE) down

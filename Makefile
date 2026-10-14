.PHONY: deps hooks smoke check coverage check-commit pr

# Downloads happen only during setup. Other checks use installed local tools.
deps:
	node scripts/local-checks.mjs deps

hooks:
	git config extensions.worktreeConfig true
	git config --worktree core.hooksPath .githooks

smoke:
	node scripts/git-gate.mjs commit

check:
	node scripts/local-checks.mjs full

coverage:
	node scripts/local-checks.mjs coverage

check-commit:
	node scripts/git-gate.mjs check $(REF)

# Supported gh pr create options; for example ARGS='--draft --title "..." --body-file ...'
pr:
	node scripts/git-gate.mjs pr $(ARGS)

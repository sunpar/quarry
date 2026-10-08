# Quarry

Agentic data exploration for quant researchers. Design: `docs/superpowers/specs/2026-10-08-quarry-design.md`.

## Development

    uv sync --all-extras
    uv run pytest
    uv run ruff check src tests && uv run ruff format --check src tests
    uv run mypy src

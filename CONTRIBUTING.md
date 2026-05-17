# Contributing to Hippocamp

Thanks for your interest! Hippocamp is a small, focused project, and contributions of any size — bug reports, doc fixes, features — are welcome.

## Dev setup

Hippocamp uses [`uv`](https://docs.astral.sh/uv/) for dependency management. The committed `uv.lock` pins exact versions so installs are reproducible.

```bash
git clone https://github.com/Prageethcs/hippocamp.git
cd hippocamp
uv sync --extra dev --extra mcp
```

That installs the `dev` extra (pytest, ruff, sentence-transformers) and the `mcp` extra (for the MCP server tests). The optional `llm` extra (Anthropic SDK, for `reflect()`) is only needed if you're working on reflection — tests use a mock LLM.

Supported Python versions: 3.11, 3.12, 3.13.

## Running tests

```bash
uv run pytest -v
```

The full suite is ~80 tests and runs in under 10 seconds locally. CI runs the same suite across Python 3.11/3.12/3.13 on every push and PR.

A few notes:

- `tests/test_semantic.py` auto-skips if `sentence-transformers` isn't installed. With the `dev` extra installed it runs the BGE-small embedder against real text (~5s including model load).
- `tests/test_reflect.py` uses a mock LLM — no API key needed.
- Tests run against `:memory:` SQLite stores; nothing touches your real `~/.hippocamp` store.

## Project layout

```
src/hippocamp/         # package source
  cli.py               # `hippocamp` CLI entry point
  mcp_server.py        # `hippocamp-mcp` server (recall/update/reflect tools)
  memory.py            # Memory facade — what users import as hc.Memory
  store.py             # SQLite backend
  events.py            # event-log + per-device files for portable sync
  embedders.py         # BGE-small, Qwen3, Hash embedders
  ranker.py            # similarity + recency + kind-boost + salience
  reflect.py           # LLM-driven consolidation
  setup_*.py           # `hippocamp setup <host>` integrations
tests/                 # pytest suite
templates/             # bundled instruction templates
scripts/               # eval / synthetic-data scripts (not shipped)
```

## Submitting a PR

- One PR per logical change. Prefer small, reviewable diffs.
- Match the existing commit-message style: short imperative subject (e.g. `ci: add GitHub Actions workflow for tests`, `README: reframe around tiered memory`). Version commits use `vX.Y.Z: <summary>`.
- Tests should pass locally (`uv run pytest`) before pushing.
- New behaviour needs a test. Bug fixes need a regression test.
- Update `CHANGELOG.md` under `## [Unreleased]` if your change is user-facing.

## Reporting bugs / requesting features

Use the issue templates in [.github/ISSUE_TEMPLATE/](.github/ISSUE_TEMPLATE/). For security issues, see [SECURITY.md](SECURITY.md) — please don't open public issues for vulnerabilities.

## License

By contributing, you agree that your contributions will be licensed under the Apache-2.0 license that covers the project.

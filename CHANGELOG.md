# Changelog

All notable changes to Hippocamp are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html) (within the 0.x line, expect occasional breaking changes between minor versions).

## [Unreleased]

### Added
- GitHub Actions CI: pytest matrix on Python 3.11/3.12/3.13.
- `CONTRIBUTING.md`, `CHANGELOG.md`, issue/PR templates.

## [0.5.0] — 2026-05

### Added
- `Memory.reflect()` — LLM-driven memory consolidation. Reads recent episodes, distils durable facts/preferences/reflections, supersedes near-duplicates. Persists `last_reflect_at` only on success so failed runs are retried.
- `reflect_memory` MCP tool, auto-exposed when the server boots with `ANTHROPIC_API_KEY` set.
- `hippocamp reflect [--since <iso-ts>]` CLI command.
- New memory kind: **reflection** (higher-order patterns spanning multiple episodes).
- Bundled Anthropic LLM adapter; any object with `complete(prompt, *, system) -> str` also works via `Memory(llm=...)`.
- Reflection lockfile (`.reflect.lock`) prevents concurrent runs across processes.

## [0.4.0]

### Changed
- Default embedder swapped to Qwen3 for better retrieval quality.
- Salience contribution in the ranker is now capped to avoid runaway boosts.

### Added
- `scripts/` — synthetic-data generation and embedder-quality eval harness.

## [0.3.4]

### Added
- `hippocamp instructions` and `hippocamp instructions --short` to print the directive for Claude Desktop / ChatGPT custom-instruction setup.

## [0.3.3]

### Changed
- `hippocamp setup claude` now configures Claude Code **and** Claude Desktop together when both are installed.

## [0.3.2]

### Added
- Proactive ambient memory in the directive: AI captures signals as they flow through conversation, no need to say "remember".

## [0.3.1]

### Added
- `hippocamp setup claude` auto-installs the Hippocamp directive block into `~/.claude/CLAUDE.md`, wrapped in idempotent markers.

## [0.3.0]

### Added
- **Event-log architecture** — every write is appended to a per-device file `events/<device_id>.jsonl`. Conflict-free across machines, since no two devices ever touch the same file.
- Cloud-synced store dir separated from local SQLite cache. Wipe the cache anytime; rebuild from events.
- `hippocamp sync` — one smart command that takes a local path, an SSH peer, or nothing (just rebuild).
- `hippocamp reindex [--embedder NAME]` for recomputing embeddings after a model swap.
- `hippocamp status` shows what's stored, where, by which devices.

## [0.1.0]

### Added
- Initial alpha. Tiered memory (episodes / facts / preferences), why-trace recall, first-class forgetting (supersedence + TTL + tombstones), SQLite backend, MCP server with `recall_memory` and `update_memory`, `hippocamp` CLI with `setup`/`inspect`.

[Unreleased]: https://github.com/Prageethcs/hippocamp/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/Prageethcs/hippocamp/releases/tag/v0.5.0
[0.4.0]: https://github.com/Prageethcs/hippocamp/releases/tag/v0.4.0
[0.3.4]: https://github.com/Prageethcs/hippocamp/releases/tag/v0.3.4
[0.3.3]: https://github.com/Prageethcs/hippocamp/releases/tag/v0.3.3
[0.3.2]: https://github.com/Prageethcs/hippocamp/releases/tag/v0.3.2
[0.3.1]: https://github.com/Prageethcs/hippocamp/releases/tag/v0.3.1
[0.3.0]: https://github.com/Prageethcs/hippocamp/releases/tag/v0.3.0
[0.1.0]: https://github.com/Prageethcs/hippocamp/releases/tag/v0.1.0

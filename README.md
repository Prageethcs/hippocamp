# Hippocamp

**One memory that works across every AI you use, on every machine you own.**

Hippocamp is a local-first, portable memory layer for LLM agents. Write a preference in Claude Code on your laptop, recall it from Cursor on your desktop. Tell ChatGPT something about your project; have it remembered when you switch to your own agent loop. Your memory follows you, not the host.

> *Local-first. Multi-host. Multi-machine. Yours.*

## Why portable matters

Most AI memory today is locked to one host *and* one machine:

- ChatGPT's "Memory" feature only works in ChatGPT, only on whatever device you're on.
- Claude Code's auto-memory is per-machine and Claude-only.
- Cloud agent-memory services (Mem0, Zep, Letta) want your data on their servers.

Hippocamp lives on your machines. Every host that speaks MCP — Claude Desktop, Claude Code, ChatGPT Apps, Cursor, Cline, Windsurf, your own agent loops — calls the same store. And by sticking the store in iCloud / Dropbox / Syncthing / a git repo, every machine you own sees the same memory. Your memory is yours.

## What it gives you

- **Tiered storage** — episodes, facts, preferences, and reflections — each with different retrieval semantics.
- **Observable retrieval** — every recall comes with a `why` trace explaining the score (similarity + recency + kind-boost + salience).
- **First-class forgetting** — TTL, supersedence, and redundancy collapse, all visible.
- **Local-first, multi-host, multi-machine** — SQLite cache on each machine; events log syncs through any file-sync mechanism you already use.
- **MCP-first** — wire it into any compliant host once, use it everywhere.
- **Conflict-free by design** — each device writes only to `events/<device_id>.jsonl`, so no two machines ever touch the same file.

## Install

```bash
pip install 'hippocamp[mcp,embeddings]'
```

Includes the MCP server and a real local embedder (BAAI/bge-small-en-v1.5, ~130MB, downloaded on first use).

## Wire it into your AI host

One command per host. Each is idempotent — safe to re-run, never overwrites existing config.

```bash
hippocamp setup claude          # Claude Code (uses `claude mcp add`)
hippocamp setup claude-desktop  # Claude Desktop
hippocamp setup cursor          # Cursor
hippocamp setup gemini-cli      # Gemini CLI
```

After setup, the host has two new tools: `recall_memory` and `update_memory`.

## Make memory work across all your machines

The whole architecture is built so this is one extra flag at setup time. Pick a folder your cloud service syncs (Dropbox, iCloud Drive, Syncthing, etc.) and pass it as `--path`:

```bash
# On every machine you use:
hippocamp setup claude --path "$HOME/Dropbox/Hippocamp"
```

Hippocamp puts `meta.json` and `events/<your-device>.jsonl` in that folder; every machine writes only to its own device file (no concurrent-write conflicts, ever); the SQLite cache stays *local* to each machine in `~/Library/Caches/hippocamp/...` (so the cloud only carries data, not an index).

When a fresh machine opens the synced folder for the first time, it auto-replays the events into its local cache. Same memory, same ranking, same `why` trace, on every device.

### iCloud Drive on macOS

```bash
hippocamp setup claude \
  --path "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Hippocamp"
```

### Self-hosted / privacy-first

[Syncthing](https://syncthing.net) gives you continuous P2P file sync without any third party. Add `~/Hippocamp/` as a synced folder on each device, then:

```bash
hippocamp setup claude --path "$HOME/Hippocamp"
```

### On-demand sync (rsync / git / USB stick)

If you'd rather sync explicitly:

```bash
# Push your device's events to a peer
hippocamp sync push user@desktop.local:~/.hippocamp/events/

# Pull a peer's events and merge them in
hippocamp sync pull user@desktop.local:~/.hippocamp/events/

# Or merge from any local source (USB, downloaded folder, git checkout)
hippocamp sync merge ~/Downloads/peers-hippocamp/
```

Events are line-append text files keyed by event id, so any union-style merge mechanism works.

## CLI reference

```bash
hippocamp setup HOST [--path DIR] [--cache-dir DIR]

hippocamp inspect [--query Q] [--limit N]
hippocamp replay                           # rebuild local cache from events
hippocamp reindex [--embedder NAME]        # recompute embeddings

hippocamp sync status
hippocamp sync merge <path>
hippocamp sync push <peer>                 # rsync our device file → peer
hippocamp sync pull <peer>                 # rsync peer's events/ → here, then replay
```

## Make Claude prefer Hippocamp over its built-in memory

Hosts have their own memory features. To make sure Hippocamp wins, drop [`templates/CLAUDE.md`](templates/CLAUDE.md) into projects where you want Hippocamp to be the default. To make it the global default, append the template into `~/.claude/CLAUDE.md` (Claude Code's user-scoped instructions).

## Quickstart — Python library

```python
import hippocamp as hc

mem = hc.Memory(path="~/Dropbox/Hippocamp")

mem.observe("User asked how to deploy to GCP")
mem.assert_fact("Project uses Python 3.13")
mem.assert_preference("Prefers terse replies", strength=1.0)

hits = mem.recall("how does the user like their replies?", limit=5)
for h in hits:
    print(h.kind, h.text, h.score, h.why.note)
```

## How sync works (architecture)

```
~/Dropbox/Hippocamp/         ← cloud-synced (the data)
├── meta.json
├── device.json
└── events/
    ├── laptop.jsonl         ← only this device writes
    └── desktop.jsonl        ← only that device writes

~/Library/Caches/hippocamp/  ← local-only (the index)
└── <store_id>/
    └── store.db
```

- `events.jsonl` is the source of truth. SQLite is a derivable cache.
- Each device writes only to its own `events/<device>.jsonl` — single-writer-per-file, so cloud sync has nothing to conflict over.
- On open, if events have new content the local cache hasn't seen, the cache rebuilds automatically. Stale `store.db` is never fatal.
- Embedder is a property of the store (`meta.json`), not the device — every device must agree, so recall is consistent everywhere. Switch with `hippocamp reindex --embedder NEW`.

## Status

**v0.3.0 (alpha).** Working: tiered memory, four-signal ranker with why-trace, real semantic recall (BGE small), MCP server with two tools, one-command setup for Claude Code / Claude Desktop / Cursor / Gemini CLI, supersedence-based forgetting, append-only event log, per-device files, cross-machine sync (file-based + rsync), embedder reindex, cloud-vs-cache directory separation. Coming next: HTTP/SSE transport for self-hosted always-on stores, encrypted multi-device relay (v0.4+).

## License

Apache-2.0

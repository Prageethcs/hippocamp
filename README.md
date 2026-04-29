# Hippocamp

**One memory that works across every AI you use.**

Hippocamp is a portable memory layer for LLM agents. Write a preference in Claude Code, recall it in Cursor. Tell ChatGPT something about your project, have it remembered when you switch to your own agent loop. Your memory follows you, not the host.

> *Local-first. Multi-host. Yours.*

## Why portable matters

Most AI memory today is locked to one host:

- ChatGPT's "Memory" feature only works in ChatGPT.
- Claude Code's auto-memory only works in Claude Code.
- Cloud agent-memory services (Mem0, Zep, Letta) want your data on their servers.

Hippocamp lives on your machine. Every host that speaks MCP — Claude Desktop, Claude Code, ChatGPT Apps, Cursor, Cline, Windsurf, your own agent loops — calls the same store at `~/.hippocamp/store.db`. Your memory is yours.

## What it gives you

- **Tiered storage** — episodes, facts, preferences, and reflections — each with different retrieval semantics.
- **Observable retrieval** — every recall comes with a `why` trace explaining the score (similarity + recency + kind-boost + salience).
- **First-class forgetting** — TTL, supersedence, and redundancy collapse, all visible.
- **Local-first** — SQLite on your machine. Never the cloud.
- **MCP-first** — wire it into any compliant host once, use it everywhere.

## Install

```bash
pip install 'hippocamp[mcp,embeddings]'
```

Includes the MCP server and a real local embedder (BAAI/bge-small-en-v1.5, ~130MB, downloaded on first use).

## Wire it into Claude Code (or any MCP host)

```bash
claude mcp add -s user hippocamp -- $(which hippocamp-mcp)
```

Or add to `~/.claude.json` / `claude_desktop_config.json` / your host's config directly:

```json
{
  "mcpServers": {
    "hippocamp": { "command": "hippocamp-mcp" }
  }
}
```

The host now has two tools: `recall_memory` and `update_memory`.

### Make Claude prefer Hippocamp over its built-in memory

Many hosts have their own memory features. To make sure Hippocamp wins, drop [`templates/CLAUDE.md`](templates/CLAUDE.md) into the root of any project where you want Hippocamp to be the default. It's a short instruction set that tells the assistant when to use Hippocamp vs the host's built-in.

### Make Hippocamp the global default

If you want Hippocamp preferred *everywhere*, not just in templated projects, append the template into your user-scoped Claude Code config:

```bash
mkdir -p ~/.claude
cat /path/to/hippocamp/templates/CLAUDE.md >> ~/.claude/CLAUDE.md
```

Claude Code reads `~/.claude/CLAUDE.md` as user-scoped instructions in every session, so Hippocamp will be preferred over the host's auto-memory in any directory.

## Quickstart — Python library

```python
import hippocamp as hc

mem = hc.Memory(path="~/.hippocamp/store.db")

mem.observe("User asked how to deploy to GCP")
mem.assert_fact("Project uses Python 3.13")
mem.assert_preference("Prefers terse replies", strength=1.0)

hits = mem.recall("how does the user like their replies?", limit=5)
for h in hits:
    print(h.kind, h.text, h.score, h.why.note)
```

## Status

Pre-alpha. v0.0.1 ships with: tiered memory, four-signal ranker, real semantic recall (BGE small), MCP server, supersedence-based forgetting. Coming next: `sqlite-vec` for production-scale vector search, `reflect()` LLM consolidation, encrypted device sync.

## License

Apache-2.0

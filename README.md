# Hippocamp

Local-first agent memory with tiered storage, observable retrieval, and first-class forgetting.

> *Memory that's yours, runs on your machine, plugs into any AI.*

## What it is

Hippocamp is an opinionated memory engine for LLM agents. Two artifacts from one core:

1. **Python library** — `pip install hippocamp` for builders writing agent loops directly against the Anthropic / OpenAI / LangGraph SDKs.
2. **MCP server** — `hippocamp-mcp` exposes the same engine to any MCP-compatible host (Claude Desktop, Claude Code, ChatGPT Apps, Cursor, Cline, Windsurf). Memory data lives on the user's machine; hosts only call the server.

## Why it's different

Most agent-memory libraries dump everything into one vector store and call cosine similarity "memory." Hippocamp's wedge:

- **Tiered storage**: distinct memory *kinds* (episode, fact, preference, reflection) with different retrieval semantics.
- **Observable**: every recall comes with a `why` trace explaining how the score was composed (similarity + recency + kind-boost + salience).
- **First-class forgetting**: TTL, supersedence, and redundancy collapse are features, not afterthoughts.
- **Local-first**: SQLite on your machine, never the cloud.
- **Embedding-model-agnostic**: swap models without re-migrating.

## Quickstart — Python

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

## Quickstart — MCP

```bash
pip install 'hippocamp[mcp]'
```

Wire into Claude Desktop / Cursor / etc:

```json
{
  "mcpServers": {
    "hippocamp": { "command": "hippocamp-mcp" }
  }
}
```

Two tools are exposed: `recall_memory` and `update_memory`. Memory lives at `~/.hippocamp/store.db` — never leaves your machine.

## Status

Pre-alpha. v0.0.1 is a working scaffold: ranking, storage, kind filtering, and supersedence pass tests with a stub embedder. Real embedding model, `reflect()` consolidation, and sqlite-vec acceleration arrive in v0.1.0.

## License

Apache-2.0

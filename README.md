# Hippocamp

**Memory that follows you across every AI and every machine.**

Tell Claude something on your laptop, recall it from Cursor on your desktop. Mention a preference to ChatGPT, your custom agent will know it too. Your memory is yours, runs locally, syncs everywhere.

---

## Get started in 30 seconds

```bash
pip install 'hippocamp[mcp,embeddings]'
hippocamp setup claude
```

Restart Claude Code. Try:

> *"Remember that I prefer terse replies and my project uses Python 3.13."*

Then in any future Claude session, ask *"what do you remember about me?"* and Hippocamp will surface what you said.

## Make it work on every machine you own

Pick a folder your cloud syncs (Dropbox, iCloud, Syncthing — anything). On every machine, run:

```bash
hippocamp setup claude --path ~/Dropbox/Hippocamp
```

That's literally it. Memory written on your laptop appears on your desktop, your work machine, anywhere. Nothing to configure, nothing to merge, nothing to think about.

## Use it with other AIs

```bash
hippocamp setup claude-desktop      # Claude Desktop
hippocamp setup cursor              # Cursor
hippocamp setup gemini-cli          # Gemini CLI
```

Same memory, every host. Pass the same `--path` if you want cross-machine sync.

## What just happened

Each AI you wired up now has two new tools — `recall_memory` and `update_memory` — that read and write a private SQLite database on your machine. Memory is *yours*: never sent to a third party, portable across every AI, lives on every device you own.

```
~/Dropbox/Hippocamp/         ← cloud-synced (the data — meta + per-device events)
~/Library/Caches/hippocamp/  ← local-only (the index, rebuilt automatically)
```

That's the whole architecture. Each device writes only to its own events file (no sync conflicts ever); the local cache is rebuilt on demand.

---

## Day-to-day commands

```bash
hippocamp inspect                     # see what's stored, with why-traces
hippocamp inspect --query "python"    # ranked recall

hippocamp sync status                 # whose events live in this store
hippocamp sync merge <path>           # merge a peer's events (USB, downloaded folder, ...)
hippocamp sync push <peer>            # rsync your events file to a peer
hippocamp sync pull <peer>            # rsync a peer's events here, then replay

hippocamp replay                      # rebuild the local cache from events
hippocamp reindex [--embedder NAME]   # recompute embeddings (after a model swap)
```

## Python library

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

## Make Claude prefer Hippocamp over its built-in memory (optional)

Most hosts have their own memory features. Hippocamp's tool descriptions are pretty assertive, but if you want to be sure the host always uses Hippocamp, drop [`templates/CLAUDE.md`](templates/CLAUDE.md) into your project (or append to `~/.claude/CLAUDE.md` for a global default).

## Why this exists

Most AI memory today is locked: ChatGPT's memory works only in ChatGPT, on whatever device you're on. Claude Code's memory works only in Claude Code. Cloud agent-memory services (Mem0, Zep, Letta) want your data on their servers.

Hippocamp inverts that. **Your memory lives on your machine, in a directory you control, and any AI that speaks MCP can read or write it.** Switch hosts; your memory is still there. Switch laptops; your memory is still there. The lock-in disappears.

The technical wedges:

- **Tiered memory** — episodes / facts / preferences are stored separately, so retrieval can use the right semantics for each.
- **Why-trace** — every recall comes back with a breakdown of *why* the result ranked where it did (similarity + recency + kind-boost + salience).
- **First-class forgetting** — supersedence, TTL, and tombstones are features, not afterthoughts.
- **Conflict-free sync** — each device writes to `events/<device_id>.jsonl`, so no two machines ever touch the same file. Every cloud-sync service handles this safely by definition.
- **Local-first** — the SQLite index lives on each machine; `events/` is the portable source of truth. Wipe the cache anytime; `hippocamp replay` rebuilds it.

## Status

**v0.3.0 (alpha).** The architecture is stable; the surface is small enough to keep audited. Coming next: HTTP/SSE transport for self-hosted always-on stores, encrypted multi-device relay.

## License

Apache-2.0

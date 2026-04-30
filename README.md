# Hippocamp

**Memory that follows you across every AI and every machine.**

Tell Claude something on your laptop, recall it from Cursor on your desktop. Mention a preference to ChatGPT, your custom agent will know it too. Your memory is yours, runs locally, syncs everywhere.

---

## Get started in 30 seconds

```bash
pip install 'hippocamp[mcp,embeddings]'
hippocamp setup claude
```

Restart Claude Code. Try this — and watch the inline "*Saved to Hippocamp*" annotations as Claude proactively captures the signals:

> *"I'm building a Python 3.13 project with FastAPI. I prefer terse replies. By the way, hippocamps are half-horse, half-fish — and they're not hippopotamuses."*

Three saves happen automatically: a fact (Python 3.13 + FastAPI), a preference (terse replies), and a fact about hippocamps. No "remember" required.

Then in any future Claude session — even a fresh one tomorrow on a different machine — ask *"what do you know about my project?"* or *"what's a hippocamp again?"* and it'll come back with the right answer.

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

## How Claude uses your memory

Once wired up, Claude uses Hippocamp **proactively** — not just when you say "remember":

- **Saves automatically** when you state a preference, a stable fact about your project or tooling, a decision, or a notable event. Each save is announced inline (*"Saved to Hippocamp: preference (terse replies)"*) so you always know what's been captured.
- **Recalls automatically** when you reference past context.
- **Skips noise** — hypotheticals, transient debugging state, code outputs, things already in this session.

If something gets saved that you don't want, just say *"forget that"* in conversation — Claude calls the forget action. Or run `hippocamp inspect` to see everything stored.

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

hippocamp status                      # what's stored, where, by which devices

hippocamp sync                        # rebuild local cache from events
hippocamp sync <local-path>           # merge events from a file/dir, then rebuild
hippocamp sync <user@host[:path]>     # bidirectional rsync, then rebuild

hippocamp instructions                # print the directive (full)
hippocamp instructions --short        # compact version (paste into Claude Desktop / ChatGPT custom instructions)

hippocamp reindex [--embedder NAME]   # recompute embeddings (after a model swap)
```

`hippocamp sync` is one smart command — give it a local path (USB stick, downloaded folder, anything), an SSH peer (`user@desktop.local`), or no argument at all (just rebuild the cache from whatever Dropbox/iCloud/Syncthing has dropped into your events directory). Memory ends up consistent either way.

## Python library

```python
import hippocamp as hc

mem = hc.Memory(path="~/Dropbox/Hippocamp")

mem.observe("User asked whether hippocamps swim in lakes (no — saltwater only)")
mem.assert_fact("A hippocamp is half-horse, half-fish, and also a Python package")
mem.assert_preference("Strongly objects to being called a 'hippopotamus'", strength=1.0)

hits = mem.recall("am I a horse, a fish, or a hippopotamus?", limit=5)
for h in hits:
    print(h.kind, h.text, h.score, h.why.note)
```

## Make Claude prefer Hippocamp over its built-in memory

Done automatically. `hippocamp setup claude` writes a Hippocamp directive into `~/.claude/CLAUDE.md` so the assistant prefers Hippocamp over Claude Code's built-in auto-memory. The block is wrapped in `<!-- hippocamp:start -->` / `<!-- hippocamp:end -->` markers — re-running setup is idempotent, and any unrelated content in your `CLAUDE.md` is preserved.

Opt out if you want to manage instructions yourself:

```bash
hippocamp setup claude --no-instructions
```

Or also write the directive into a project-scoped `CLAUDE.md`:

```bash
hippocamp setup claude --project-instructions ~/projects/myapp
# → also writes ~/projects/myapp/CLAUDE.md with the same block
```

## Why this exists

Most AI memory today is locked: ChatGPT's memory works only in ChatGPT, on whatever device you're on. Claude Code's memory works only in Claude Code. Cloud agent-memory services (Mem0, Zep, Letta) want your data on their servers.

Hippocamp inverts that. **Your memory lives on your machine, in a directory you control, and any AI that speaks MCP can read or write it.** Switch hosts; your memory is still there. Switch laptops; your memory is still there. The lock-in disappears.

The technical wedges:

- **Tiered memory** — episodes / facts / preferences are stored separately, so retrieval can use the right semantics for each.
- **Why-trace** — every recall comes back with a breakdown of *why* the result ranked where it did (similarity + recency + kind-boost + salience).
- **First-class forgetting** — supersedence, TTL, and tombstones are features, not afterthoughts.
- **Conflict-free sync** — each device writes to `events/<device_id>.jsonl`, so no two machines ever touch the same file. Every cloud-sync service handles this safely by definition.
- **Local-first** — the SQLite index lives on each machine; `events/` is the portable source of truth. Wipe the cache anytime; `hippocamp sync` rebuilds it.

## Status

**v0.3.2 (alpha).** Architecture stable; ambient memory behaviour live (Claude saves proactively as the conversation flows, with inline announcements). Coming next: HTTP/SSE transport for self-hosted always-on stores, encrypted multi-device relay.

## License

Apache-2.0

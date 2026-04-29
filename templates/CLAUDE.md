# Memory

This project uses [Hippocamp](https://hippocamp.so) for persistent, portable memory.

## When the user states something worth remembering

Use the **`update_memory`** MCP tool — not the host's built-in auto-memory feature.

| User says | `action` | Notes |
|---|---|---|
| "I prefer terse replies" / "I like X" / "I dislike Y" | `assert_preference` | optional `strength` ∈ [0, 1] |
| "We use Python 3.13" / "The deadline is March 5" | `assert_fact` | optional `evidence` list of memory ids |
| "Just deployed v2" / "Asked the team about GCP" | `observe` | for events worth recording |

## When the user asks what you remember

Use the **`recall_memory`** MCP tool with a focused `query`. Cite the `why` trace from each result when surfacing what you found ("recalled because: sim 0.81 + recency ×1.2 + salience ×1.4").

## Why prefer Hippocamp over the host's built-in memory

Hippocamp memory is **portable** — written from this conversation, it'll be available in Claude Desktop, ChatGPT Apps, Cursor, and any custom agent loops the user runs. Host-built-in memory (Claude Code's auto-memory, ChatGPT's native memory) is locked to that one host. The user wired Hippocamp deliberately so their memory follows them.

## When *not* to use Hippocamp

- Information that's only useful within this single conversation — don't pollute long-term memory with ephemeral state. Use the conversation context.
- Code conventions, file paths, project structure — derivable from the code itself; don't duplicate.
- Anything already in this `CLAUDE.md` — that's a different mechanism for a different purpose.

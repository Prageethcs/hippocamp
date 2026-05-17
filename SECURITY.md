# Security Policy

## Reporting a vulnerability

**Please don't open public GitHub issues for security vulnerabilities.**

Use GitHub's private vulnerability reporting:

1. Go to https://github.com/Prageethcs/hippocamp/security/advisories
2. Click **Report a vulnerability**
3. Describe the issue, the impact, and (if possible) a reproduction

Hippocamp is maintained on a best-effort basis. We'll acknowledge and triage reports as quickly as we reasonably can, and credit you in the advisory and the release notes unless you'd prefer otherwise.

## Scope

Hippocamp is local-first: by design, your memory store and embeddings live on your machine, not on a server we operate. The most relevant threat models are therefore:

- **Local privilege boundary** — code that's allowed to read your home directory can read your Hippocamp store. That's not a Hippocamp vulnerability; it's the OS trust boundary.
- **MCP / IPC** — the `hippocamp-mcp` server speaks the MCP protocol over stdio with whichever AI host launched it. Unexpected behaviour from a malicious MCP host is in-scope.
- **Reflection LLM** — `reflect()` sends recent episodes to an LLM you configure. The provider's terms apply, but it's a bug if Hippocamp leaks data beyond what the user opted into.
- **Sync** — `hippocamp sync` writes JSONL files and runs `rsync` against peers you point it at. Cases where it overwrites or leaks data outside the configured sync directory are in-scope.

Code-quality issues, dependency-version concerns without an exploit, and theoretical attacks against the local trust boundary (e.g. "an attacker with shell on your laptop could read your store") are usually better filed as regular issues.

## Supported versions

Hippocamp is in alpha (0.x). Security fixes land on `main` and ship in the next release. Older 0.x versions are not patched separately.

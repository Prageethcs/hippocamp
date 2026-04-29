"""Wire Hippocamp into common AI hosts (Claude Code, Claude Desktop, Cursor, Gemini CLI).

Each setup function is idempotent: it merges a `hippocamp` entry under
the host's `mcpServers` key, never overwriting unrelated config.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class SetupResult:
    host: str
    config_path: Path | None
    action: str  # "added", "already-present", "updated", "host-cli"
    notes: str = ""


HOSTS = ("claude", "claude-desktop", "cursor", "gemini-cli")


# ---------------------------------------------------------------- path helpers


def _claude_desktop_config_path() -> Path:
    home = Path.home()
    sysname = platform.system()
    if sysname == "Darwin":
        return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if sysname == "Windows":
        return Path(os.environ.get("APPDATA", str(home))) / "Claude" / "claude_desktop_config.json"
    return home / ".config" / "Claude" / "claude_desktop_config.json"


def _cursor_config_path() -> Path:
    return Path.home() / ".cursor" / "mcp.json"


def _gemini_cli_config_path() -> Path:
    return Path.home() / ".gemini" / "settings.json"


def find_hippocamp_mcp() -> str:
    """Locate the hippocamp-mcp executable, preferring the current venv."""
    venv_bin = Path(sys.executable).parent / "hippocamp-mcp"
    if venv_bin.exists():
        return str(venv_bin)
    on_path = shutil.which("hippocamp-mcp")
    if on_path:
        return on_path
    raise RuntimeError(
        "hippocamp-mcp not found. Install with: pip install 'hippocamp[mcp]'"
    )


# ----------------------------------------------------------- generic JSON edit


def _add_mcp_entry(
    config_path: Path,
    name: str,
    command: str,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> SetupResult:
    """Idempotently add an MCP server entry to a JSON config file.

    Creates the file (and parent dirs) if missing. Preserves any existing
    config; only touches the `mcpServers.<name>` slot.
    """
    if config_path.exists():
        try:
            data: dict[str, Any] = json.loads(config_path.read_text())
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"Existing config at {config_path} is not valid JSON: {e}"
            ) from e
    else:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {}

    servers = data.setdefault("mcpServers", {})
    entry = {"command": command}
    if args:
        entry["args"] = args
    if env:
        entry["env"] = env

    if servers.get(name) == entry:
        return SetupResult(
            host=name, config_path=config_path, action="already-present"
        )

    action = "updated" if name in servers else "added"
    servers[name] = entry

    tmp = config_path.with_suffix(config_path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(config_path)

    return SetupResult(host=name, config_path=config_path, action=action)


# ------------------------------------------------------------------ per-host


def _build_env(
    path: str | None, cache_dir: str | None
) -> dict[str, str] | None:
    env: dict[str, str] = {}
    if path:
        env["HIPPOCAMP_PATH"] = path
    if cache_dir:
        env["HIPPOCAMP_CACHE_DIR"] = cache_dir
    return env or None


def setup_claude(
    *,
    command: str | None = None,
    path: str | None = None,
    cache_dir: str | None = None,
) -> SetupResult:
    """Register Hippocamp with Claude Code via `claude mcp add`.

    Uses the official `claude` CLI, which handles `~/.claude.json`
    merging safely. Fails clearly if the CLI is missing.
    """
    cli = shutil.which("claude")
    if not cli:
        raise RuntimeError(
            "claude CLI not found. Install Claude Code from https://claude.com/claude-code"
        )

    cmd = command or find_hippocamp_mcp()

    args = [cli, "mcp", "add", "-s", "user"]
    env = _build_env(path, cache_dir)
    if env:
        for key, value in env.items():
            args.extend(["-e", f"{key}={value}"])
    args.extend(["hippocamp", "--", cmd])

    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        if "already exists" in stderr.lower() or "already configured" in stderr.lower():
            return SetupResult(host="claude", config_path=None, action="already-present")
        raise RuntimeError(f"`claude mcp add` failed:\n{stderr}")

    return SetupResult(
        host="claude",
        config_path=Path.home() / ".claude.json",
        action="host-cli",
        notes=proc.stdout.strip(),
    )


def setup_claude_desktop(
    *,
    command: str | None = None,
    path: str | None = None,
    cache_dir: str | None = None,
    config_path: Path | None = None,
) -> SetupResult:
    cmd = command or find_hippocamp_mcp()
    cfg = config_path or _claude_desktop_config_path()
    res = _add_mcp_entry(cfg, "hippocamp", cmd, env=_build_env(path, cache_dir))
    res.host = "claude-desktop"
    res.notes = "Restart Claude Desktop to pick up the change."
    return res


def setup_cursor(
    *,
    command: str | None = None,
    path: str | None = None,
    cache_dir: str | None = None,
    config_path: Path | None = None,
) -> SetupResult:
    cmd = command or find_hippocamp_mcp()
    cfg = config_path or _cursor_config_path()
    res = _add_mcp_entry(cfg, "hippocamp", cmd, env=_build_env(path, cache_dir))
    res.host = "cursor"
    res.notes = "Restart Cursor or reload the MCP server list."
    return res


def setup_gemini_cli(
    *,
    command: str | None = None,
    path: str | None = None,
    cache_dir: str | None = None,
    config_path: Path | None = None,
) -> SetupResult:
    cmd = command or find_hippocamp_mcp()
    cfg = config_path or _gemini_cli_config_path()
    res = _add_mcp_entry(cfg, "hippocamp", cmd, env=_build_env(path, cache_dir))
    res.host = "gemini-cli"
    res.notes = "Restart gemini-cli to pick up the change."
    return res


SETUP_FUNCS = {
    "claude": setup_claude,
    "claude-desktop": setup_claude_desktop,
    "cursor": setup_cursor,
    "gemini-cli": setup_gemini_cli,
}

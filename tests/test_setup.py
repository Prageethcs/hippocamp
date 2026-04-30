"""Tests for the per-host setup logic.

All tests use temp paths so the user's actual config files are never
touched. The Claude Code setup uses the `claude` CLI directly and is
skipped here; it's covered by manual integration testing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hippocamp.setup import (
    _add_mcp_entry,
    setup_claude_desktop,
    setup_cursor,
    setup_gemini_cli,
)


def _read(path: Path) -> dict:
    return json.loads(path.read_text())


def test_add_creates_new_config(tmp_path):
    cfg = tmp_path / "config.json"
    res = _add_mcp_entry(cfg, "hippocamp", "/usr/local/bin/hippocamp-mcp")

    assert cfg.exists()
    assert res.action == "added"
    data = _read(cfg)
    assert data["mcpServers"]["hippocamp"] == {
        "command": "/usr/local/bin/hippocamp-mcp"
    }


def test_add_preserves_unrelated_keys(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "theme": "dark",
        "mcpServers": {"sentry": {"command": "sentry-mcp"}},
    }))

    _add_mcp_entry(cfg, "hippocamp", "/x/hippocamp-mcp")

    data = _read(cfg)
    assert data["theme"] == "dark"
    assert "sentry" in data["mcpServers"]
    assert "hippocamp" in data["mcpServers"]


def test_add_is_idempotent(tmp_path):
    cfg = tmp_path / "config.json"
    _add_mcp_entry(cfg, "hippocamp", "/x/hippocamp-mcp")

    res = _add_mcp_entry(cfg, "hippocamp", "/x/hippocamp-mcp")
    assert res.action == "already-present"


def test_add_updates_when_command_differs(tmp_path):
    cfg = tmp_path / "config.json"
    _add_mcp_entry(cfg, "hippocamp", "/old/hippocamp-mcp")

    res = _add_mcp_entry(cfg, "hippocamp", "/new/hippocamp-mcp")
    assert res.action == "updated"
    data = _read(cfg)
    assert data["mcpServers"]["hippocamp"]["command"] == "/new/hippocamp-mcp"


def test_add_rejects_invalid_json(tmp_path):
    cfg = tmp_path / "broken.json"
    cfg.write_text("{not valid json")

    with pytest.raises(RuntimeError, match="not valid JSON"):
        _add_mcp_entry(cfg, "hippocamp", "/x/hippocamp-mcp")


def test_setup_claude_desktop_writes_to_given_path(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    res = setup_claude_desktop(
        command="/x/hippocamp-mcp", config_path=cfg
    )
    assert res.host == "claude-desktop"
    assert res.action == "added"
    assert "Restart Claude Desktop" in res.notes
    data = _read(cfg)
    assert data["mcpServers"]["hippocamp"]["command"] == "/x/hippocamp-mcp"


def test_setup_cursor_writes_to_given_path(tmp_path):
    cfg = tmp_path / "mcp.json"
    res = setup_cursor(command="/x/hippocamp-mcp", config_path=cfg)
    assert res.host == "cursor"
    assert res.action == "added"
    assert _read(cfg)["mcpServers"]["hippocamp"]["command"] == "/x/hippocamp-mcp"


def test_setup_gemini_cli_writes_to_given_path(tmp_path):
    cfg = tmp_path / "settings.json"
    res = setup_gemini_cli(command="/x/hippocamp-mcp", config_path=cfg)
    assert res.host == "gemini-cli"
    assert res.action == "added"
    assert _read(cfg)["mcpServers"]["hippocamp"]["command"] == "/x/hippocamp-mcp"


def test_setup_creates_parent_dirs(tmp_path):
    cfg = tmp_path / "deeply" / "nested" / "path" / "config.json"
    setup_cursor(command="/x/hippocamp-mcp", config_path=cfg)
    assert cfg.exists()


def test_setup_passes_path_and_cache_dir_via_env(tmp_path):
    """The cloud-sync setup: --path and --cache-dir become host env vars."""
    cfg = tmp_path / "mcp.json"
    setup_cursor(
        command="/x/hippocamp-mcp",
        path="/Users/me/Dropbox/Hippocamp",
        cache_dir="/Users/me/.cache/hippocamp",
        config_path=cfg,
    )
    data = _read(cfg)
    entry = data["mcpServers"]["hippocamp"]
    assert entry["env"]["HIPPOCAMP_PATH"] == "/Users/me/Dropbox/Hippocamp"
    assert entry["env"]["HIPPOCAMP_CACHE_DIR"] == "/Users/me/.cache/hippocamp"


def test_setup_without_path_omits_env_block(tmp_path):
    """No --path/--cache-dir → no env block (inherit from parent shell)."""
    cfg = tmp_path / "mcp.json"
    setup_cursor(command="/x/hippocamp-mcp", config_path=cfg)
    entry = _read(cfg)["mcpServers"]["hippocamp"]
    assert "env" not in entry


def test_setup_claude_writes_user_instructions(monkeypatch, tmp_path):
    """Default behaviour: setup_claude appends to ~/.claude/CLAUDE.md."""
    from hippocamp import setup as setup_mod
    from hippocamp import instructions as instr_mod

    fake_home_md = tmp_path / "claude" / "CLAUDE.md"

    class FakeProc:
        returncode = 0
        stdout = "Added stdio MCP server"
        stderr = ""

    monkeypatch.setattr(setup_mod.shutil, "which", lambda n: "/usr/bin/claude" if n == "claude" else None)
    monkeypatch.setattr(setup_mod.subprocess, "run", lambda *a, **k: FakeProc())
    monkeypatch.setattr(setup_mod, "find_hippocamp_mcp", lambda: "/path/to/hippocamp-mcp")
    monkeypatch.setattr(setup_mod, "claude_user_md_path", lambda: fake_home_md)
    monkeypatch.setattr(instr_mod, "claude_user_md_path", lambda: fake_home_md)

    setup_mod.setup_claude()

    assert fake_home_md.exists()
    assert "Hippocamp memory" in fake_home_md.read_text()


def test_setup_claude_no_instructions_skips(monkeypatch, tmp_path):
    """Opt-out flag: install_instructions=False leaves CLAUDE.md alone."""
    from hippocamp import setup as setup_mod
    from hippocamp import instructions as instr_mod

    fake_home_md = tmp_path / "claude" / "CLAUDE.md"

    class FakeProc:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(setup_mod.shutil, "which", lambda n: "/usr/bin/claude" if n == "claude" else None)
    monkeypatch.setattr(setup_mod.subprocess, "run", lambda *a, **k: FakeProc())
    monkeypatch.setattr(setup_mod, "find_hippocamp_mcp", lambda: "/path/to/hippocamp-mcp")
    monkeypatch.setattr(setup_mod, "claude_user_md_path", lambda: fake_home_md)
    monkeypatch.setattr(instr_mod, "claude_user_md_path", lambda: fake_home_md)

    setup_mod.setup_claude(install_instructions=False)

    assert not fake_home_md.exists()


def test_setup_claude_writes_project_instructions(monkeypatch, tmp_path):
    """`project_instructions_dir` writes a CLAUDE.md inside that dir."""
    from hippocamp import setup as setup_mod
    from hippocamp import instructions as instr_mod

    fake_home_md = tmp_path / "claude" / "CLAUDE.md"
    project_dir = tmp_path / "myproject"
    project_dir.mkdir()

    class FakeProc:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(setup_mod.shutil, "which", lambda n: "/usr/bin/claude" if n == "claude" else None)
    monkeypatch.setattr(setup_mod.subprocess, "run", lambda *a, **k: FakeProc())
    monkeypatch.setattr(setup_mod, "find_hippocamp_mcp", lambda: "/path/to/hippocamp-mcp")
    monkeypatch.setattr(setup_mod, "claude_user_md_path", lambda: fake_home_md)
    monkeypatch.setattr(instr_mod, "claude_user_md_path", lambda: fake_home_md)

    setup_mod.setup_claude(
        install_instructions=False,
        project_instructions_dir=project_dir,
    )

    project_md = project_dir / "CLAUDE.md"
    assert project_md.exists()
    assert "Hippocamp memory" in project_md.read_text()


def test_setup_claude_uses_attached_env_form(monkeypatch):
    """Regression: `claude mcp add` treats -e as variadic and would
    otherwise consume the server-name positional. We must use the
    attached-value form `--env=KEY=VAL` so the flag and value are a
    single argv token.
    """
    from hippocamp import setup as setup_mod

    captured: list[list[str]] = []

    class FakeProc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_which(name):
        return "/usr/bin/claude" if name == "claude" else None

    def fake_run(args, **kwargs):
        captured.append(list(args))
        return FakeProc()

    monkeypatch.setattr(setup_mod.shutil, "which", fake_which)
    monkeypatch.setattr(setup_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(setup_mod, "find_hippocamp_mcp", lambda: "/path/to/hippocamp-mcp")

    setup_mod.setup_claude(path="/tmp/foo", cache_dir="/tmp/bar")

    assert len(captured) == 1
    args = captured[0]
    # Bug repro: bare `-e` as a separate token would have shown up here
    assert "-e" not in args, f"bare -e leaked into args: {args}"
    # Both env vars present in the attached form
    assert "--env=HIPPOCAMP_PATH=/tmp/foo" in args
    assert "--env=HIPPOCAMP_CACHE_DIR=/tmp/bar" in args
    # Server name and command still at the expected positions
    assert "hippocamp" in args
    assert "/path/to/hippocamp-mcp" in args
    # The `--` separator before the command is preserved
    assert args.index("--") < args.index("/path/to/hippocamp-mcp")

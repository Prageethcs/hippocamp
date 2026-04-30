"""Tests for the CLAUDE.md instruction block management."""

from __future__ import annotations

from pathlib import Path

from hippocamp.instructions import (
    END_MARKER,
    INSTRUCTIONS,
    START_MARKER,
    install_or_update,
    remove_block,
)


def test_creates_when_file_missing(tmp_path):
    p = tmp_path / "deeply" / "nested" / "CLAUDE.md"
    action = install_or_update(p)
    assert action == "created"
    text = p.read_text()
    assert START_MARKER in text
    assert END_MARKER in text
    assert "Hippocamp memory" in text


def test_appends_to_existing_unrelated_content(tmp_path):
    p = tmp_path / "CLAUDE.md"
    p.write_text("# My personal notes\n\nDo not edit this section.\n")
    action = install_or_update(p)
    assert action == "appended"
    text = p.read_text()
    # User's content preserved verbatim
    assert "My personal notes" in text
    assert "Do not edit this section." in text
    # Block appended below
    assert START_MARKER in text
    assert text.index("personal notes") < text.index(START_MARKER)


def test_idempotent_on_second_run(tmp_path):
    p = tmp_path / "CLAUDE.md"
    install_or_update(p)
    action = install_or_update(p)
    assert action == "unchanged"
    # Single occurrence of each marker
    text = p.read_text()
    assert text.count(START_MARKER) == 1
    assert text.count(END_MARKER) == 1


def test_refreshes_when_block_content_drifts(tmp_path):
    p = tmp_path / "CLAUDE.md"
    p.write_text(f"{START_MARKER}\nold v0.0.1 directive\n{END_MARKER}\n")
    action = install_or_update(p)
    assert action == "updated"
    text = p.read_text()
    assert "old v0.0.1 directive" not in text
    assert "Hippocamp memory" in text


def test_preserves_content_around_block(tmp_path):
    p = tmp_path / "CLAUDE.md"
    p.write_text(
        f"# My notes\n\nIntro paragraph.\n\n"
        f"{START_MARKER}\nold content\n{END_MARKER}\n\n"
        f"# Footer\nMy own rules below.\n"
    )
    install_or_update(p)
    text = p.read_text()
    assert "My notes" in text
    assert "Intro paragraph." in text
    assert "Footer" in text
    assert "My own rules below." in text
    assert "old content" not in text


def test_remove_block_when_present(tmp_path):
    p = tmp_path / "CLAUDE.md"
    p.write_text(
        f"# Notes\n\n{START_MARKER}\nblock\n{END_MARKER}\n\n# After\n"
    )
    action = remove_block(p)
    assert action == "removed"
    text = p.read_text()
    assert START_MARKER not in text
    assert END_MARKER not in text
    assert "# Notes" in text
    assert "# After" in text


def test_remove_block_when_absent(tmp_path):
    p = tmp_path / "CLAUDE.md"
    p.write_text("# Notes\n\nNo Hippocamp block here.\n")
    action = remove_block(p)
    assert action == "absent"
    assert "# Notes" in p.read_text()


def test_remove_block_when_file_missing(tmp_path):
    p = tmp_path / "missing.md"
    action = remove_block(p)
    assert action == "file-missing"


def test_get_instructions_full_has_no_markers():
    from hippocamp.instructions import get_instructions

    text = get_instructions()
    assert START_MARKER not in text
    assert END_MARKER not in text
    assert "Hippocamp memory" in text


def test_get_instructions_short_is_compact():
    from hippocamp.instructions import get_instructions

    full = get_instructions(short=False)
    short = get_instructions(short=True)

    assert "Hippocamp" in short
    assert "recall_memory" in short
    # Compact: meaningfully shorter
    assert len(short) < len(full) // 2


def test_get_instructions_short_has_no_markers_either():
    from hippocamp.instructions import get_instructions

    text = get_instructions(short=True)
    assert START_MARKER not in text
    assert END_MARKER not in text

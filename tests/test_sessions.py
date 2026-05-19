from pathlib import Path

import pytest

from aque.sessions import CAPTURERS, ClaudeCapturer


def test_claude_session_dir_slug(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    c = ClaudeCapturer()
    assert c.session_dir("/Users/me/code/api") == \
        tmp_path / ".claude" / "projects" / "-Users-me-code-api"


def test_claude_existing_uuids_missing_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    c = ClaudeCapturer()
    assert c.existing_uuids("/Users/me/code/api") == set()


def test_claude_existing_uuids_empty_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / ".claude" / "projects" / "-Users-me-code-api"
    target.mkdir(parents=True)
    c = ClaudeCapturer()
    assert c.existing_uuids("/Users/me/code/api") == set()


def test_claude_existing_uuids_picks_up_jsonl(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / ".claude" / "projects" / "-Users-me-code-api"
    target.mkdir(parents=True)
    (target / "uuid-1.jsonl").write_text("")
    (target / "uuid-2.jsonl").write_text("")
    (target / "ignore.txt").write_text("")
    c = ClaudeCapturer()
    assert c.existing_uuids("/Users/me/code/api") == {"uuid-1", "uuid-2"}


def test_claude_resume_command_appends_flag():
    c = ClaudeCapturer()
    cmd = ["claude", "--model", "opus"]
    out = c.resume_command(cmd, "uuid-1")
    assert out == ["claude", "--model", "opus", "--resume", "uuid-1"]
    # input not mutated
    assert cmd == ["claude", "--model", "opus"]


def test_claude_in_registry():
    assert "claude" in CAPTURERS
    assert isinstance(CAPTURERS["claude"], ClaudeCapturer)

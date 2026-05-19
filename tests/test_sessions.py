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


def test_codex_session_dir_root(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from aque.sessions import CodexCapturer
    c = CodexCapturer()
    assert c.session_dir("/any/cwd") == tmp_path / ".codex" / "sessions"


def test_codex_existing_uuids_extracts_uuid_from_filename(monkeypatch, tmp_path):
    """Codex filenames look like rollout-<timestamp>-<uuid>.jsonl.
    The UUID is the last 5 hyphen-separated tokens of the stem.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    today_dir = tmp_path / ".codex" / "sessions" / "2026" / "05" / "18"
    today_dir.mkdir(parents=True)
    (today_dir / "rollout-2026-05-18T10-00-00-aaaa1111-bbbb-cccc-dddd-eeeeffff0000.jsonl").write_text("")
    (today_dir / "rollout-2026-05-18T11-00-00-aaaa2222-bbbb-cccc-dddd-eeeeffff1111.jsonl").write_text("")
    yesterday_dir = tmp_path / ".codex" / "sessions" / "2026" / "05" / "17"
    yesterday_dir.mkdir(parents=True)
    (yesterday_dir / "rollout-2026-05-17T10-00-00-aaaa3333-bbbb-cccc-dddd-eeeeffff2222.jsonl").write_text("")

    from aque.sessions import CodexCapturer
    c = CodexCapturer()
    assert c.existing_uuids("/any/cwd") == {
        "aaaa1111-bbbb-cccc-dddd-eeeeffff0000",
        "aaaa2222-bbbb-cccc-dddd-eeeeffff1111",
        "aaaa3333-bbbb-cccc-dddd-eeeeffff2222",
    }


def test_codex_existing_uuids_missing_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from aque.sessions import CodexCapturer
    c = CodexCapturer()
    assert c.existing_uuids("/any/cwd") == set()


def test_codex_existing_uuids_skips_malformed_filenames(monkeypatch, tmp_path):
    """Files whose stems have fewer than 6 hyphen-separated tokens are skipped
    (not enough parts to contain a UUID after the rollout/date prefix)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    d = tmp_path / ".codex" / "sessions" / "2026" / "05" / "18"
    d.mkdir(parents=True)
    (d / "short.jsonl").write_text("")  # 1 token — skipped
    (d / "rollout-2026-05-18T10-00-00-aaaa-bbbb-cccc-dddd-eeee.jsonl").write_text("")  # 11 tokens, valid

    from aque.sessions import CodexCapturer
    c = CodexCapturer()
    assert c.existing_uuids("/any/cwd") == {"aaaa-bbbb-cccc-dddd-eeee"}


def test_codex_resume_command():
    from aque.sessions import CodexCapturer
    c = CodexCapturer()
    out = c.resume_command(["codex"], "uuid-a")
    assert out == ["codex", "resume", "uuid-a"]


def test_codex_resume_command_with_extra_args():
    """Codex resume injects 'resume <id>' as the first positional after
    'codex', preserving any flags the user originally passed."""
    from aque.sessions import CodexCapturer
    c = CodexCapturer()
    out = c.resume_command(["codex", "--profile", "work"], "uuid-a")
    assert out == ["codex", "resume", "uuid-a", "--profile", "work"]


def test_codex_in_registry():
    from aque.sessions import CAPTURERS, CodexCapturer
    assert "codex" in CAPTURERS
    assert isinstance(CAPTURERS["codex"], CodexCapturer)

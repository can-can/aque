from pathlib import Path

import pytest

from aque.sessions import CAPTURERS, ClaudeCapturer, _read_last_line


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


class TestReadLastLine:
    def test_returns_none_for_missing_file(self, tmp_path):
        assert _read_last_line(tmp_path / "nope.jsonl") is None

    def test_returns_none_for_empty_file(self, tmp_path):
        p = tmp_path / "f.jsonl"
        p.write_text("")
        assert _read_last_line(p) is None

    def test_returns_only_line_when_single_line(self, tmp_path):
        p = tmp_path / "f.jsonl"
        p.write_text("alpha\n")
        assert _read_last_line(p) == "alpha"

    def test_returns_last_line_when_multiline(self, tmp_path):
        p = tmp_path / "f.jsonl"
        p.write_text("alpha\nbeta\ngamma\n")
        assert _read_last_line(p) == "gamma"

    def test_handles_missing_trailing_newline(self, tmp_path):
        p = tmp_path / "f.jsonl"
        p.write_text("alpha\nbeta")
        assert _read_last_line(p) == "beta"

    def test_handles_file_larger_than_window(self, tmp_path):
        p = tmp_path / "f.jsonl"
        # Write 20 KB so we definitely exceed an 8 KB window.
        lines = [f"line-{i:05d}" for i in range(2000)]
        p.write_text("\n".join(lines) + "\n")
        assert _read_last_line(p) == "line-01999"

    def test_handles_last_line_longer_than_window(self, tmp_path):
        # Last line is bigger than the window; helper should grow.
        p = tmp_path / "f.jsonl"
        long_line = "x" * 20000
        p.write_text(f"short\n{long_line}\n")
        assert _read_last_line(p) == long_line

    def test_strips_windows_crlf_line_endings(self, tmp_path):
        p = tmp_path / "f.jsonl"
        p.write_bytes(b"alpha\r\nbeta\r\n")
        assert _read_last_line(p) == "beta"

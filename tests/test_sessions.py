import json
import os
import uuid as uuid_mod
from pathlib import Path

import pytest

from aque.plugins import claude
from aque.sessions import _read_last_line, _read_last_user_or_assistant


def test_claude_session_dir_slug(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert claude._session_dir("/Users/me/code/api") == \
        tmp_path / ".claude" / "projects" / "-Users-me-code-api"


def test_claude_existing_uuids_missing_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert claude.existing_uuids("/Users/me/code/api") == set()


def test_claude_existing_uuids_empty_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / ".claude" / "projects" / "-Users-me-code-api"
    target.mkdir(parents=True)
    assert claude.existing_uuids("/Users/me/code/api") == set()


def test_claude_existing_uuids_picks_up_jsonl(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / ".claude" / "projects" / "-Users-me-code-api"
    target.mkdir(parents=True)
    (target / "uuid-1.jsonl").write_text("")
    (target / "uuid-2.jsonl").write_text("")
    (target / "ignore.txt").write_text("")
    assert claude.existing_uuids("/Users/me/code/api") == {"uuid-1", "uuid-2"}


def test_claude_resume_command_appends_flag():
    cmd = ["claude", "--model", "opus"]
    out = claude.resume_command(cmd, "uuid-1")
    assert out == ["claude", "--model", "opus", "--resume", "uuid-1"]
    # input not mutated
    assert cmd == ["claude", "--model", "opus"]


def test_claude_resume_command_rewrites_preassigned_session_id():
    """The stored launch command carries the preassigned --session-id. To
    resume, claude needs --resume <uuid> instead (--session-id re-creates the
    session and errors when it already exists), so resume_command drops the
    preassigned flag and appends --resume."""
    cmd = ["claude", "--session-id", "preassigned-uuid"]
    out = claude.resume_command(cmd, "preassigned-uuid")
    assert out == ["claude", "--resume", "preassigned-uuid"]
    assert "--session-id" not in out
    # input not mutated
    assert cmd == ["claude", "--session-id", "preassigned-uuid"]


def test_claude_resume_command_is_idempotent_across_repeats():
    """Resuming an already-resumed command must not stack duplicate flags."""
    cmd = ["claude", "--resume", "uuid-1"]
    out = claude.resume_command(cmd, "uuid-1")
    assert out == ["claude", "--resume", "uuid-1"]


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


class TestClaudePreassign:
    def test_appends_session_id_flag(self):
        cmd, sid = claude.preassign(["claude", "--model", "opus"])
        assert cmd[:3] == ["claude", "--model", "opus"]
        assert cmd[3] == "--session-id"
        assert cmd[4] == sid

    def test_generated_uuid_is_valid_v4(self):
        _, sid = claude.preassign(["claude"])
        parsed = uuid_mod.UUID(sid)
        assert parsed.version == 4

    def test_each_call_yields_a_different_uuid(self):
        ids = {claude.preassign(["claude"])[1] for _ in range(10)}
        assert len(ids) == 10

    def test_does_not_mutate_input_list(self):
        cmd_in = ["claude"]
        claude.preassign(cmd_in)
        assert cmd_in == ["claude"]


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")


class TestClaudeSummarize:
    def test_returns_empty_when_dir_missing(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        assert claude.summarize("/tmp/no-such-dir") == []

    def test_returns_empty_when_dir_has_no_jsonl(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / ".claude" / "projects" / "-tmp-x").mkdir(parents=True)
        assert claude.summarize("/tmp/x") == []

    def test_skips_meta_first_user_entry(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        d = tmp_path / ".claude" / "projects" / "-tmp-x"
        d.mkdir(parents=True)
        _write_jsonl(d / "aaaa.jsonl", [
            {"type": "file-history-snapshot"},
            {"type": "user", "isMeta": True,
             "message": {"role": "user",
                         "content": "<local-command-caveat>x</local-command-caveat>"}},
            {"type": "user",
             "message": {"role": "user", "content": "real first prompt here"}},
            {"type": "assistant",
             "message": {"role": "assistant", "content": "real last reply here"}},
        ])
        out = claude.summarize("/tmp/x")
        assert len(out) == 1
        assert out[0].first_prompt == "real first prompt here"
        assert out[0].last_activity == "real last reply here"

    def test_handles_list_content_blocks(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        d = tmp_path / ".claude" / "projects" / "-tmp-x"
        d.mkdir(parents=True)
        _write_jsonl(d / "bbbb.jsonl", [
            {"type": "user",
             "message": {"role": "user",
                         "content": [{"type": "text", "text": "block-style prompt"}]}},
            {"type": "assistant",
             "message": {"role": "assistant",
                         "content": [{"type": "text", "text": "block-style reply"}]}},
        ])
        out = claude.summarize("/tmp/x")
        assert out[0].first_prompt == "block-style prompt"
        assert out[0].last_activity == "block-style reply"

    def test_truncates_long_text(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        d = tmp_path / ".claude" / "projects" / "-tmp-x"
        d.mkdir(parents=True)
        long = "z" * 200
        _write_jsonl(d / "cccc.jsonl", [
            {"type": "user", "message": {"role": "user", "content": long}},
        ])
        out = claude.summarize("/tmp/x")
        assert len(out[0].first_prompt) <= 81  # 80 chars + ellipsis
        assert out[0].first_prompt.endswith("…")

    def test_sorts_newest_first_by_mtime(self, monkeypatch, tmp_path):
        import time
        monkeypatch.setenv("HOME", str(tmp_path))
        d = tmp_path / ".claude" / "projects" / "-tmp-x"
        d.mkdir(parents=True)
        for name in ("aaaa.jsonl", "bbbb.jsonl", "cccc.jsonl"):
            _write_jsonl(d / name, [
                {"type": "user",
                 "message": {"role": "user", "content": f"prompt-{name}"}}
            ])
        # Force distinct mtimes: aaaa oldest, cccc newest.
        now = time.time()
        os.utime(d / "aaaa.jsonl", (now - 300, now - 300))
        os.utime(d / "bbbb.jsonl", (now - 100, now - 100))
        os.utime(d / "cccc.jsonl", (now, now))
        out = claude.summarize("/tmp/x")
        assert [s.uuid for s in out] == ["cccc", "bbbb", "aaaa"]

    def test_last_activity_survives_trailing_system_entries(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        d = tmp_path / ".claude" / "projects" / "-tmp-x"
        d.mkdir(parents=True)
        _write_jsonl(d / "eeee.jsonl", [
            {"type": "user", "message": {"role": "user", "content": "first prompt"}},
            {"type": "assistant", "message": {"role": "assistant", "content": "the last real reply"}},
            {"type": "system", "subtype": "turn_duration"},
            {"type": "attachment", "attachment": {"type": "task_reminder", "content": []}},
        ])
        out = claude.summarize("/tmp/x")
        assert len(out) == 1
        assert out[0].first_prompt == "first prompt"
        assert out[0].last_activity == "the last real reply"

    def test_handles_corrupt_jsonl_gracefully(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        d = tmp_path / ".claude" / "projects" / "-tmp-x"
        d.mkdir(parents=True)
        (d / "dddd.jsonl").write_bytes(b"not json at all\xff\xfe\n")
        out = claude.summarize("/tmp/x")
        # Corrupt file shows up but with None previews.
        assert len(out) == 1
        assert out[0].uuid == "dddd"
        assert out[0].first_prompt is None
        assert out[0].last_activity is None


class TestReadLastUserOrAssistant:
    def test_returns_none_for_missing_file(self, tmp_path):
        assert _read_last_user_or_assistant(tmp_path / "missing.jsonl") == (None, None)

    def test_returns_last_assistant_even_with_trailing_system_entries(self, tmp_path):
        p = tmp_path / "f.jsonl"
        _write_jsonl(p, [
            {"type": "user", "message": {"role": "user", "content": "old prompt"}},
            {"type": "assistant", "message": {"role": "assistant", "content": "real last reply"}},
            {"type": "system", "subtype": "turn_duration"},
            {"type": "attachment", "attachment": {"type": "task_reminder", "content": []}},
        ])
        text, role = _read_last_user_or_assistant(p)
        assert text == "real last reply"
        assert role == "assistant"

    def test_returns_last_user_when_no_assistant_after(self, tmp_path):
        p = tmp_path / "f.jsonl"
        _write_jsonl(p, [
            {"type": "assistant", "message": {"role": "assistant", "content": "old reply"}},
            {"type": "user", "message": {"role": "user", "content": "newer prompt"}},
            {"type": "system", "subtype": "away_summary"},
        ])
        text, role = _read_last_user_or_assistant(p)
        assert text == "newer prompt"
        assert role == "user"

    def test_returns_none_when_no_user_or_assistant_in_window(self, tmp_path):
        p = tmp_path / "f.jsonl"
        _write_jsonl(p, [
            {"type": "system", "subtype": "x"},
            {"type": "attachment"},
        ])
        assert _read_last_user_or_assistant(p) == (None, None)

    def test_skips_meta_user_entries(self, tmp_path):
        p = tmp_path / "f.jsonl"
        _write_jsonl(p, [
            {"type": "user", "message": {"role": "user", "content": "real one"}},
            {"type": "user", "isMeta": True,
             "message": {"role": "user", "content": "<local-command-caveat>x</local-command-caveat>"}},
        ])
        text, role = _read_last_user_or_assistant(p)
        assert text == "real one"
        assert role == "user"



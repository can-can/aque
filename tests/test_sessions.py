import json
import os
import uuid as uuid_mod
from pathlib import Path

import pytest

from aque.sessions import CAPTURERS, ClaudeCapturer, CodexCapturer, _read_last_line, _read_last_user_or_assistant


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


class TestClaudePreassign:
    def test_appends_session_id_flag(self):
        c = ClaudeCapturer()
        cmd, sid = c.preassign(["claude", "--model", "opus"])
        assert cmd[:3] == ["claude", "--model", "opus"]
        assert cmd[3] == "--session-id"
        assert cmd[4] == sid

    def test_generated_uuid_is_valid_v4(self):
        c = ClaudeCapturer()
        _, sid = c.preassign(["claude"])
        parsed = uuid_mod.UUID(sid)
        assert parsed.version == 4

    def test_each_call_yields_a_different_uuid(self):
        c = ClaudeCapturer()
        ids = {c.preassign(["claude"])[1] for _ in range(10)}
        assert len(ids) == 10

    def test_does_not_mutate_input_list(self):
        c = ClaudeCapturer()
        cmd_in = ["claude"]
        c.preassign(cmd_in)
        assert cmd_in == ["claude"]


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")


class TestClaudeSummarize:
    def test_returns_empty_when_dir_missing(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        assert ClaudeCapturer().summarize("/tmp/no-such-dir") == []

    def test_returns_empty_when_dir_has_no_jsonl(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / ".claude" / "projects" / "-tmp-x").mkdir(parents=True)
        assert ClaudeCapturer().summarize("/tmp/x") == []

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
        out = ClaudeCapturer().summarize("/tmp/x")
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
        out = ClaudeCapturer().summarize("/tmp/x")
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
        out = ClaudeCapturer().summarize("/tmp/x")
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
        out = ClaudeCapturer().summarize("/tmp/x")
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
        out = ClaudeCapturer().summarize("/tmp/x")
        assert len(out) == 1
        assert out[0].first_prompt == "first prompt"
        assert out[0].last_activity == "the last real reply"

    def test_handles_corrupt_jsonl_gracefully(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        d = tmp_path / ".claude" / "projects" / "-tmp-x"
        d.mkdir(parents=True)
        (d / "dddd.jsonl").write_bytes(b"not json at all\xff\xfe\n")
        out = ClaudeCapturer().summarize("/tmp/x")
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


class TestCodexStubs:
    def test_preassign_returns_none(self):
        assert CodexCapturer().preassign(["codex"]) is None

    def test_summarize_returns_empty_list(self, tmp_path):
        assert CodexCapturer().summarize("/tmp/x") == []


class TestCodexExistingUuids:
    def test_picks_up_uuid_from_rollout_file(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        d = tmp_path / ".codex" / "sessions" / "2026" / "05" / "24"
        d.mkdir(parents=True)
        uuid = "019e5b51-3ff5-7c43-bd69-ef8dfdd9bd84"
        (d / f"rollout-2026-05-24T11-48-31-{uuid}.jsonl").write_text("")
        assert uuid in CodexCapturer().existing_uuids("/tmp/x")

    def test_picks_up_uuid_from_shell_snapshot(self, monkeypatch, tmp_path):
        """shell_snapshots/<uuid>.<ts>.sh appears BEFORE the rollout file —
        codex writes it within seconds of session init, well before the user
        submits any prompt. Capturer must pick it up to avoid stalling on
        idle codex sessions."""
        monkeypatch.setenv("HOME", str(tmp_path))
        d = tmp_path / ".codex" / "shell_snapshots"
        d.mkdir(parents=True)
        uuid = "019e5b60-3288-76d1-a7c5-820fa6ad161e"
        (d / f"{uuid}.1779649491861955000.sh").write_text("# snapshot")
        assert uuid in CodexCapturer().existing_uuids("/tmp/x")

    def test_unions_uuids_from_both_locations(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        sessions_d = tmp_path / ".codex" / "sessions" / "2026" / "05" / "24"
        sessions_d.mkdir(parents=True)
        rollout_uuid = "019e5b51-3ff5-7c43-bd69-ef8dfdd9bd84"
        (sessions_d / f"rollout-2026-05-24T11-48-31-{rollout_uuid}.jsonl").write_text("")
        snapshots_d = tmp_path / ".codex" / "shell_snapshots"
        snapshots_d.mkdir(parents=True)
        snapshot_uuid = "019e5b60-3288-76d1-a7c5-820fa6ad161e"
        (snapshots_d / f"{snapshot_uuid}.1779649491861955000.sh").write_text("")
        uuids = CodexCapturer().existing_uuids("/tmp/x")
        assert rollout_uuid in uuids
        assert snapshot_uuid in uuids

    def test_ignores_unrelated_files_in_shell_snapshots(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        d = tmp_path / ".codex" / "shell_snapshots"
        d.mkdir(parents=True)
        (d / "not-a-uuid.sh").write_text("")
        (d / "README.sh").write_text("")
        assert CodexCapturer().existing_uuids("/tmp/x") == set()

"""Tests for DirHistoryManager — directory usage history persistence layer."""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from aque.dir_history import DirHistoryManager


@pytest.fixture
def mgr(tmp_aque_dir):
    """DirHistoryManager backed by a temporary directory."""
    return DirHistoryManager(tmp_aque_dir)


# ---------------------------------------------------------------------------
# TestDirHistoryLoad
# ---------------------------------------------------------------------------


class TestDirHistoryLoad:
    def test_load_empty_returns_defaults(self, mgr):
        """When no file exists, _load_raw returns empty pinned/history."""
        data = mgr._load_raw()
        assert data == {"pinned": [], "history": []}

    def test_load_existing_data(self, mgr, tmp_aque_dir, tmp_path):
        """When file exists with data, _load_raw returns it (pruning missing dirs)."""
        real_dir = tmp_path / "real_project"
        real_dir.mkdir()
        payload = {
            "pinned": [str(real_dir)],
            "history": [
                {"path": str(real_dir), "count": 3, "last_used": "2026-03-28T10:00:00"},
            ],
        }
        (tmp_aque_dir / "dir_history.json").write_text(json.dumps(payload))

        data = mgr._load_raw()
        assert data["pinned"] == [str(real_dir)]
        assert len(data["history"]) == 1
        assert data["history"][0]["count"] == 3

    def test_load_prunes_nonexistent_dirs(self, mgr, tmp_aque_dir):
        """Directories that no longer exist on disk are cleaned out."""
        payload = {
            "pinned": ["/no/such/path/abc123"],
            "history": [
                {"path": "/no/such/path/abc123", "count": 5, "last_used": "2026-03-28T10:00:00"},
            ],
        }
        (tmp_aque_dir / "dir_history.json").write_text(json.dumps(payload))

        data = mgr._load_raw()
        assert data["pinned"] == []
        assert data["history"] == []


# ---------------------------------------------------------------------------
# TestDirHistoryRecordUse
# ---------------------------------------------------------------------------


class TestDirHistoryRecordUse:
    def test_record_new_dir(self, mgr, tmp_path):
        """Recording a new directory creates an entry with count=1."""
        d = tmp_path / "project_a"
        d.mkdir()
        mgr.record_use(str(d))

        data = mgr._load_raw()
        assert len(data["history"]) == 1
        assert data["history"][0]["path"] == str(d.resolve())
        assert data["history"][0]["count"] == 1

    def test_record_increments_count(self, mgr, tmp_path):
        """Recording the same directory again increments its count."""
        d = tmp_path / "project_b"
        d.mkdir()
        mgr.record_use(str(d))
        mgr.record_use(str(d))
        mgr.record_use(str(d))

        data = mgr._load_raw()
        assert len(data["history"]) == 1
        assert data["history"][0]["count"] == 3

    def test_record_updates_last_used(self, mgr, tmp_path):
        """Each record_use updates the last_used timestamp."""
        d = tmp_path / "project_c"
        d.mkdir()
        mgr.record_use(str(d))
        first = mgr._load_raw()["history"][0]["last_used"]

        # Small pause so timestamps differ
        time.sleep(0.01)
        mgr.record_use(str(d))
        second = mgr._load_raw()["history"][0]["last_used"]

        assert second >= first

    def test_record_resolves_path(self, mgr, tmp_path):
        """Paths with ~ or symlinks are resolved."""
        d = tmp_path / "project_d"
        d.mkdir()
        link = tmp_path / "link_d"
        link.symlink_to(d)
        mgr.record_use(str(link))

        data = mgr._load_raw()
        assert data["history"][0]["path"] == str(d.resolve())


# ---------------------------------------------------------------------------
# TestDirHistoryPin
# ---------------------------------------------------------------------------


class TestDirHistoryPin:
    def test_pin_adds_to_pinned(self, mgr, tmp_path):
        d = tmp_path / "pinned_project"
        d.mkdir()
        mgr.pin(str(d))

        assert str(d.resolve()) in mgr.get_pinned()

    def test_pin_idempotent(self, mgr, tmp_path):
        d = tmp_path / "pinned_project"
        d.mkdir()
        mgr.pin(str(d))
        mgr.pin(str(d))

        assert mgr.get_pinned().count(str(d.resolve())) == 1

    def test_unpin_removes_from_pinned(self, mgr, tmp_path):
        d = tmp_path / "pinned_project"
        d.mkdir()
        mgr.pin(str(d))
        mgr.unpin(str(d))

        assert str(d.resolve()) not in mgr.get_pinned()

    def test_unpin_preserves_history(self, mgr, tmp_path):
        """Unpinning does NOT remove the directory from history."""
        d = tmp_path / "pinned_project"
        d.mkdir()
        mgr.record_use(str(d))
        mgr.pin(str(d))
        mgr.unpin(str(d))

        history = mgr.get_history()
        paths = [h["path"] for h in history]
        assert str(d.resolve()) in paths

    def test_pin_order_preserved(self, mgr, tmp_path):
        """Pinned dirs maintain insertion order."""
        dirs = []
        for name in ["alpha", "beta", "gamma"]:
            d = tmp_path / name
            d.mkdir()
            dirs.append(d)
            mgr.pin(str(d))

        pinned = mgr.get_pinned()
        assert pinned == [str(d.resolve()) for d in dirs]


# ---------------------------------------------------------------------------
# TestDirHistoryRanking
# ---------------------------------------------------------------------------


class TestDirHistoryRanking:
    def test_pinned_appear_first(self, mgr, tmp_path):
        """Pinned directories always appear before non-pinned."""
        pinned_dir = tmp_path / "pinned"
        pinned_dir.mkdir()
        freq_dir = tmp_path / "frequent"
        freq_dir.mkdir()

        # frequent dir has high count
        for _ in range(10):
            mgr.record_use(str(freq_dir))
        mgr.record_use(str(pinned_dir))
        mgr.pin(str(pinned_dir))

        ranked = mgr.get_ranked_dirs()
        assert ranked[0]["path"] == str(pinned_dir.resolve())
        assert ranked[0]["pinned"] is True
        assert ranked[1]["path"] == str(freq_dir.resolve())
        assert ranked[1]["pinned"] is False

    def test_history_sorted_by_frequency(self, mgr, tmp_path):
        """Non-pinned entries are sorted by count descending."""
        dirs = {}
        for name, count in [("low", 1), ("high", 10), ("mid", 5)]:
            d = tmp_path / name
            d.mkdir()
            dirs[name] = d
            for _ in range(count):
                mgr.record_use(str(d))

        ranked = mgr.get_ranked_dirs()
        counts = [r["count"] for r in ranked]
        assert counts == [10, 5, 1]

    def test_deleted_dirs_excluded(self, mgr, tmp_aque_dir, tmp_path):
        """Directories that no longer exist are excluded from ranking."""
        real = tmp_path / "real"
        real.mkdir()
        payload = {
            "pinned": ["/no/such/dir/xyz"],
            "history": [
                {"path": str(real), "count": 3, "last_used": "2026-03-28T10:00:00"},
                {"path": "/no/such/dir/xyz", "count": 99, "last_used": "2026-03-28T10:00:00"},
            ],
        }
        (tmp_aque_dir / "dir_history.json").write_text(json.dumps(payload))

        ranked = mgr.get_ranked_dirs()
        paths = [r["path"] for r in ranked]
        assert "/no/such/dir/xyz" not in paths
        assert str(real) in paths

    def test_max_20_non_pinned(self, mgr, tmp_path):
        """At most 20 non-pinned entries are returned."""
        for i in range(25):
            d = tmp_path / f"dir_{i:03d}"
            d.mkdir()
            mgr.record_use(str(d))

        ranked = mgr.get_ranked_dirs()
        non_pinned = [r for r in ranked if not r["pinned"]]
        assert len(non_pinned) <= 20


# ---------------------------------------------------------------------------
# TestDirHistorySearch
# ---------------------------------------------------------------------------


class TestDirHistorySearch:
    def test_empty_query_returns_ranked(self, mgr, tmp_path):
        """Empty query delegates to get_ranked_dirs."""
        d = tmp_path / "project"
        d.mkdir()
        mgr.record_use(str(d))

        results = mgr.search("", str(tmp_path))
        assert len(results) >= 1
        assert results[0]["path"] == str(d.resolve())

    def test_matches_history(self, mgr, tmp_path):
        """Substring match against existing history."""
        d = tmp_path / "my_special_project"
        d.mkdir()
        mgr.record_use(str(d))

        results = mgr.search("special", str(tmp_path))
        paths = [r["path"] for r in results]
        assert str(d.resolve()) in paths

    def test_scans_filesystem(self, mgr, tmp_path):
        """When few matches, search scans default_dir for subdirectories."""
        # Create subdirectories that should be discovered
        for name in ["alpha_proj", "beta_proj", "gamma_proj"]:
            (tmp_path / name).mkdir()

        results = mgr.search("proj", str(tmp_path))
        paths = [r["path"] for r in results]
        assert any("alpha_proj" in p for p in paths)

    def test_non_matching_query_no_crash(self, mgr, tmp_path):
        """A query that matches nothing returns an empty list gracefully."""
        results = mgr.search("zzz_nonexistent_zzz", str(tmp_path))
        assert isinstance(results, list)

    def test_search_skips_hidden_dirs(self, mgr, tmp_path):
        """Hidden directories (starting with .) are not returned."""
        (tmp_path / ".hidden").mkdir()
        (tmp_path / "visible").mkdir()

        results = mgr.search("", str(tmp_path))
        paths = [r["path"] for r in results]
        assert not any(".hidden" in p for p in paths)

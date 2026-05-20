import json
from aque.history import HistoryManager, _UNSET


class TestHistoryManager:
    def test_load_empty_history(self, tmp_aque_dir):
        mgr = HistoryManager(tmp_aque_dir)
        entries = mgr.load()
        assert entries == []

    def test_add_entry(self, tmp_aque_dir):
        mgr = HistoryManager(tmp_aque_dir)
        mgr.add_entry(
            agent_id=1,
            label="claude . api",
            dir="/tmp/api",
            command=["claude"],
            created_at="2026-03-28T10:00:00Z",
        )
        entries = mgr.load()
        assert len(entries) == 1
        assert entries[0]["label"] == "claude . api"
        assert "completed_at" in entries[0]

    def test_multiple_entries_preserved(self, tmp_aque_dir):
        mgr = HistoryManager(tmp_aque_dir)
        mgr.add_entry(agent_id=1, label="a", dir="/tmp", command=["a"], created_at="2026-03-28T10:00:00Z")
        mgr.add_entry(agent_id=2, label="b", dir="/tmp", command=["b"], created_at="2026-03-28T10:01:00Z")
        entries = mgr.load()
        assert len(entries) == 2
        assert entries[0]["label"] == "a"
        assert entries[1]["label"] == "b"

    def test_count(self, tmp_aque_dir):
        mgr = HistoryManager(tmp_aque_dir)
        assert mgr.count() == 0
        mgr.add_entry(agent_id=1, label="a", dir="/tmp", command=["a"], created_at="2026-03-28T10:00:00Z")
        assert mgr.count() == 1

    def test_add_entry_stores_agent_type(self, tmp_aque_dir):
        mgr = HistoryManager(tmp_aque_dir)
        mgr.add_entry(
            agent_id=1, label="claude . api", dir="/tmp/api",
            command=["claude"], created_at="2026-03-28T10:00:00Z",
            agent_type="claude",
        )
        assert mgr.load()[0]["agent_type"] == "claude"

    def test_add_entry_omits_agent_type_key_when_not_passed(self, tmp_aque_dir):
        mgr = HistoryManager(tmp_aque_dir)
        mgr.add_entry(
            agent_id=1, label="a", dir="/tmp", command=["a"],
            created_at="2026-03-28T10:00:00Z",
        )
        # When agent_type is not passed, the key is omitted (legacy entry semantics).
        assert "agent_type" not in mgr.load()[0]


class TestRecentTasks:
    def _add(self, mgr, label, dir, command, created_at, agent_type=_UNSET):
        kwargs = dict(agent_id=1, label=label, dir=dir, command=command, created_at=created_at)
        if agent_type is not _UNSET:
            kwargs["agent_type"] = agent_type
        mgr.add_entry(**kwargs)

    def test_empty(self, tmp_aque_dir):
        assert HistoryManager(tmp_aque_dir).recent_tasks() == []

    def test_dedup_by_dir_and_command_newest_first(self, tmp_aque_dir):
        mgr = HistoryManager(tmp_aque_dir)
        self._add(mgr, "old", "/a", ["claude"], "2026-01-01T00:00:00Z", "claude")
        self._add(mgr, "other", "/b", ["claude"], "2026-01-02T00:00:00Z", "claude")
        self._add(mgr, "new", "/a", ["claude"], "2026-01-03T00:00:00Z", "claude")
        tasks = mgr.recent_tasks()
        assert [t["label"] for t in tasks] == ["new", "other"]
        assert tasks[0]["dir"] == "/a"

    def test_distinct_dirs_kept(self, tmp_aque_dir):
        mgr = HistoryManager(tmp_aque_dir)
        self._add(mgr, "a", "/a", ["claude"], "2026-01-01T00:00:00Z", "claude")
        self._add(mgr, "b", "/b", ["claude"], "2026-01-02T00:00:00Z", "claude")
        assert len(mgr.recent_tasks()) == 2

    def test_backfill_type_from_same_command(self, tmp_aque_dir):
        mgr = HistoryManager(tmp_aque_dir)
        self._add(mgr, "typed", "/a", ["claude"], "2026-01-01T00:00:00Z", "claude")
        self._add(mgr, "untyped", "/b", ["claude"], "2026-01-02T00:00:00Z")  # no field
        tasks = {t["dir"]: t for t in mgr.recent_tasks()}
        assert tasks["/b"]["agent_type"] == "claude"
        assert tasks["/b"]["type_known"] is True

    def test_unknown_type_when_no_field_and_no_inference(self, tmp_aque_dir):
        mgr = HistoryManager(tmp_aque_dir)
        self._add(mgr, "untyped", "/b", ["mystery"], "2026-01-02T00:00:00Z")  # no field
        task = mgr.recent_tasks()[0]
        assert task["agent_type"] is None
        assert task["type_known"] is False

    def test_explicit_none_is_known(self, tmp_aque_dir):
        mgr = HistoryManager(tmp_aque_dir)
        self._add(mgr, "polling", "/b", ["bash"], "2026-01-02T00:00:00Z", None)  # field present, None
        task = mgr.recent_tasks()[0]
        assert task["agent_type"] is None
        assert task["type_known"] is True

    def test_limit(self, tmp_aque_dir):
        mgr = HistoryManager(tmp_aque_dir)
        for i in range(15):
            self._add(mgr, f"t{i}", f"/d{i}", ["claude"], f"2026-01-{i+1:02d}T00:00:00Z", "claude")
        assert len(mgr.recent_tasks(limit=10)) == 10

    def test_dedup_runs_before_limit(self, tmp_aque_dir):
        # 20 entries spanning only 3 unique (dir, command) keys.
        mgr = HistoryManager(tmp_aque_dir)
        dirs = ["/a", "/b", "/c"]
        for i in range(20):
            d = dirs[i % len(dirs)]
            self._add(mgr, f"t{i}", d, ["claude"], f"2026-01-{i+1:02d}T00:00:00Z", "claude")
        # With a large limit, dedup must collapse to the 3 unique keys, not 10.
        tasks = mgr.recent_tasks(limit=10)
        assert len(tasks) == 3
        assert {t["dir"] for t in tasks} == set(dirs)

    def test_limit_applies_to_distinct_tasks(self, tmp_aque_dir):
        # 5 unique keys, repeated; limit=2 must yield the 2 newest distinct.
        mgr = HistoryManager(tmp_aque_dir)
        dirs = ["/a", "/b", "/c", "/d", "/e"]
        for i in range(10):
            d = dirs[i % len(dirs)]
            self._add(mgr, f"t{i}", d, ["claude"], f"2026-01-{i+1:02d}T00:00:00Z", "claude")
        tasks = mgr.recent_tasks(limit=2)
        assert len(tasks) == 2
        # Newest two distinct entries are i=9 (/e) and i=8 (/d).
        assert [t["dir"] for t in tasks] == ["/e", "/d"]

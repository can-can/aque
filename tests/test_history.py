import json
from aque.history import HistoryManager


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

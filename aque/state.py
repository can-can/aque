import contextlib
import enum
import fcntl
import json
import os
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class AgentState(str, enum.Enum):
    RUNNING = "running"
    WAITING = "waiting"
    FOCUSED = "focused"
    EXITED = "exited"
    ON_HOLD = "on_hold"
    DONE = "done"


@dataclass
class AgentInfo:
    id: int
    tmux_session: str
    label: str
    dir: str
    command: list[str]
    state: AgentState
    pid: int
    created_at: str = ""
    last_change_at: str = ""
    agent_type: str | None = None

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.last_change_at:
            self.last_change_at = now

    def to_dict(self) -> dict:
        d = asdict(self)
        d["state"] = self.state.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AgentInfo":
        d = d.copy()
        d["state"] = AgentState(d["state"])
        d.setdefault("agent_type", None)
        return cls(**d)


@dataclass
class AppState:
    agents: list[AgentInfo] = field(default_factory=list)
    monitor_pid: Optional[int] = None


class StateManager:
    def __init__(self, aque_dir: Path):
        self.aque_dir = Path(aque_dir)
        self.state_file = self.aque_dir / "state.json"
        self.aque_dir.mkdir(parents=True, exist_ok=True)

    def _read_locked(self) -> dict:
        if not self.state_file.exists():
            return {"agents": [], "monitor_pid": None}
        with open(self.state_file, "r") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                return json.load(f)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def _write_locked(self, data: dict) -> None:
        fd, tmp_path = tempfile.mkstemp(dir=self.aque_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self.state_file)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @contextlib.contextmanager
    def _locked(self):
        """Hold an exclusive lock on a lock file for the entire duration of the block."""
        lock_file = self.aque_dir / "state.lock"
        with open(lock_file, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)

    def load(self) -> AppState:
        raw = self._read_locked()
        agents = [AgentInfo.from_dict(a) for a in raw.get("agents", [])]
        return AppState(agents=agents, monitor_pid=raw.get("monitor_pid"))

    def save(self, state: AppState) -> None:
        data = {
            "agents": [a.to_dict() for a in state.agents],
            "monitor_pid": state.monitor_pid,
        }
        self._write_locked(data)

    def add_agent(self, agent: AgentInfo) -> None:
        with self._locked():
            state = self.load()
            state.agents.append(agent)
            self.save(state)

    def remove_agent(self, agent_id: int) -> None:
        with self._locked():
            state = self.load()
            state.agents = [a for a in state.agents if a.id != agent_id]
            self.save(state)

    def update_agent_state(self, agent_id: int, new_state: AgentState) -> None:
        with self._locked():
            state = self.load()
            for agent in state.agents:
                if agent.id == agent_id:
                    agent.state = new_state
                    agent.last_change_at = datetime.now(timezone.utc).isoformat()
                    self.save(state)
                    return
            raise KeyError(agent_id)

    def get_agents_by_state(self, agent_state: AgentState) -> list[AgentInfo]:
        state = self.load()
        return [a for a in state.agents if a.state == agent_state]

    def next_id(self) -> int:
        state = self.load()
        if not state.agents:
            return 1
        return max(a.id for a in state.agents) + 1

    def done_agent(self, agent_id: int, history_manager) -> None:
        with self._locked():
            state = self.load()
            agent = next((a for a in state.agents if a.id == agent_id), None)
            if agent is None:
                raise KeyError(agent_id)
            history_manager.add_entry(
                agent_id=agent.id,
                label=agent.label,
                dir=agent.dir,
                command=agent.command,
                created_at=agent.created_at,
            )
            state.agents = [a for a in state.agents if a.id != agent_id]
            self.save(state)

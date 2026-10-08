from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from code_agent.core.task.model import Task, TaskStatus

def _now() -> str:
    return datetime.now(UTC).isoformat()

class TaskManager:
    def __init__(
        self,
        tasks_dir: Path
    ) -> None:
        self._dir = tasks_dir
        self._dir.mkdir(parents = True, exist_ok = True)
        self._next_id = self._max_id() + 1

    def _max_id(self) -> int:
        ids = [
            int(f.stem.split("_")[1])
            for f in self._dir.glob("task_*.json")
            if f.stem.split("_")[1].isdigit()
        ]

        return max(ids) if ids else 0

    def load(
        self,
        task_id: int 
    ) -> Task:
        path = self._dir / f"task_{task_id}.json"
        if not path.exists():
            raise ValueError(f"task {task_id} not found")
        return Task.from_dict(json.loads(path.read_text(encoding = "utf-8")))

    def _save(
        self,
        task: Task
    ) -> None:
        path = self._dir / f"task_{task.id}.json"
        path.write_text(
            json.dumps(
                task.to_dict(), 
                indent = 2, 
                ensure_ascii = False
            ),
            encoding = "utf-8"
        )

    def create(
        self,
        subject: str,
        description: str = "",
        blocked_by: list[int] | None = None
    ) -> Task:
        for dep_id in (blocked_by or []):
            if not (self._dir / f"task_{dep_id}.json").exists():
                raise ValueError(f"blocked_by task {dep_id} not found")

        now = _now()

        task = Task(
            id = self._next_id,
            subject = subject,
            description = description,
            status = "pending",
            blocked_by = blocked_by,
            created_at = now,
            updated_at = now 
        )

        self._save(task)
        self._next_id += 1
        return task

    def get(
        self,
        task_id: int
    ) -> Task:
        return self.load(task_id)       

    def update(
        self,
        task_id: int,
        *,
        status: TaskStatus | None = None,
        add_blocked_by: list[int] | None = None,
        remove_blocked_by: list[int] | None = None
    ) -> Task:
        task = self.load(task_id)
        if status is not None:
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"invalid status: {status!r}")
            task.status = status
            if status == "completed":
                self._clear_dependency(task_id)

        if add_blocked_by:
            task.blocked_by = list(set(task.blocked_by + add_blocked_by))
        if remove_blocked_by:
            task.blocked_by = [x for x in task.blocked_by if x not in remove_blocked_by]
        
        task.updated_at = _now()
        self._save(task)

        return task

    def _clear_dependency(
        self,
        completed_id: int
    ) -> None:
        for f in self._dir.glob("task_*.json"):
            try:
                data = json.loads(f.read_text(encoding = "utf-8"))
            except (ValueError, json.JSONDecodeError):
                continue
            
            blocked = [int(b) for b in data.get("blocked_by", [])]  
            if completed_id in blocked:
                data["blocked_by"] = [int(x) for x in blocked if x != completed_id]
                data["updated_at"] = _now()
                f.write_text(
                    json.dumps(
                        data, 
                        indent = 2, 
                        ensure_ascii = False
                    ),
                    encoding = "utf-8"
                )

    
    def list_all(self) -> list[Task]:
        tasks = []
        for f in sorted(
            self._dir.glob("task_*.json"), 
            key = lambda p: int(p.stem.split("_")[1])
        ):
            try: 
                tasks.append(
                    Task.from_dict(
                        json.loads(f.read_text(encoding = "utf-8")
                    ))
                )
            except (ValueError, KeyError):
                pass
        
        return tasks
    

    def format_list(self) -> str:
        tasks = self.list_all()
        if not tasks:
            return "Not tasks"
        marker = {
            "pending": "[ ]",
            "in_progress": "[>]",
            "completed": "[X]"
        }
        lines = []
        for t in tasks:
            blocked = f" (blocked by: {t.blocked_by})" if t.blocked_by else ""
            lines.append(f"{marker.get(t.status, "[?]")} #{t.id}: {t.subject}{blocked}")
        
        return "\n".join(lines)

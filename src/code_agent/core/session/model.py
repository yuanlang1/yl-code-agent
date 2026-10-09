from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


SessionMode = Literal["one_shot", "chat"]
SessionStatus = Literal["active", "waiting_for_input", "closed"]

@dataclass
class Session:
    id: str
    mode: SessionMode
    status: SessionStatus
    title: str
    created_at: str
    updated_at: str
    run_ids: list[str] = field(default_factory = list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "mode": self.mode,
            "status": self.status,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "run_ids": list(self.run_ids)
        }
    
    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any]
    ) -> Session:
        return cls(
            id = str(data["id"]),
            mode = data["mode"],
            status = data["status"],
            title = str(data.get("title", "")),
            created_at = str(data["created_at"]),
            updated_at = str(data["updated_at"]),
            run_ids = [str(x) for x in data.get("run_id", [])]
        )

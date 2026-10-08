from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

@dataclass
class ExecutionContext:
    run_id: str
    goal: str
    max_steps: int

    step: int = 0
    messages: list[dict[str, Any]] = field(default_factory = list)
    status: str = "running"
    reason: str | None = None
    result: str = ""

    def __post_init__(self) -> None:
        if not self.messages:
            self.messages.append({
            "role": "user",
            "content": self.goal
        })
    
    def add_assistant_message(
        self,
        content: list[Any]
    ) -> None:
        self.messages.append({
            "role": "assistant",
            "content": content
        })

    def add_tool_result(
        self,
        tool_use_id: str,
        content: str,
        is_error: bool = False
    ) -> None:
        block: dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": content
        }

        if is_error:
            block["is_error"] = True

        last = self.messages[-1] if self.messages else None
        if (
            last is not None
            and last["role"] == "user"
            and isinstance(last["content"], list)
            and last["content"]
            and all(a.get("type") == "tool_result" for a in last["content"])
        ):
            last["content"].append(block)

        else:
            self.messages.append({
                "role": "user",
                "content": [block]
            })

    def is_done(self) -> bool:
        return  self.status != "running"

    def is_success(self) -> bool:
        return self.status == "success" 
    
    def mark_success(self) -> None:
        self.status = "success"

    def mark_failed(
        self,
        reason: str
    ) -> None:
        self.status = "failed"
        self.reason = reason
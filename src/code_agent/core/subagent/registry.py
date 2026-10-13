
import asyncio

from code_agent.core.context import ExecutionContext


class BackgroundTaskRegistry:
    def __init__(self) -> None:
        self._task: dict[str, tuple[asyncio.Task[None], ExecutionContext]] = []

    def register(
        self,
        run_id: str,
        task: asyncio.Task[None],
        context: ExecutionContext
    ) -> None:
        self._task[run_id] = (task, context)

    def get(
        self,
        run_id: str
    ) -> tuple[asyncio.Task[None], ExecutionContext] | None:
        return self._task.get(run_id)
        
    def all(self) -> list[tuple[asyncio.Task[None], ExecutionContext]]:
        return list(self._task.values())
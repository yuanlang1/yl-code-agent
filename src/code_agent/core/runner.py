

from asyncio import CancelledError
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from code_agent.core.bus.events import RunFinishedEvent, RunStartedEvent
from code_agent.core.config import AgentConfig
from code_agent.core.context import ExecutionContext
from code_agent.core.events.bus import EventBus, EventHandler
from code_agent.core.events.writer import EventWriter
from code_agent.core.llm.base import LlmProvider
from code_agent.core.llm.provider import AnthropicProvider
from code_agent.core.loop import AgentLoop
from code_agent.core.runs import RUNS_DIR, new_run_id
from code_agent.core.tools.builtin.read_file import ReadFileTool
from code_agent.core.tools.registry import ToolRegistry



def _now() -> str:
    return datetime.now(UTC).isoformat()

class AgentRunner:
    def __init__(
        self,
        config: AgentConfig,
        *,
        provider: LlmProvider | None = None,
        extra_handler: list[EventHandler],
        runs_dir: Path | None = None
    ) -> None:
        self._config = config
        self._provider = provider
        self._extra_handler = extra_handler
        self._runs_dir = runs_dir or RUNS_DIR

    async def run(
        self,
        goal: str
    ) -> None:
        run_id = new_run_id()
        run_path = self._runs_dir / run_id
        run_path.mkdir(parents = True, exist_ok = True)

        bus = EventBus()
        for handler in self._extra_handler:
            bus.subscribe(handler)
        
        provider = self._provider or AnthropicProvider(self._config.llm.default_model)
        registry = ToolRegistry()
        registry.registry(ReadFileTool)

        loop = AgentLoop(provider, bus, registry)

        context = ExecutionContext(
            run_id = run_id,
            goal = goal,
            max_steps = self._config.loop.max_steps
        )

        async with EventWriter(run_path / "events.jsonl") as writer:
            bus.subscribe(writer.handle)

            await bus.publish(
                RunStartedEvent(run_id = run_id, goal = goal, ts = _now())
            )

            cancelled = False

            try:
                await loop.run(context)
            except CancelledError:
                cancelled = True
                if not context.is_done():
                    context.mark_failed("cancelled")

            await bus.publish(
                RunFinishedEvent(
                    run_id = run_id,
                    status = context.status,
                    reason = context.reason,
                    steps = context.step,
                    ts = _now()
                )
            )

        if cancelled:
            raise asyncio.CancelledError()

            



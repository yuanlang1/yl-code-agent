

from asyncio import CancelledError
import asyncio
from dataclasses import dataclass
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
from code_agent.core.trace.provider import TracingProvider
from code_agent.core.trace.writer import TraceWriter

def _now() -> str:
    return datetime.now(UTC).isoformat()

@dataclass
class RunOutcome:
    status: str
    result: str
    reason: str | None

class AgentRunner:
    def __init__(
        self,
        config: AgentConfig,
        *,
        provider: LlmProvider | None = None,
        extra_handler: list[EventHandler] | None = None,
        runs_dir: Path | None = None,
        bus: EventBus | None = None,
        trace: TraceWriter | None = None
    ) -> None:
        self._config = config
        self._provider = provider
        self._bus = bus
        self._extra_handler: list[EventHandler] = extra_handler or []
        self._runs_dir = runs_dir or RUNS_DIR
        self._trace = trace

    async def run(
        self,
        goal: str,
        *,
        run_id: str | None = None
    ) -> RunOutcome:
        await self.run_and_capture(
            goal = goal,
            run_id = run_id
        )

    async def run_and_capture(
        self,
        goal: str,
        run_id: str | None = None
    ) -> RunOutcome:
        run_id = run_id or new_run_id()
        run_path = self._runs_dir / run_id
        run_path.mkdir(parents = True, exist_ok = True)

        bus = self._bus if self._bus is not None else EventBus()
        for handler in self._extra_handler:
            bus.subscribe(handler)

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

            provider = self._provider or AnthropicProvider(self._config.llm.default_model)
            if self._trace is not None:
                provider = TracingProvider(
                    provider,
                    self._trace,
                    include_payload = self._config.trace.include_llm_payload
                )

            registry = ToolRegistry()
            registry.registry(ReadFileTool)

            loop = AgentLoop(provider, bus, registry)

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

        return RunOutcome(
            status = context.status,
            result = context.result,
            reason = context.reason
        )

            



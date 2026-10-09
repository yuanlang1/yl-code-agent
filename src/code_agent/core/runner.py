

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
from code_agent.core.session.model import Session
from code_agent.core.session.store import SessionStore
from code_agent.core.task import TaskManager
from code_agent.core.tools.builtin.bash import BashTool
from code_agent.core.tools.builtin.environment_info import EnvironmentInfoTool
from code_agent.core.tools.builtin.listdir import ListDirTool
from code_agent.core.tools.builtin.note_save import NoteSaveTool
from code_agent.core.tools.builtin.read_file import ReadFileTool
from code_agent.core.tools.builtin.task_create import TaskCreateTool
from code_agent.core.tools.builtin.task_get import TaskGetTool
from code_agent.core.tools.builtin.task_list import TaskListTool
from code_agent.core.tools.builtin.task_update import TaskUpdateTool
from code_agent.core.tools.builtin.write_file import WriteFileTool
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

    def _build_registry(
        self,
        task_manager: TaskManager,
        session: Session | None = None,
        store: SessionStore | None = None,
        run_id: str | None = None
    ) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(ReadFileTool())
        registry.register(BashTool())
        registry.register(WriteFileTool())
        registry.register(ListDirTool())
        registry.register(EnvironmentInfoTool())
        registry.register(TaskCreateTool(task_manager))
        registry.register(TaskUpdateTool(task_manager))
        registry.register(TaskListTool(task_manager))
        registry.register(TaskGetTool(task_manager))

        if session is not None and store is not None and run_id is not None:
            return registry.register(NoteSaveTool(store, session.id, run_id))
        return registry

    async def run(
        self,
        goal: str,
        *,
        run_id: str | None = None,
        session: Session | None = None,
        store: SessionStore | None = None
    ) -> RunOutcome:
        await self.run_and_capture(
            goal = goal,
            run_id = run_id,
            session = session,
            store = store
        )

    async def run_and_capture(
        self,
        goal: str,
        run_id: str | None = None,
        session: Session | None = None,
        store: SessionStore | None = None
    ) -> RunOutcome:
        run_id = run_id or new_run_id()

        if session is not None and store is not None:
            run_path = store.runs_dir(session.id) / run_id
            history = store.read_messages(session.id)
            notes = store.read_notes(session.id)
        else:
            run_path = self._runs_dir / run_id
            history = [{"role": "user", "content": goal}]
            notes = ""

        run_path.mkdir(parents = True, exist_ok = True)
        
        task_manager = TaskManager(run_path / ".tasks")

        bus = self._bus if self._bus is not None else EventBus()
        for handler in self._extra_handler:
            bus.subscribe(handler)

        context = ExecutionContext(
            run_id = run_id,
            goal = goal,
            max_steps = self._config.loop.max_steps,
            prefill_messages = history,
            session_notes = notes
        )

        prefill_len = len(history)

        async with EventWriter(run_path / "events.jsonl") as writer:
            bus.subscribe(writer.handle)

            await bus.publish(
                RunStartedEvent(run_id = run_id, goal = goal, ts = _now())
            )
            registry = self._build_registry(task_manager)

            cancelled = False
            try:
                provider = self._provider or AnthropicProvider(self._config.llm.default_model)
                if self._trace is not None:
                    provider = TracingProvider(
                        provider,
                        self._trace,
                        include_payload = self._config.trace.include_llm_payload
                    )

                loop = AgentLoop(provider, bus, registry)
                await loop.run(context)
            except CancelledError:
                cancelled = True
                if not context.is_done():
                    context.mark_failed("cancelled")
            except Exception:
                if not context.is_done():
                    context.mark_failed("llm_error")

            await bus.publish(
                RunFinishedEvent(
                    run_id = run_id,
                    status = context.status,
                    reason = context.reason,
                    steps = context.step,
                    ts = _now()
                )
            )

        if session is not None and store is not None:
            store.append_messages(
                session_id = session.id, 
                messages = context.messages[prefill_len:],
                run_id = run_id
            )

        if cancelled:
            raise asyncio.CancelledError()

        return RunOutcome(
            status = context.status,
            result = context.result,
            reason = context.reason
        )

            



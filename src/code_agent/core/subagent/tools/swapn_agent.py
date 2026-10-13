
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field
from code_agent.core.agents import AgentProfile, AgentProfileLoader
from code_agent.core.bus.events import SubagentFinishedEvent, SubagentStartedEvent
from code_agent.core.context import ExecutionContext
from code_agent.core.events.bus import EventBus
from code_agent.core.events.writer import EventWriter
from code_agent.core.llm.base import LlmProvider
from code_agent.core.loop import AgentLoop
from code_agent.core.permissions import PermissionManager
from code_agent.core.runs import new_run_id
from code_agent.core.subagent.registry import BackgroundTaskRegistry
from code_agent.core.subagent.tools.agent_result import AgentResultTool
from code_agent.core.task import TaskManager
from code_agent.core.tools.base import BaseTool, ToolResult
from code_agent.core.tools.builtin.bash import BashTool
from code_agent.core.tools.builtin.listdir import ListDirTool
from code_agent.core.tools.builtin.read_file import ReadFileTool
from code_agent.core.tools.builtin.task_create import TaskCreateTool
from code_agent.core.tools.builtin.task_get import TaskGetTool
from code_agent.core.tools.builtin.task_list import TaskListTool
from code_agent.core.tools.builtin.task_update import TaskUpdateTool
from code_agent.core.tools.builtin.write_file import WriteFileTool
from code_agent.core.tools.registry import ToolRegistry

def _now() -> str:
    return datetime.now(UTC).isoformat()

class SpawnAgentParams(BaseModel):
    model_config = ConfigDict(extra = "forbid")
    description: str = Field(description = "3-5 word task description shown in progress display")
    prompt: str = Field(
        description = (
            "Complete task description including all context the sub-agent needs. "
            "The sub-agent cannot see the parent conversation, so be explicit."
        )
    )
    run_in_background: bool = Field(
        default = False,
        description = "When true, returns immediately with a run_id; use agent_result to poll."
    )
    subagent_type: str = Field(
        default = "",
        description = "Agent role profile (planner/executor/reviewer). Leave empty for default."
    )

class SpawnAgentTool(BaseTool):
    name = "spawn_agent"
    description = (
        "Spawn an isolated sub-agent to handle a self-contained sub-task. "
        "The sub-agent starts with a clean context containing only the provided prompt — "
        "it does not inherit the current conversation history. "
        "Use run_in_background=true to run in parallel; retrieve result later with agent_result."
    )

    params_model = SpawnAgentParams
    input_schemas = SpawnAgentParams.model_json_schema()

    def __init__(
        self,
        provider: LlmProvider,
        parent_bus: EventBus,
        parent_run_id: str,
        permission_manager: PermissionManager,
        max_steps: int,
        task_registry: BackgroundTaskRegistry,
        runs_dir: Path,
        session_id: str,
        depth: int = 0
    ) -> None:
        self._provider = provider
        self._parent_bus = parent_bus
        self._parent_run_id = parent_run_id
        self._permission_manager = permission_manager
        self._max_steps = max_steps
        self._task_registry = task_registry
        self._runs_dir = runs_dir
        self._session_id = session_id
        self._depth = depth

    async def invoke(
        self, 
        params: dict[str, object]
    ) -> ToolResult:
        vp = self.params_model.model_validate(params)

        # 嵌套层数不能 >2
        if self._depth > 2:
            return ToolResult(
                content = "Subagent nesting limit (2) reached; cannot spawn further subagents.",
                is_error = True,
                error_type = "runtime_error" 
            )

        profile: AgentProfile | None = None
        if vp.subagent_type:
            profile = AgentProfileLoader().load(vp.subagent_type)

        child_run_id = new_run_id()
        child_context = ExecutionContext(
            run_id = child_run_id,
            goal = vp.prompt,
            max_steps = self._max_steps,
            system_prompt_override = profile.system_prompt if profile else None
        )

        child_bus = EventBus()
        async def _bridge(event: BaseModel) -> None:
            await self._parent_bus.publish(event)

        child_bus.subscribe(handler = _bridge)
        
        child_registry = self._build_child_registry(child_bus, child_run_id, profile)

        child_loop = AgentLoop(
            provider = self._provider,
            bus = child_bus,
            registry = child_registry,
            permission_manager = self._permission_manager,
            session_id = self._session_id
        )

        await self._parent_bus.publish(
            SubagentStartedEvent(
                run_id = child_run_id,
                parent_run_id = self._parent_run_id,
                description = profile.description,
                ts = _now()
            ) 
        )

        child_run_path = self._runs_dir / child_run_id
        child_run_path.mkdir(parents = True, exist_ok = True)

        # run in background
        if vp.run_in_background:
            task: asyncio.Task[None] = asyncio.create_task(
                self._run_background(
                    loop = child_loop,
                    context = child_context,
                    bus = child_bus,
                    run_path = child_run_path,
                    run_id = child_run_id
                )
            )
            self._task_registry.register(child_run_id, task)
            return ToolResult(
                content = (
                    f"Subagent started in background. run_id={child_run_id}. "
                    f"Use agent_result(run_id='{child_run_id}') to receive result."
                )
            )

        
        async with EventWriter(child_run_path / "events.jsonl") as writer:
            writer.subscribe(child_bus)
            await child_loop.run(child_context)

        await self._parent_bus.publish(
            SubagentFinishedEvent(
                run_id = child_run_id, 
                parent_run_id = self._parent_run_id,
                status = child_context.status,
                ts = _now()
            )
        )

        if child_context.status == "success":
            return ToolResult(
                content = child_context.result or "Subagent completed with no text result"
            )
        
        return ToolResult(
            content = child_context.result 
                      or f"Subagent failed (status={child_context.status}, reason={child_context.reason})",
            is_error = True,
            error_type = "runtime_error"
        )

    # run in background
    async def _run_background(
        self,
        loop: AgentLoop,
        context: ExecutionContext,
        bus: EventBus,
        run_path: Path,
        run_id: str
    ) -> None:
        async with EventWriter(run_path / "events.jsonl") as writer:
            writer.subscribe(bus)
            await loop.run(context)

        await self._parent_bus.publish(
            SubagentFinishedEvent(
                run_id = run_id,
                parent_run_id = self._parent_run_id,
                status = context.status,
                ts = _now()
            )
        )


    def _build_child_registry(
        self,
        child_bus: EventBus,
        child_run_id: str,
        profile: AgentProfile | None
    ) -> ToolRegistry:
        allowed: set[str] | None = (
            set(profile.allowed_tools) if profile and profile.allowed_tools else None
        )

        def _allowed(name: str) -> bool:
            return allowed is None or name in allowed

        registry = ToolRegistry()
        _all_tools = [
            ReadFileTool(),
            BashTool(),
            WriteFileTool(), 
            ListDirTool()
        ]

        for t in _all_tools:
            if _allowed(t.name):
                registry.register(t)

        child_task_manager = TaskManager(self._runs_dir / child_run_id / ".tasks")
        for t in [
            TaskCreateTool(child_task_manager),
            TaskGetTool(child_task_manager),
            TaskListTool(child_task_manager),
            TaskUpdateTool(child_task_manager)
        ]:
            if _allowed(t.name):
                registry.register(t)

        # 可以继续嵌套子agent
        if self._depth < 1:
            nested = SpawnAgentTool(
                provider = self._provider,
                parent_bus = child_bus,
                parent_run_id = child_run_id,
                permission_manager = self._permission_manager,
                max_steps = self._max_steps,
                task_registry = self._task_registry,
                runs_dir = self._runs_dir,
                session_id = self._session_id,
                depth = self._depth + 1    
            )

            if _allowed("spawn_agent"):
                registry.register(nested)
            if _allowed("agent_result"):
                registry.register(AgentResultTool(self._task_registry))

        return registry


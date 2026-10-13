from pydantic import BaseModel, ConfigDict, Field
from code_agent.core.subagent.registry import BackgroundTaskRegistry
from code_agent.core.tools.base import BaseTool, ToolResult


class AgentResultParams(BaseModel):
    model_config = ConfigDict(extra = "forbid")
    run_id: str = Field(description = "The run_id returned by spawn_agent(run_in_background=true)")

class AgentResultTool(BaseTool):
    name = "agent_result"
    description = (
        "Retrieve the result of a background sub-agent previously started with spawn_agent. "
        "Returns 'still running' if the sub-agent has not yet completed."
    )
    params_model = AgentResultParams
    input_schemas = AgentResultParams.model_json_schema()

    def __init__(
        self,
        task_registry: BackgroundTaskRegistry
    ) -> None:
        self._task_registry = task_registry

    async def invoke(
        self, 
        params: dict[str, object]
    ) -> ToolResult:
        vp = self.params_model.model_validate(params)

        entry = self._task_registry.get(vp.run_id)
        if entry == None:
            return ToolResult(
                content = f"Unknown run_id: {vp.run_id}. Only background subagents can be queried.",
                is_error = True,
                error_type = "runtime_error",
            )   
        
        task, context = entry
        if not task.done():
            return ToolResult(content = "still running")

        if task.cancelled():
            return ToolResult(
                content = "Subagent was cancelled.",
                is_error = True, 
                error_type = "runtime_error"
            )

        exc = task.exception()
        if exc is not None:
            return ToolResult(
                content = f"Subagent raised an exception: {exc}",
                is_error = True,
                error_type = "runtime_error",
            )

        return ToolResult(
            content = context.result or "Subagent completed with no text result." 
        )


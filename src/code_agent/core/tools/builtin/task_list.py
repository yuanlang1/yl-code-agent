
from pydantic import BaseModel, ConfigDict
from code_agent.core.task import TaskManager
from code_agent.core.tools.base import BaseTool, ToolResult

class TaskListParams(BaseModel):
    model_config = ConfigDict(extra = "forbid")


class TaskListTool(BaseTool):
    name = "task_list"
    description = (
        "List all tasks with their current status and blocking dependencies. "
        "Use this to check what work remains and what can be started next."
    )
    params_model = TaskListParams
    input_schemas: dict[str, object] = params_model.model_json_schema()

    def __init__(
        self,
        task_manager: TaskManager
    ) -> None:
        self._manager = task_manager

    async def invoke(
        self, 
        params: dict[str, object]
    ) -> ToolResult:
        return ToolResult(
            content = self._manager.format_list()
        )
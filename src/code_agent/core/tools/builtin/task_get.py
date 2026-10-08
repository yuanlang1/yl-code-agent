
import json
from pydantic import BaseModel, ConfigDict, Field
from code_agent.core.task import TaskManager
from code_agent.core.tools.base import BaseTool, ToolResult

class TaskGetParams(BaseModel):
    model_config = ConfigDict(extra = "forbid")
    task_id: int = Field(
        description = "ID of the task to retrieve."
    )


class TaskGetTool(BaseTool):
    name = "task_get"
    description = "Get full details of a task by its integer ID. Returns the task as JSON."
    params_model = TaskGetParams
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
        input = self.params_model.model_validate(params)
        
        try:
            task = self._manager.get(input.task_id)
            return ToolResult(content = json.dumps(task.to_dict(), ensure_ascii = False))
        except ValueError as ex:
            return ToolResult(
                content = str(ex),
                is_error = True,
                error_type = "runtime_error"
            )
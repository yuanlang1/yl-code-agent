
import json
from pydantic import BaseModel, ConfigDict, Field
from code_agent.core.task import TaskManager
from code_agent.core.tools.base import BaseTool, ToolResult

class TaskCreateParams(BaseModel):
    model_config = ConfigDict(extra = "forbid")
    subject: str = Field(description = "Short title for the task")
    description: str = Field(
        default_factory = str,
        description = "Optional longer description of what needs to be done." 
    )
    blocked_by: list[int] = Field(
        default_factory = list,
        description = "IDs of tasks that must be completed before this one."
    )

class TaskCreateTool(BaseTool):
    name = "task_create"
    description = (
        "Create a new task to track a unit of work. "
        "Use this to break down a complex goal into smaller, trackable steps. "
        "Returns the created task as JSON."
    )
    params_model = TaskCreateParams
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
        subject = str(params["subject"])
        description = str(params.get("description", ""))
        raw_blocked: list[object] = list(params.get("blocked_by") or []) 
        blocked_by = [int(str(x)) for x in raw_blocked]

        try:
            task = self._manager.create(subject, description, blocked_by)
            return ToolResult(
                content = json.dumps(task.to_dict(), ensure_ascii = False)
            )
        except ValueError as ex:
            return ToolResult(
                content = str(ex),
                is_error = True,
                error_type = "runtime_error" 
            )
        

import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from code_agent.core.task import TaskManager, TaskStatus
from code_agent.core.tools.base import BaseTool, ToolResult

class TaskUpdateParams(BaseModel):
    model_config = ConfigDict(extra = "forbid")
    task_id: int = Field(description = "ID of the task to update.")
    status: Literal[
        "pending", "in_progress", "completed"
    ] | None = Field(
        default = None,
        description = "New status for the task."
    )
    add_blocked_by: list[int] = Field(
        default_factory = list,
        description = "Task IDs to add to blocked_by."
    )
    remove_blocked_by: list[int] = Field(
        default_factory = list,
        description = "Task IDs to remove from blocked_by."
    )

class TaskUpdateTool(BaseTool):
    name = "task_update"
    description = (
        "Update a task's status or dependency list. "
        "Set status to 'in_progress' when starting work on a task, "
        "'completed' when finished (automatically clears it from other tasks' blocked_by). "
        "Returns the updated task as JSON."
    )
    params_model = TaskUpdateParams
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
        validated = self.params_model.model_validate(params)

        try:
            task = self._manager.update(
                task_id = validated.task_id,
                status = validated.status,
                add_blocked_by= validated.add_blocked_by or None,
                remove_blocked_by = validated.remove_blocked_by or None
            )
            
            return ToolResult(content = json.dumps(task.to_dict(), ensure_ascii = False))

        except ValueError as ex:
            return ToolResult(
                content = str(ex),
                is_error = True,
                error_type = "runtime_error"
            )
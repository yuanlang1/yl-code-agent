
from pydantic import BaseModel, ConfigDict, Field
from code_agent.core.session.store import SessionStore
from code_agent.core.tools.base import BaseTool, ToolResult

class NoteSaveParams(BaseModel):
    model_config = ConfigDict(extra = "forbid")
    content: str = Field(description = "The durable fact or decision to remember.")

class NoteSaveTool(BaseTool):
    name = "note_save"
    description = (
        "Save a concise fact or decision to this session's notes. "
        "These notes are visible in future turns of the same session."
    )
    params_model = NoteSaveParams
    input_schemas = params_model.model_json_schema()

    def __init__(
        self,
        store: SessionStore,
        session_id: str,
        run_id: str
    ) -> None:
        self._store = store
        self._session_id = session_id
        self._run_id = run_id

    async def invoke(
        self, 
        params: dict[str, object]
    ) -> ToolResult:
        validated = self.params_model.model_validate(params)
        content = validated.content

        if not content:
            return ToolResult(
                content = "empty content",
                is_error = True,
                error_type = "runtime_error" 
            )
        
        self._store.append_notes(
            session_id = self._session_id,
            content = content, 
            run_id = self._run_id
        )

        return ToolResult(content = "saved")

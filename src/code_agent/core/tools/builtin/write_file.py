
import json
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field
from code_agent.core.tools.base import BaseTool, ToolResult

_MAX_BYTES = 1 * 1024 * 1024  # 1 MB

class WriteFileParams(BaseModel):
    model_config = ConfigDict(extra = "forbid")
    path: str = Field(
        description = "Relative path to the file (relative to current working directory)."
    )
    content: str = Field(description = "Text content to write.")

class WriteFileTool(BaseTool):
    name = "write_file"
    description = (
        "Write text content to a file, creating it (and any parent directories) if it "
        "does not exist, or overwriting it if it does. "
        "Path must be relative to the current working directory. "
        "Content size is limited to 1 MB."
    )
    params_model = WriteFileParams
    input_schemas: dict[str, object] = params_model.model_json_schema()

    async def invoke(
        self,
        params: dict[str, object]
    ) -> ToolResult:
        validated = self.params_model.model_validate(params)
        path_str = validated.path
        content = validated.content

        if ".." in Path(path_str).parts:
            raise PermissionError(f"path traversal not allowed: {path_str}")

        encoded = content.encode("utf-8")
        if len(encoded) > _MAX_BYTES:
            return ToolResult(
                content = f"content too large: {len(encoded)} bytes (limit 1MB)",
                is_error = True,
                error_type = "runtime_error"
            )
        
        path = Path(path_str)
        path.parent.mkdir(parents = True, exist_ok = True)
        path.write_text(content, encoding = "utf-8")

        return ToolResult(content = f"wrote {len(encoded)} bytes to {path_str}")
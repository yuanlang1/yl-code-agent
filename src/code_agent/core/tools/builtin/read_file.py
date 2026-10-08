from __future__ import annotations
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field
from code_agent.core.tools.base import BaseTool, ToolResult

_MAX_BYTES = 512 * 1024

class ReadFileParam(BaseModel):
    model_config = ConfigDict(extra = "forbid")
    path: str = Field(
        description = (
            "Relative path to the file "
            "(relative to current working directory)."
        )
    )

class ReadFileTool(BaseTool):
    name = "read_file"
    description = (
        "Read the text content of a file. "
        "Path must be relative to the current working directory. "
        "Files larger than 512 KB are truncated.")
    params_model = ReadFileParam
    input_schemas: dict[str, object] = ReadFileParam.model_json_schema()

    async def invoke(
        self, 
        params: dict[str, object]
    ) -> ToolResult:
        # 再次检验
        validated = self.params_model.model_validate(params)
        path_str = validated.path

        if ".." in Path(path_str).parts:
            raise PermissionError(f"path traversal not allowed: {path_str}")

        path = Path(path_str)
        raw = path.read_bytes()
        truncated = len(raw) > _MAX_BYTES

        text = raw[:_MAX_BYTES].decode("utf-8", errors = "replace")
        if truncated:
            text += "\n[truncated]"

        return ToolResult(text)
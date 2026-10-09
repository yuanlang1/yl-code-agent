
import asyncio
from dataclasses import field
from pydantic import BaseModel, ConfigDict, Field
from code_agent.core.tools.base import BaseTool, ToolResult

_MAX_OUTPUT_BYTES = 64 * 1024  # 64 KB
_DEFAULT_TIMEOUT = 60

class BashParams(BaseModel):
    model_config = ConfigDict(extra = "forbid")
    command: str = Field(description = "Shell command to execute.")
    timeout: int = Field(
        default = _DEFAULT_TIMEOUT,
        ge = 1,
        le = 120,
        description = f"Maximum seconds to wait (default {_DEFAULT_TIMEOUT}, max 120).",
    )

class BashTool(BaseTool):
    name = "bash"
    description = (
        "Execute a shell command and return its output (stdout + stderr combined). "
        "Non-interactive only — commands requiring user input will hang and time out. "
        "Prefer short, focused commands. Output is truncated at 64 KB."
    )
    params_model = BashParams
    input_schemas: dict[str, object] = params_model.model_json_schema()

    async def invoke(
        self, 
        params: dict[str, object]
    ) -> ToolResult:
        validated = self.params_model.model_validate(params)
        command = validated.command
        timeout = validated.timeout
        
        try: 
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout = asyncio.subprocess.PIPE,
                stderr = asyncio.subprocess.STDOUT
            )

            try:
                stdout_bytes, _ = await asyncio.wait_for(
                    proc.communicate(), timeout = timeout
                )
            except TimeoutError:
                proc.kill()
                await proc.communicate()
                return ToolResult(
                    content = f"[timeout after {timeout}s]",
                    is_error = True,
                    error_type = "timeout"
                )
        except Exception as ex:
            return ToolResult(
                content = str(ex),
                is_error = True,
                error_type = "runtime_error"
            )

        output = stdout_bytes.decode(encoding = "utf-8", errors = "replace")
        truncated = len(stdout_bytes) > _MAX_OUTPUT_BYTES
        if truncated:
            output = output[:_MAX_OUTPUT_BYTES] + "\n[truncated]"

        returncode = proc.returncode or 0

        if returncode != 0:
            return ToolResult(
                content = f"[exit {returncode}]\n{output}",
                is_error = True,
                error_type = "runtime_error",
            )

        return ToolResult(content = output or "[no output]") 
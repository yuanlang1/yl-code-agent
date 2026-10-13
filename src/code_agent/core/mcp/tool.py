
from typing import Any
from code_agent.core.mcp.client import McpClient, McpServerUnavailableError, McpToolDef, McpToolError
from code_agent.core.tools.base import BaseTool, ToolResult


class McpTool(BaseTool):
    params_model = None

    def __init__(
        self,
        client: McpClient,
        server_name: str,
        tool_def: McpToolDef
    ) -> None:
        self._client = client
        self._server_name = server_name
        self._tool_def = tool_def,
        self.name = f"{server_name}__{tool_def.name}"
        self.description = tool_def.description or f"MCP tool from {server_name}"
        self.input_schemas: dict[str, Any] = (
            tool_def.input_schema or {"type": "object", "properties": {}}
        )

    async def invoke(
        self, 
        params: dict[str, object]
    ) -> ToolResult:
        try:
            content = self._client.call_tool(
                name = self._tool_def.name,
                arguments = dict(params)
            )
            return ToolResult(content = content)

        except McpServerUnavailableError as exc:
            return ToolResult(
                content = f"mcp server '{self._server_name}' unavailable: {exc}",
                is_error = True,
                error_type = "runtime_error"
            )

        except McpToolError as exc:
            return ToolResult(
                content = f"mcp tool '{self.name}' err: {str(exc)}",
                is_error = True,
                error_type = "runtime_error"
            )

        except Exception as exc:
            return ToolResult(
                content = f"mcp tool '{self.name}' unexpected error: {str(exc)}",
                is_error = True,
                error_type = "runtime_error"
            )
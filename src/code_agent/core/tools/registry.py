
from code_agent.core.tools.base import BaseTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def registry(
        self,
        tool: BaseTool
    ) -> None:
        self._tools[tool.name] = tool

    def get(
        self,
        name: str
    ) -> BaseTool | None:
        return self._tools[name] 
    
    def tool_schemas(self) -> list[dict[str, object]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.params_model.model_json_schema(),
            }
            for tool in self._tools.values()
        ]
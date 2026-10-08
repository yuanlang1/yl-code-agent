from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from pydantic import BaseModel


@dataclass
class ToolResult:
    content: str
    is_error: bool = False
    error_type: str | None = None

class BaseTool(ABC):
    name: str
    description: str
    input_schemas: dict[str, object]
    params_model: ClassVar[type[BaseModel] | None] = None

    @abstractmethod
    async def invoke(
        self,
        params: dict[str, object]
    ) -> ToolResult:
        ...



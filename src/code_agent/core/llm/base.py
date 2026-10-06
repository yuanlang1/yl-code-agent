
from typing import Protocol

from code_agent.core.events.bus import EventBus
from code_agent.core.llm.types import LlmResponse


class LlmProvider(Protocol):
    async def chat(
         self,
        messages: list[dict[str, object]],
        tool_schemas: list[dict[str, object]],
        bus: EventBus,
        run_id: str
    ) -> LlmResponse:
        ...
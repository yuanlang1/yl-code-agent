
from datetime import UTC, datetime
import os
from typing import Any
import anthropic

from code_agent.core.bus.events import LlmModelSelectedEvent, LlmTokenEvent, LlmUsageEvent
from code_agent.core.events.bus import EventBus
from code_agent.core.llm.types import LlmResponse, ToolCallBack, UsageStats

_SYSTEM_PROMPT = (
    "You are a helpful AI assistant. "
    "Use the available tools to complete the user's goal. "
    "When the goal is fully achieved, respond with a final answer and do not call any more tools."
)

def _now() -> str:
    return datetime.now(UTC).isoformat()


class AnthropicProvider:
    def __init__(
        self,
        model: str,
        client: Any = None
    ) -> None:
        if client is None:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise SystemExit("ANTHROPIC API KEY is not set")
            
            self.client: Any = anthropic.AsyncAnthropic(api_key = api_key)
        else:
            self.client = client
        
        self.model = model

    async def chat(
        self,
        messages: list[dict[str, object]],
        tool_schemas: list[dict[str, object]],
        bus: EventBus,
        run_id: str
    ) -> LlmResponse:
        await bus.publish(
            LlmModelSelectedEvent(run_id = run_id, model = self.model, strategy = "static", ts = _now())
        )

        system: list[dict[str, object]] = [
           {"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
        ]

        tools: list[dict[str, object]] = list(tool_schemas)
        if tools:
            last = dict(tools[-1])
            last["cache_control"] = {"type": "ephemeral"}
            tools = tools[:-1] + [last]
 
        kwargs: dict[str, object] = {
            "model": self.model,
            "max_tokens": 4096,
            "system": system,
            "messages": messages
        }

        if tools:
            kwargs["tools"] = tools

        text_parts: list[str] = []

        async with self.client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                await bus.publish(LlmTokenEvent(run_id = run_id, token = text, ts = _now()))
                text_parts.append(text)

            final_message = await stream.get_final_message()

        usage = final_message.usage
        cache_read: int = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_create: int = getattr(usage, "cache_creation_input_tokens", 0) or 0

        await bus.publish(
            LlmUsageEvent(
                run_id = run_id,
                input_tokens = usage.input_tokens,
                output_tokens = usage.output_tokens,
                cache_read_input_tokens = cache_read,
                cache_creation_input_tokens = cache_create,
                ts = _now()
            )
        )

        tool_calls: list[ToolCallBack] = []

        for block in final_message.content:
            if block == "tool_calls":
                tool_calls.append(
                    ToolCallBack(
                        id = block.id, 
                        name = block.name, 
                        input = dict(block.input)
                    )
                )

        return LlmResponse(
            stop_reason = final_message.stop_reason or "end_turn",
            tool_calls = tool_calls,
            text = "".join(text_parts),
            usage = UsageStats(
                input_tokens = usage.input_tokens,
                output_tokens = usage.output_tokens,
                cache_read_input_tokens = cache_read,
                cache_creation_input_tokens = cache_create,
            ),
        )


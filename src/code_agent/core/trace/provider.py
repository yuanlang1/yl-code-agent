
import dataclasses
from datetime import UTC, datetime
import time
from typing import Any
from code_agent.core.events.bus import EventBus
from code_agent.core.llm.base import LlmProvider
from code_agent.core.llm.types import LlmResponse
from code_agent.core.trace.record import TraceRecord
from code_agent.core.trace.writer import TraceWriter

def _now() -> str:
    return datetime.now(UTC).isoformat()


class TracingProvider:
    def __init__(
        self,
        inner: LlmProvider,
        trace: TraceWriter,
        *,
        include_payload: bool = True
    ) -> None:
        self._inner = inner
        self._trace = trace
        self._include_payload = include_payload

    async def chat(
        self,
        messages: list[dict[str, object]],
        tool_schemas: list[dict[str, object]],
        bus: EventBus,
        run_id: str,
        *,
        step: int = 0
    ) -> LlmResponse:
        if self._include_payload:
            call_data = {
                "messages": messages,
                "tool_schemas": tool_schemas
            }
        else:
            call_data = {
                "messages_count": len(messages),
                "tool_count": len(tool_schemas)
            }

        self._trace.emit(
            TraceRecord(
                ts = _now(),
                direction = "CORE->LLM",
                layer = "llm",
                kind = "api_call",
                run_id = run_id,
                step = step,
                data = call_data
            )
        )

        start_time = time.monotonic()
        result = await self._inner.chat(
            messages = messages,
            tool_schemas = tool_schemas,
            bus = bus,
            run_id = run_id,
            step = step
        )
        latency_ms = int((time.monotonic() - start_time) * 1000)

        resp_data: dict[str, Any]
        if self._include_payload:
            resp_data = {
                "stop_reason": result.stop_reason,
                "text": result.text,
                "tool_calls": [dataclasses.asdict(tc) for tc in result.tool_calls],
                "usage": dataclasses.asdict(result.usage) if result.usage else {},
                "latency_ms": latency_ms
            }
        else:
            resp_data = {
                "stop_reason": result.stop_reason,
                "usage": dataclasses.asdict(result.usage) if result.usage else {},
                "latency_ms": latency_ms
            }
        
        self._trace.emit(
            TraceRecord(
                ts = _now(),
                direction = "LLM->CORE",
                layer = "llm",
                kind = "api_response",
                run_id = run_id,
                step = step,
                data = resp_data
            )
        )

        return result
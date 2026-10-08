
import asyncio
from datetime import UTC, datetime
import time

from anthropic import RateLimitError
from pydantic import ValidationError
from code_agent.core.bus.events import ToolCallFailedEvent, ToolCallFinishedEvent, ToolCallStartedEvent
from code_agent.core.events.bus import EventBus
from code_agent.core.llm.types import ToolCallBack
from code_agent.core.tools.base import ToolResult
from code_agent.core.tools.registry import ToolRegistry

_MAX_RETRIES = 2
_RETRY_BASE_S = 2.0
_RETRYABLE = ["runtime_error", "rate_limited"]

def _now() -> str:
    return datetime.now(UTC).isoformat()

async def _fail(
    bus: EventBus,
    run_id: str,
    tool_call: ToolCallBack,
    error_type: str,
    error_message: str,
    elapsed_ms: int,
    attempt: int = 1
) -> ToolResult:
    await bus.publish(
        ToolCallFailedEvent(
            run_id = run_id,
            tool_use_id = tool_call.id,
            tool_name = tool_call.name,
            error_type = error_type,
            error_message = error_message,
            elapsed_ms = elapsed_ms,
            attempt = attempt,
            ts = _now()
        )
    )

    return ToolResult(
        content = error_message,
        is_error = True,
        error_type = error_type
    )


async def invoke_tool(
    registry: ToolRegistry,
    tool_call: ToolCallBack,
    bus: EventBus,
    run_id: str,
    timeout: float = 10.0
) -> ToolResult:
    start_time = time.monotonic()

    def elapsed() -> int:
        return int((time.monotonic() - start_time) * 1000)

    await bus.publish(
        ToolCallStartedEvent(
            run_id = run_id, 
            tool_use_id = tool_call.id, 
            tool_name = tool_call.name, 
            params = tool_call.input, 
            ts = _now()
        )
    )

    tool = registry.get(tool_call.name)
    if tool is None:
        return await _fail(bus, run_id, tool_call,
            "runtime_error", f"unknown tool: {tool_call.name}",  elapsed())
    
    if tool.params_model is not None:
        try:
            tool.params_model.model_validate(dict(tool_call.input))
        except ValidationError as e:
            return await _fail(
                bus = bus,
                run_id = run_id, 
                tool_call = tool_call, 
                error_type = "schema_error", 
                error_message = str(e), 
                elapsed_ms = elapsed(), 
            )

    for attempt in (1, _MAX_RETRIES + 2):
        try:
            result = await asyncio.wait_for(tool.invoke(tool_call.input), timeout = timeout)
            if result.is_error:
                error_class = result.error_type or "runtime_error"
                error_message = result.content
            
            else:
                await bus.publish(
                    ToolCallFinishedEvent(
                        run_id = run_id, 
                        tool_use_id = tool_call.id, 
                        tool_name = tool_call.name, 
                        elapsed_ms = elapsed(), 
                        ts = _now()
                    )
                )
                return result
        except RateLimitError as e:
            error_class = "rate_limited"
            error_message = str(e)

        except TimeoutError as e:
            return await _fail(
                bus, run_id, tool_call, 
                "timeout", f"out of time:{timeout}", elapsed(), attempt
            )
        
        except Exception as e:
            error_class = "runtime_error"
            error_message = str(e)

        if attempt <= _MAX_RETRIES or error_class in _RETRYABLE:
            await bus.publish(
                ToolCallFailedEvent(
                    run_id = run_id,
                    tool_use_id = tool_call.id,
                    tool_name = tool.name,
                    error_type = error_class,
                    error_message = error_message,
                    elapsed_ms = elapsed(),
                    attempt = attempt,
                    ts = _now()
                )
            )

            await asyncio.sleep(_RETRY_BASE_S * (2 ** (attempt - 1)))
            continue
            
    return await _fail(
        bus = bus,
        run_id = run_id, 
        tool_call = tool_call, 
        error_type = error_class, 
        error_message = error_message, 
        elapsed_ms = elapsed(), 
        attempt = attempt
    )
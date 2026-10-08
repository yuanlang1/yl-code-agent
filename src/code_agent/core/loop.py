
import asyncio
from datetime import UTC, datetime

from code_agent.core.bus.events import StepFinishedEvent, StepStartedEvent
from code_agent.core.context import ExecutionContext
from code_agent.core.events.bus import EventBus
from code_agent.core.llm.base import LlmProvider
from code_agent.core.tools.invocation import invoke_tool
from code_agent.core.tools.registry import ToolRegistry

def _now() -> str:
    return datetime.now(UTC).isoformat()
    
class AgentLoop:
    def __init__(
        self,
        provider: LlmProvider,
        bus: EventBus,
        registry: ToolRegistry
    ) -> None:
        self._provider = provider
        self._bus = bus
        self._registry = registry

    async def run(
        self,
        context: ExecutionContext
    ) -> None:
        while not context.is_done():
            context.step += 1

            await self._bus.publish(
                StepStartedEvent(run_id = context.run_id, step = context.step, ts = _now())
            )

            try:
                resp = await self._provider.chat(
                    messages = context.messages, 
                    tool_schemas = self._registry.tool_schemas(),
                    bus = self._bus, 
                    run_id = context.run_id,
                    step = context.step
                )
            except asyncio.CancelledError:
                context.mark_failed("cancelled")
                raise
            
            except Exception:
                context.mark_failed("llm_error")
                raise

            block: list[dict[str, object]] = []
            
            if resp.text:
                block.append({
                    "type": "text", "text": resp.text
                })
            for tool in resp.tool_calls:
                block.append({
                    "type": "tool_use", "id": tool.id, "name": tool.name, "input": tool.input
                })
            
            context.add_assistant_message(block)

            if resp.stop_reason == "tool_use":
                for tool in resp.tool_calls:
                    result = await invoke_tool(
                        registry = self._registry, 
                        tool_call = tool, 
                        bus = self._bus, 
                        run_id = context.run_id
                    )
                    context.add_tool_result(
                        tool_use_id = tool.id, 
                        content = result.content, 
                        is_error = result.is_error
                    )

            if resp.stop_reason == "end_turn":
                context.result = resp.text or ""
                context.mark_success()
            elif context.step >= context.max_steps:
                context.mark_failed("exceeded_max_steps")

            await self._bus.publish(
                StepFinishedEvent(run_id = context.run_id, step = context.step, ts = _now())
            )

            

            

        

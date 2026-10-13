
import asyncio
from datetime import UTC, datetime
from logging import Logger
import logging

from code_agent.core.bus.events import StepFinishedEvent, StepStartedEvent
from code_agent.core.compact.compactor import Compactor
from code_agent.core.context import ExecutionContext
from code_agent.core.events.bus import EventBus
from code_agent.core.llm import provider
from code_agent.core.llm.base import LlmProvider
from code_agent.core.permissions import PermissionManager
from code_agent.core.tools.invocation import invoke_tool
from code_agent.core.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

def _now() -> str:
    return datetime.now(UTC).isoformat()
    
class AgentLoop:
    def __init__(
        self,
        provider: LlmProvider,
        bus: EventBus,
        registry: ToolRegistry,
        *,
        permission_manager: PermissionManager | None = None,
        session_id: str = "",
        compactor: Compactor | None = None,
        compact_threshold: float = 0.80
    ) -> None:
        self._provider = provider
        self._bus = bus
        self._registry = registry
        self._permission_manager = permission_manager
        self._session_id = session_id
        self._compactor = compactor
        self._compact_threshold = compact_threshold

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
                    step = context.step,
                    system = context.system_prompt(
                        "You are a helpful AI assistant. "
                        "Use the available tools to complete the user's goal. "
                        "When the goal is fully achieved, respond with a final answer "
                        "and do not call any more tools."
                    )
                )
            except asyncio.CancelledError:
                context.mark_failed("cancelled")
                raise
            
            except Exception:
                logger.exception(
                    "LLM call failed run_id=%s step=%d", context.run_id, context.step
                )
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
                        run_id = context.run_id,
                        permission_manager = self._permission_manager,
                        session_id = self._session_id
                    )
                    context.add_tool_result(
                        tool_use_id = tool.id, 
                        content = result.content, 
                        is_error = result.is_error
                    )
            elif resp.stop_reason == "max_tokens" and resp.tool_calls:
                for tc in resp.tool_calls:
                    context.add_tool_result(
                        tool_use_id = tc.id,
                        content = "Error: output token limit reached before this tool call could be completed. "
                                  "Please break the task into smaller steps and try again.",
                        is_error = True,
                    )

            if resp.stop_reason == "end_turn":
                context.result = resp.text or ""
                context.mark_success()
            elif context.step >= context.max_steps:
                context.mark_failed("exceeded_max_steps")

            if (
                not context.is_done()
                and resp.stop_reason == "tool_use"
                and self._compactor is not None
                and self._compact_threshold > 0
                and resp.usage is not None
                and resp.usage.context_pct >= self._compact_threshold
            ):
                await self._compactor.compact(context, self._provider)

            await self._bus.publish(
                StepFinishedEvent(run_id = context.run_id, step = context.step, ts = _now())
            )

            

            

        

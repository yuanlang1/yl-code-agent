
import asyncio
import json
from pydoc import cli
import sys
import time
from typing import Any
from pydantic import BaseModel

from code_agent.core.bus.events import LlmTokenEvent, RunFinishedEvent, RunStartedEvent, StepFinishedEvent, StepStartedEvent, ToolCallFailedEvent, ToolCallStartedEvent
from code_agent.core.config import AgentConfig
from code_agent.core.runner import AgentRunner
from code_agent.core.transport.socket_client import IpcError, SocketClient

class StdoutPrinter:
    def __init__(self) -> None:
        self._inline = False
        self._run_start: float = 0.0

    def _ensure_newline(self) -> None:
        if self._inline:
            print()
            self._inline = False

    async def handler(
        self,
        event: BaseModel
    ) -> None:
        if isinstance(event, RunStartedEvent):
            self._run_start = time.monotonic()
            print(f"[run] {event.run_id}")
        
        elif isinstance(event, StepStartedEvent):
            self._ensure_newline()
            print(f"[step {event.step}] planning...")

        elif isinstance(event, LlmTokenEvent):
            print(event.token, end = "", flush = True)
            self._inline = True

        elif isinstance(event, ToolCallStartedEvent):
            self._ensure_newline()
            params_str = json.dumps(event.params, ensure_ascii = True)
            print(f"[tool] {event.tool_name} {params_str}")

        elif isinstance(event, ToolCallFailedEvent):
            print(f"[tool] {event.tool_name} ✓ {event.elapsed_ms}")

        elif isinstance(event, ToolCallFailedEvent):
            print(f"[tool] {event.tool_name} ✗ {event.error_message}", file = sys.stderr)

        elif isinstance(event, StepFinishedEvent):
            self._ensure_newline()
            print(f"[step {event.step}] done")

        elif isinstance(event, RunFinishedEvent):
            self._ensure_newline()
            elapsed = time.monotonic() - self._run_start
            print(f"[run] {event.status} {event.steps} steps {elapsed:.1f}s")

async def _run_async(
    goal: str,
    config: AgentConfig
) -> int:
    client = SocketClient(config.host, config.port)
    try:
        await client.connect()
    except (ConnectionResetError, OSError):
        print(f"error: core not running ({config.host}:{config.port})", file=sys.stderr)
        return 1
    
    printer = StdoutPrinter
    finished = asyncio.Event
    exit_code = 0

    async def on_event(event: dict[str, Any]) -> None:
        nonlocal exit_code
        await printer.handler(event)
        if event.get("type") == "run.finished":
            if event.get("status") != "success":
                exit_code = 1
            finished.set()

    client.on_event(on_event)
    loop_task = asyncio.create_task(client.run_event_loop())
    
    try: 
        await client.send_command(
            "event.subscribe",
            {
                "topics": ["run.*", "step.*", "tool.*", "llm.token", "llm.usage"],
                "scope": "global"
            }
        )
        await client.send_command(
            "agent.run", 
            {
                "goal": goal
            }
        )
    except IpcError as e:
        print(f"error: {e}", file = sys.stderr)
        loop_task.cancel()
        await client.close()
        return 1

    await finished.wait()
    
    loop_task.cancel()
    try:
        await loop_task
    except asyncio.CancelledError:
        pass

    await client.close()
    return exit_code

def cmd_run(goal: str, config: AgentConfig) -> None:
    printer = StdoutPrinter()
    runner = AgentRunner(config, extra_handler = [printer.handler])

    try:
        asyncio.run(runner.run(goal))
    except KeyboardInterrupt:
        sys.exit(130)
from __future__ import annotations
import json
import sys

import code_agent
import asyncio
import time
from code_agent.core.bus.commands import PongResult
from code_agent.core.bus.envelope import JsonRpcError, JsonRpcSuccess
from code_agent.core.config import AgentConfig

def cmd_ping(config: AgentConfig) -> None:
    try:
        asyncio.run(_ping(config))
    except (ConnectionError, OSError):
        print(f"error: core not running ({config.host}:{config.port})", file = sys.stderr)
        sys.exit(1)

async def _ping(config: AgentConfig) -> None:
    t0 = time.monotonic()
    reader, writer = await asyncio.open_connection(config.host, config.port)

    request = {
        "jsonrpc": "2.0",
        "id": "cli-1",
        "method": "core.ping",
        "params": {
            "client": f"cli/{code_agent.__version__}"
        }
    }

    writer.write((json.dumps(request) + "\n").encode())
    await writer.drain()

    line = await asyncio.wait_for(reader.readline(), timeout = 10.0)
    latency_ms = int((time.monotonic() - t0) * 1000)

    writer.close()
    await writer.wait_closed()

    raw = json.loads(line)
    if "error" in raw:
        err = JsonRpcError.model_validate(raw)
        print(f"error: {err.error.code}, {err.error.message}", file = sys.stderr)
        sys.exit(1)

    response = JsonRpcSuccess.model_validate(raw)
    result = PongResult.model_validate(response.result)

    print(f"Pong server={result.server_version}, uptime={result.uptime_ms}ms, latency={latency_ms}ms")

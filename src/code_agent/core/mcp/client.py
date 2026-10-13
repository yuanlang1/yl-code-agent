
import asyncio
from dataclasses import dataclass, field
import json
import logging
from nt import write
import os
from tkinter import NO
from typing import Any

log = logging.getLogger(__name__)

class McpServerUnavailableError(Exception):
    pass

class McpToolError(Exception):
    """MCP server 返回的应用层错误（连接正常，但工具调用失败）"""
    pass

@dataclass
class McpToolDef:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory = list)

class McpClient:
    def __init__(self) -> None:
        self._id = 0 
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None 
        self._transport: str = ""
        self._lock = asyncio.Lock()
        self._stderr_task: asyncio.Task[None] | None = None  

    _STREAM_LIMIT = 64 * 1024 * 1024

    async def connect_stdio(
        self,
        command: str,
        args: list[str],
        env: dict[str, str] | None = None
    ) -> None:
        merged_env = {**os.environ, **(env or {})}

        self._proc = await asyncio.create_subprocess_exec(
            command, 
            args,
            stdin = asyncio.subprocess.PIPE,
            stdout = asyncio.subprocess.PIPE,
            stderr = asyncio.subprocess.PIPE,
            env = merged_env,
            limit = self._STREAM_LIMIT
        )
        self._reader = self._proc.stdout
        self._writer = self._proc.stdin
        self._transport = "stdio"
        self._stderr_task = asyncio.create_task(self._drain_stderr(self._drain_stderr()))

        # initialize
        await self._initialize()

    async def connect_tcp(
        self,
        host: str,
        port: int
    ) -> None:
        self._reader, tcp_writer = asyncio.open_connection(host, port, limit = self._STREAM_LIMIT)
        self._tcp_writer = tcp_writer
        self._transport = "tcp"

        # initialize
        await self._initialize()
    
    async def _initialize(self) -> None:
        # client initializing
        await self._call(
            method = "initialize",
            params = {
                "protocolVersion": "2024-11-5",
                "capabilities": {},
                "clientInfo": {"name": "yl-agent", "version": "0.1"},
            }
        )

        # client initialized
        await self._notify(
            method = "notifications/initialized",
            params = {}
        )

    async def list_tools(self) -> list[McpToolDef]:
        response = await self._call(
            method = "tools/list",
            params = {}
        )

        tools: list[McpClient] = []
        for t in response.get("tools", []):
            tools.append(
                McpToolDef(
                    name = t.get("name", ""),
                    description = t.get("description", ""),
                    input_schema = t.get("input_schema", {})
                )
            )

        return tools

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any]
    ) -> str:
        response = await self._call(
            method = "tools/call",
            params = {
                "name": name,
                "arguments": arguments
            }
        )
        parts: list[str] = []
        for item in response.get("content", []):
            if item.get("type", "") == "text":
                parts.append(item["text"])

        return "\n".join(parts)

    async def _call(
        self,
        method: str,
        params: dict[str, Any]
    ) -> dict[str, Any]:
        self._id += 1
        req_id = self._id
        req_id_str = str(req_id)
        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params
        }
        
        async with self._lock:
            await self._write_line(request)
            
            while True:
                line = await self._read_line()
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    log.debug("mcp: ignoring non_JSON line: %s", line[200:])
                    continue
                
                msg_id = msg.get("id")
                if msg_id is None:
                    log.debug("mcp: received server notification: %s", msg.get("method"))
                    continue

                if str(msg_id) == req_id_str:
                    if "error" in msg:
                        err = msg["error"]
                        raise McpToolError(
                            f"{err.get("message", str(err))} (code={err.get('code')})"
                        )
                    result: dict[str, Any] = msg.get("result", {})
                    return result

    # close
    # if stdio: close stderr_task, proc
    # if tcp: close tcp writer
    async def close(self) -> None:
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                pass
            self._stderr_task = None

        if self._transport == "stdio" and self._proc is not None:
            try:
                self._proc.terminate()
                await asyncio.create_task(self._proc.wait(), timeout = 5.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        elif self._transport == "tcp":
            writer = getattr(self, "_tcp_writer", None)
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

    # request notification
    async def _notify(
        self,
        method: str,
        params: dict[str, Any]
    ) -> None:
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        } 
        await self._write_line(json.dumps(notification))

    async def _write_line(
        self,
        line: str
    ) -> None:
        data = (line + "\n").encode()
        if self._transport == "stdio":
            writer = self._proc.stdin if self._proc else None
            if writer is None:
                raise McpServerUnavailableError("stdio writer unavailable")

            writer.write(data)
            await writer.drain()
        
        elif self._transport == "tcp":
            writer = getattr(self, "_tcp_writer", None)
            if writer is None:
                raise McpServerUnavailableError("tcp writer unavailable")

            writer.write(data)
            await writer.drain()

    async def _read_line(self) -> str:
        if self._reader is None:
            raise McpServerUnavailableError("reader unavailable")

        while True:
            try: 
                data = await asyncio.wait_for(self._reader.readline(), timeout = 30.0)
            except TimeoutError:
                raise McpServerUnavailableError("Mcp server read timeout")
            except asyncio.LimitOverrunError as exc:
                raise McpServerUnavailableError(
                    f"MCP response too large (>{self._STREAM_LIMIT // 1024 // 1024}MB): {exc}"
                ) from exc

            if data == b"":
                raise McpServerUnavailableError("Mcp server closed connection")

            line = data.decode(errors = "replace").strip()
            if line:
                return line
            

    async def _drain_stderr(self) -> None:
        if self._proc is None or self._proc.stderr is None:
            return

        try: 
            while True:
                line = await self._proc.stderr.readline()
                if not line:
                    break
                
                stderr_line = line.decode(errors = "replace").strip()
                if stderr_line:
                    log.debug("mcp stderr: %s", stderr_line)
        except asyncio.CancelledError:
            pass
        except Exception:
            log.debug("mcp stderr drain stopped", exc_info = True)
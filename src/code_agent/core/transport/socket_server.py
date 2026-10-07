
import asyncio
from codecs import StreamWriter
from contextvars import ContextVar
from datetime import UTC, datetime
import json
import logging
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ValidationError

from code_agent.core.bus.envelope import INTERNAL_ERROR, INVALID_PARAMS, INVALID_REQUEST, METHOD_NOT_FOUND, PARSE_ERROR, JsonRpcError, JsonRpcRequest, JsonRpcSuccess, make_error
from code_agent.core.trace.record import TraceRecord
from code_agent.core.trace.writer import TraceWriter
from code_agent.core.transport.ipc_boradcaster import IpcEventBroadcaster


type CommandHandler = Callable[dict[str, Any], Awaitable[Any]]

# 每个连接处理协程中，当前正在处理的 writer（供 handler 读取连接上下文）
_writer_var: ContextVar[asyncio.StreamWriter] = ContextVar("_writer_var")



logger = logging.getLogger(__name__)

def get_connection_writer() -> asyncio.StreamWriter:
    return _writer_var.get()

def _now() -> str:
    return datetime.now(UTC).isoformat()

_MAX_LINE_BYTES = 1 * 1024 * 1024

class SocketServer:
    def __init__(
        self,
        host: str,
        port: int,
        broadcaster: IpcEventBroadcaster | None = None,
        trace: TraceWriter | None = None
    ) -> None:
        self.host = host
        self.port = port
        self._handler: dict[str, CommandHandler] = {}
        self._server: asyncio.AbstractServer | None = None
        self._broadcaster = broadcaster
        self._trace = trace

    # 添加handler
    def registry(
        self,
        method: str,
        handler: CommandHandler
    ) -> None:
        self._handler[method] = handler

    # 启动server，如果端口已被占用退出
    async def start(self) -> str:
        try: 
            reader, writer = await asyncio.open_connection(self.host, self.port)
            writer.close()
            await writer.wait_closed()
            raise SystemExit(f"core already running at {self.host}:{self.port}")
        except (ConnectionError, OSError):
            pass
            
        self._server = await asyncio.start_server(
            self._handle_connection,
            host = self.host,
            port = self.port,
            limit = _MAX_LINE_BYTES,
        )

        return f"{self.host}:{self.port}"

    async def stop(self) -> None:
        if self._server is None:
            return

        self._server.close()
        await asyncio.wait_for(self._server.wait_closed(), timeout = 2.0)

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter
    ) -> None:
        addr = writer.get_extra_info("peername", "<unknown>")
        logger.debug("client connected: %s", addr)

        try:
            await self._read_loop(reader, writer)
        finally:
            if self._broadcaster is not None:
                self._broadcaster.unsubscribe(writer)
            writer.close()

            try:
                await asyncio.wait_for(writer.wait_closed(), timeout = 1.0)
            except TimeoutError:
                pass
            logger.debug("client disconnected: %s", addr)

    async def _read_loop(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter
    ) -> None:
        while True:
            try:
                line = await reader.readline()
            except asyncio.LimitOverrunError:
                await self._send(writer, make_error(None, INVALID_REQUEST, "Request too large"))
                return 
            
            if not line:
                return

            await self._handle_line(line, writer)
    
    async def _handle_line(
        self,
        line: bytes,
        writer: StreamWriter
    ) -> None:
        try:
            raw: Any = json.loads(line)
        except json.JSONDecodeError as e:
            await self._send(writer, make_error(None, PARSE_ERROR, f"Parse error: {e}"))
            return
            
        try:
            request = JsonRpcRequest.model_validate(raw)
        except ValidationError as e:
            await self._send(writer, make_error(None, INVALID_REQUEST, "Invalid Request", str(e)))
            return 

        if self._trace is not None:
            client_id = str(writer.get_extra_info("peername", "<unknown>"))
            self._trace.emit(
                TraceRecord(
                    ts = _now(),
                    direction = "CLIENT->CORE",
                    layer = "ipc",
                    kind = "command",
                    client_id = client_id,
                    data = {
                        "method": request.method,
                        "id": request.id,
                        "params": request.params
                    }
                )
            )

        handler = self._handler.get(request.method)
        if handler is None:
            await self._send(
                writer, make_error(request.id, METHOD_NOT_FOUND, f"Method not found: {request.method}")
            )
            return
        
        _writer_var.set(writer)
        try:
            result = await handler(request.params)
        except ValidationError as e:
            await self._send(writer, make_error(request.id, INVALID_PARAMS, "Invalid params"))
            return
        except Exception as e:
            logger.exception("handler %s raised %s", request.method, e)
            await self._send(writer, make_error(request.id, INTERNAL_ERROR, "Internal error"))
            return 
        
        result_data: Any = result.model_dump() if isinstance(result, BaseModel) else result
        await self._send(writer, JsonRpcSuccess(id = request.id, result = result_data))

    async def _send(
        self,
        writer: asyncio.StreamWriter,
        message: BaseModel
    ) -> None:
        writer.write(message.model_dump_json().encode() + b"\n")
        await writer.drain()
        if self._trace is not None:
            kind = "error" if isinstance(message, JsonRpcError) else "response"
            client_id = str(writer.get_extra_info("peername", "<unknown>"))
            self._trace.emit(
                TraceRecord(
                    ts = _now(),
                    direction = "CORE->CLIENT",
                    layer = "ipc",
                    kind = kind,
                    client_id = client_id,
                    data = message.model_dump()
                )
            )

    
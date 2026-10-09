from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import fnmatch
import json
import logging
from pathlib import Path
import signal
import sys
import time
from typing import Any

from pydantic import BaseModel

import code_agent
from code_agent.core.bus.commands import AgentRunCommand, AgentRunResult, EventSubscribeCommand, EventSubscribeResult, PongResult, SessionCloseCommand, SessionCloseResult, SessionCreateCommand, SessionCreateResult, SessionGetHistoryCommand, SessionGetHistoryResult, SessionSendMessageCommand, SessionSendMessageResult
from code_agent.core.bus.envelope import EventPushEnvelope
from code_agent.core.config import AgentConfig, get_config
from code_agent.core.events.bus import EventBus
from code_agent.core.logging_setup import setup_logging
from code_agent.core.runner import AgentRunner
from code_agent.core.runs import events_file, new_run_id, session_dir
from code_agent.core.session.manager import SessionManager
from code_agent.core.session.store import SessionStore
from code_agent.core.trace.record import TraceRecord
from code_agent.core.trace.writer import TraceWriter
from code_agent.core.transport.ipc_boradcaster import IpcEventBroadcaster
from code_agent.core.transport.socket_server import SocketServer, get_connection_writer


logger = logging.getLogger(__name__)

def _now() -> str:
    return datetime.now(UTC).isoformat()


class CoreApp:
    def __init__(self) -> None:
        self._start_time = time.monotonic()
        self._bus = EventBus()
        self._broadcaster: IpcEventBroadcaster | None = None
        self._config: AgentConfig | None = None
        self._trace: TraceWriter | None = None
        self._running_runs: set[asyncio.Task[None]] = set[asyncio.Task[None]]()
        self._sessions: SessionManager | None = None

    async def _ping_handler(
        self,
        params: dict[str, Any]
    ) -> PongResult:
        client = params.get("client", "unknown")
        logger.debug("ping from %s", client)

        return PongResult(
            server_version = code_agent.__version__,
            uptime_ms = int((time.monotonic() - self._start_time) * 1000),
            received_at = datetime.datetime.now(datetime.UTC).isoformat()
        )
    
    async def _agent_run_handler(
        self,
        params: dict[str, Any]
    ) -> AgentRunResult:
        assert self._sessions is not None

        print(f"request: {params}")
        cmd = AgentRunCommand.model_validate(params)
        session = await self._sessions.create(mode = "one_shot", title = cmd.goal[:40])
        run_id = new_run_id()
        run_task = asyncio.create_task(
            self._sessions.send_message(session_id = session.id, content = cmd.goal, run_id = run_id)
        )

        self._running_runs.add(run_task)
        run_task.add_done_callback(self._running_runs.discard())

        return AgentRunResult(run_id)

    async def _session_create_handler(
        self,
        params: dict[str, Any]
    ) -> SessionCreateResult:
        assert self._sessions is not None

        cmd = SessionCreateCommand.model_validate(params)
        session = await self._sessions.create(mode = cmd.mode, title = cmd.title)

        return SessionCreateResult(session_id = session.id, status = session.status)

    async def _session_send_handler(
        self,
        params: dict[str, Any]
    ) -> SessionSendMessageResult:
        assert self._sessions is not None

        cmd = SessionSendMessageCommand.model_validate(params)
        run_id = await self._sessions.send_message(cmd.session_id, cmd.content)

        return SessionSendMessageResult(run_id = run_id)

    async def _session_history_handler(
        self,
        params: dict[str, Any]
    ) -> SessionGetHistoryResult:
        assert self._sessions is not None

        cmd = SessionGetHistoryCommand.model_validate(params)
        messages = await self._sessions.get_history(cmd.session_id)

        return SessionGetHistoryResult(messages)

    async def _session_close_handler(
        self,
        params: dict[str, Any]
    ) -> SessionCloseResult:
        assert self._sessions is not None

        cmd = SessionCloseCommand.model_validate(params)
        await self._sessions.close(cmd.session_id)

        return SessionCloseResult(status = "closed")

    async def _subscribe_handler(
        self,
        params: dict[str, Any]
    ) -> EventSubscribeResult:
        cmd = EventSubscribeCommand.model_validate(params)
        writer = get_connection_writer()

        replayed_count = 0
        # 事件回放
        if cmd.replay_from_run is not None:
            replayed_count = await self._replay_events(
                run_id = cmd.replay_from_run, 
                writer = writer,
                topics = cmd.topics
            )
        
        sub_id = self._broadcaster.subscribe(writer, cmd.topics, cmd.scope)
        return EventSubscribeResult(
            subscription_id = sub_id,
            replayed_count = replayed_count
        )

    async def _trace_event_handler(
        self,
        event: BaseModel
    ) -> None:
        assert self._trace is not None
        
        event_dict = event.model_dump()
        self._trace.emit(
            TraceRecord(
                ts = _now(),
                direction = "CORE",
                layer = "event",
                kind = "event",
                run_id = event_dict.get("run_id"),
                data = event_dict
            )  
        )
    
    # 回放
    async def _replay_events(
        self,
        run_id: str, 
        writer: asyncio.StreamWriter,
        topics: list[str]
    ) -> int:
        path = events_file(run_id)
        if not path.exists():
            for candidate in Path(session_dir()).expanduser().glob(
                f"*/runs/{run_id}/events.jsonl"
            ):
                path = candidate
                break
        if not path.exists():
            return 0

        count = 0   
        for line in path.read_text().splitlines():
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
                
            event_type: str = event.get("type", "")
            if not any(fnmatch.fnmatch(event_type, p) for p in topics):
                continue
            
            envelope = EventPushEnvelope(event = event)
            writer.write(envelope.model_dump_json().encode() + b"\n")
            
            count += 1
        
        if count:
            await writer.drain()
        
        return count    

    async def run(self) -> None:
        self._start_time = time.monotonic()
        self._config = get_config()
        setup_logging(self._config)

        if self._config.trace.enabled:
            trace_path = Path(self._config.trace.file).expanduser()
            self._trace = TraceWriter(trace_path)
            await self._trace.start()
            self._bus.subscribe(self._trace_event_handler)

        self._broadcaster = IpcEventBroadcaster(trace = self._trace)
        self._bus.subscribe(self._broadcaster.handle)

        session_root = Path(session_dir()).expanduser()
        store = SessionStore(session_root)
        self._sessions = SessionManager(
            store = store,
            runner_factory = lambda: AgentRunner(self._config, bus = self._bus, trace = self._trace),
            bus = self._bus
        )        

        server = SocketServer(
            host = self._config.host, 
            port = self._config.port, 
            broadcaster = self._broadcaster,
            trace = self._trace
        )
        server.register("core.ping", self._ping_handler)
        server.register("agent.run", self._agent_run_handler)
        server.register("event.subscribe", self._subscribe_handler)
        server.register("session.create", self._session_create_handler)
        server.register("session.send_message", self._session_send_handler)
        server.register("session.get_history", self._session_history_handler)
        server.register("session.close", self._session_close_handler)

        # return host:port
        addr = await server.start()
        logger.info("agent-core %s listening %s", code_agent.__version__, addr)
        logger.info("config %s", self._config)

        loop = asyncio.get_running_loop()
        shutdown = asyncio.Event()

        # linux / macOs
        if sys.platform != "win32":
            loop.add_signal_handler(signal.SIGTERM, shutdown.set())

        try: 
            await shutdown.wait()
        finally:
            logger.info("shutting down")
            for run_task in list(self._running_runs):
                run_task.cancel()
            
            if self._running_runs:
                await asyncio.gather(*self._running_runs, return_exceptions = True)
            await server.stop()

            if self._trace is not None:
                await self._trace.stop()

# 同步入口：启动 CoreApp 事件循环
def run() -> None:
    asyncio.run(CoreApp().run())
    
        



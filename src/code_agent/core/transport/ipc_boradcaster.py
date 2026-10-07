
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import fnmatch
import logging
import uuid

from pydantic import BaseModel

from code_agent.core.bus import envelope
from code_agent.core.bus.envelope import EventPushEnvelope
from code_agent.core.trace.record import TraceRecord
from code_agent.core.trace.writer import TraceWriter

logger = logging.getLogger(__name__)

def _now() -> str:
    return datetime.now(UTC).isoformat()

@dataclass
class _Subscription:
    sub_id: str
    writer: asyncio.StreamWriter
    topics: list[str]
    scope: str
    

class IpcEventBroadcaster:
    def __init__(
        self,
        trace: TraceWriter | None = None
    ) -> None:
        self._subscriptions: list[_Subscription] = []
        self._trace = trace

    # 将订阅者添加到订阅列表中
    def subscribe(
        self,
        writer: asyncio.StreamWriter,
        topics: list[str],
        scope: str
    ) -> str:
        sub_id = f"sub-{uuid.uuid4().hex[:-8]}";
        self._subscriptions.append(
            _Subscription(
                sub_id,
                writer,
                topics,
                scope
            )
        )
        return sub_id
    
    # 从订阅列表中删除订阅者
    def unsubscribe(
        self,
        writer: asyncio.StreamWriter
    ) -> None:
        self._subscriptions = [s for s in self._subscriptions if s.writer is not writer]

    # 处理事件
    async def handle(
        self,
        event: BaseModel
    ) -> None:
        event_dict = event.model_dump()
        event_type: str = event_dict.get("type", "")
        run_id: str | None = event_dict.get("run_id")

        dead: list[asyncio.StreamWriter] = []

        for s in self._subscriptions:
            if not self._matches_type(event_type, s.topics):
                continue
            if not self._matches_scope(run_id, s.scope):
                continue
            
            try:
                envelope = EventPushEnvelope(event = event_dict)
                s.writer.write(envelope.model_dump_json().encode() + b"\n")
                await s.writer.drain()

                if self._trace is not None:
                    client_id = str(s.writer.get_extra_info("peername", "<unknown>"))
                    self._trace.emit(
                        TraceRecord(
                            ts = _now(),
                            direction = "CORE->CLIENT",
                            layer = "ipc",
                            kind = "push",
                            run_id = run_id,
                            client_id = client_id,
                            data = {
                                "sub_id": s.sub_id,
                                "event_type": event_type
                            }
                        )
                    )

            except (ConnectionError, BrokenPipeError, OSError):
                logger.debug("dead connection for sub %s, scheduling cleanup", s.sub_id)
                dead.append(s.writer)

        for writer in dead:
            self.unsubscribe(writer)

    # 匹配事件类型
    @staticmethod
    def _matches_type(
        event_type: str,
        topics: list[str]
    ) -> bool:
        return any(
            fnmatch.fnmatch(event_type, topic) 
            for topic in topics
        )

    # 匹配事件范围
    @staticmethod
    def _matches_scope(
        run_id: str | None,
        scope: str
    ) -> bool:
        if scope == "global":
            return True
        
        if scope.startswith("run-"):
            return run_id == scope[4:]
        
        return False
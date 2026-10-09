from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Callable
import uuid
from code_agent.core.bus.envelope import HandlerError
from code_agent.core.bus.events import SessionClosedEvent, SessionCreatedEvent, SessionMessageReceivedEvent, SessionResumedEvent, SessionWaitingForInputEvent
from code_agent.core.events.bus import EventBus
from code_agent.core.runner import AgentRunner
from code_agent.core.runs import new_run_id
from code_agent.core.session.model import Session, SessionMode
from code_agent.core.session.store import SessionStore

SESSION_NOT_FOUND = -32010
SESSION_CLOSED = -32011
SESSION_BUSY = -32012

def _now() -> str:
    return datetime.now(UTC).isoformat()

class SessionManager:
    def __init__(
        self,
        store: SessionStore,
        runner_factory: Callable[[], AgentRunner],
        bus: EventBus    
    ) -> None:
        self._store = store
        self._runner_factory = runner_factory
        self._bus = bus
        self._sessions: dict[str, Session] = {}
        self._lock: dict[str, asyncio.Lock] = {}

    async def create(
        self,
        mode: SessionMode,
        title: str = ""
    ) -> Session:
        session_id = f"sess-{uuid.uuid4().hex[:12]}"
        ts = _now()

        session = Session(
            id = session_id,
            mode = mode,
            status = "active",
            title = title,
            created_at = ts,
            updated_at = ts,
            run_ids = []  
        )
        self._sessions[session_id] = session
        self._lock[session_id] = asyncio.Lock()
        self._store.write_meta(session)

        await self._bus.publish(
            SessionCreatedEvent(
                session_id = session_id,
                mode = mode,
                ts = ts
            )
        )

        return session

    def _get_session(
        self,
        session_id: str
    ) -> Session:
        session = self._sessions.get(session_id)
        if session is None:
            raise HandlerError(SESSION_NOT_FOUND, "session not found")
        
        return session

    async def send_message(
        self,
        session_id: str,
        content: str,
        *,
        run_id: str | None = None
    ) -> str:
        session = self._get_session(session_id)
        lock = self._lock[session_id]
        if lock.locked():
            raise HandlerError(SESSION_BUSY, "session busy")

        async with lock:
            if session.status == "closed":
                raise HandlerError(SESSION_CLOSED, "session already closed")
            
            if session.status == "waiting_for_input":
                await self._bus.publish(
                    SessionResumedEvent(session_id = session_id, ts = _now())
                )
            self._store.append_message(
                session_id = session_id,
                role = "user",
                content = content
            )

            await self._bus.publish(
                SessionMessageReceivedEvent(
                    session_id = session_id, 
                    content = content, 
                    ts = _now() 
                )
            )

            if not session.title:
                session.title = content[:40]
            
            run_id = run_id or new_run_id()
            session.run_ids.append(run_id)
            session.updated_at = _now()
            self._store.write_meta(session)

            runner = self._runner_factory()
            await runner.run_and_capture(
                goal = content,
                run_id = run_id,
                session = session,
                store = self._store
            )
            
            session.updated_at = _now()
            if session.mode == "one_shot":
                session.status = "closed"
                await self._bus.publish(
                    SessionClosedEvent(session_id = session_id, ts = _now())
                )
            else:
                session.status = "waiting_for_input"
                await self._bus.publish(
                    SessionWaitingForInputEvent(
                        session_id = session_id, 
                        last_run_id = run_id, 
                        ts = _now()
                    )
                )

            self._store.write_meta(session)
            return run_id    

    async def close(
        self,
        session_id: str
    ) -> None:
        session = self._get_session(session_id)
        lock = self._lock[session_id]

        if lock.locked():
            raise HandlerError(SESSION_BUSY, "session busy")
        
        async with lock:
            session.status = "closed"
            session.updated_at = _now()
            self._store.write_meta(session)

            await self._bus.publish(
                SessionClosedEvent(session_id = session_id, ts = _now())
            )

    async def get_history(
        self,
        session_id: str
    ) -> list[dict[str, Any]]:
        session = self._get_session(session_id)
        return self._store.read_messages(session_id)

                    
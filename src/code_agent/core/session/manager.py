from __future__ import annotations

from ast import arguments
import asyncio
from datetime import UTC, datetime
from typing import Any, Callable
import uuid
from code_agent.core.bus.commands import SessionCompactResult
from code_agent.core.bus.envelope import HandlerError
from code_agent.core.bus.events import SessionClosedEvent, SessionCreatedEvent, SessionMessageReceivedEvent, SessionResumedEvent, SessionWaitingForInputEvent, SkillInvokedEvent
from code_agent.core.compact.compactor import Compactor
from code_agent.core.events.bus import EventBus
from code_agent.core.llm import provider
from code_agent.core.llm.base import LlmProvider
from code_agent.core.runner import AgentRunner
from code_agent.core.runs import new_run_id, session_dir
from code_agent.core.session.model import Session, SessionMode
from code_agent.core.session.store import SessionStore
from code_agent.core.skills import SkillLoader

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
        bus: EventBus,
        provider: LlmProvider | None = None
    ) -> None:
        self._store = store
        self._runner_factory = runner_factory
        self._bus = bus
        self._sessions: dict[str, Session] = {}
        self._lock: dict[str, asyncio.Lock] = {}
        self._provider = provider
        self._skill_loader = SkillLoader()

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

            goal = content
            system_prompt_override: str | None = None
            tool_whitelist: list[str] | None = None
            if goal.startswith("/"):
                parts = content[1:].split(None, 1)
                skill_name = parts[0]
                arguments = parts[1] if len(parts) > 1 else ""  
                skill = self._skill_loader.resolve(skill_name)

                if skill is not None:
                    goal = self._skill_loader.render_prompt(skill, arguments)
                    system_prompt_override = skill.system_prompt_template
                    tool_whitelist = skill.allowed_tools or None

                    await self._bus.publish(
                        SkillInvokedEvent(
                            skill_name = skill_name,
                            arguments = arguments,
                            run_id = run_id,
                            ts = _now()
                        )
                    )


            runner = self._runner_factory()
            await runner.run_and_capture(
                goal = content,
                run_id = run_id,
                session = session,
                store = self._store,
                system_prompt_override = system_prompt_override,
                tool_whitelist = tool_whitelist
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

    async def compact(
        self,
        session_id: str,
        focus: str = ""
    ) -> Any:
        session = self._sessions.get(session_id)
        lock = self._lock[session_id]
        if lock.locked():
            raise HandlerError(SESSION_BUSY, "session busy")
        
        if self._provider is None:
            raise HandlerError(-32020, "provider not available for compaction.")

        async with lock:
            messages = self._store.read_messages(session_id)
            session_dir = self._store.session_dir(session_id)
            compactor = Compactor(self._bus, session_dir, session_id)

            result = await compactor.compact_messages(messages, self._provider, focus)
            if result is None:
                raise HandlerError(-32020, "compaction failed or not beneficial")

            self._store.write_compacted(
                session_id = session.id,
                messages = [
                    {"role": "user", "content": result.summary_text},
                    {"role": "assistant", "content": "Understood, I'll continue from this summary"}
                ]
            )

            return SessionCompactResult(
                summary_tokens = result.original_token_estimate,
                saved_tokens = max(0, result.original_token_estimate - result.summary_tokens)
            )

    

                    
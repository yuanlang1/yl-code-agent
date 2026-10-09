
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from typing import Any

from code_agent.core.session.model import Session

logger = logging.getLogger(__name__)

MessageContent = str | list[dict[str, Any]]

def _now() -> str:
    return datetime.now(UTC).isoformat()

class SessionStore:
    def __init__(
        self,
        root: Path
    ) -> None:
        self._root = root.expanduser()
        self._root.mkdir(parents = True, exist_ok = True)

    def session_dir(
        self,
        session_id: str
    ) -> Path:
        return self._root / session_id

    def runs_dir(
        self,
        session_id: str
    ) -> Path:
        return self.session_dir(session_id) / "runs"

    def write_meta(
        self,
        session: Session
    ) -> None:
        path = self.session_dir(session.id)
        path.mkdir(parents = True, exist_ok = True)

        (path / "meta.json").write_text(
            json.dumps(session.to_dict(), ensure_ascii = False, indent = 2),
            encoding = "utf-8"
        )

    def read_meta(
        self,
        session_id: str
    ) -> Session:
        data = json.loads(
            self.session_dir(session_id / "meta.json").read_text(encoding = "utf-8")
        )

        return Session.from_dict(data)

    def append_message(
        self,
        session_id: str,
        role: str,
        content: MessageContent,
        run_id: str | None = None
    ) -> None:
        row: dict[str, Any] = {
            "ts": _now(),
            "role": role,
            "content": content
        }

        if run_id is None:
            row["run_id"] = run_id
        
        path = self.session_dir(session_id)
        path.mkdir(parents = True, exist_ok = True)
        with (path / "thread.jsonl").open("a", encoding = "utf-8") as f:
            f.write(json.dumps(row, ensure_ascii = False) + "\n") 

    def append_messages(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        run_id: str
    ) -> None:
        for message in messages:
            self.append_message(
                session_id = session_id,
                role = str(message["role"]),
                content = message["content"],
                run_id = run_id
            )

    def read_messages(
        self,
        session_id: str
    ) -> list[dict[str, Any]]:
        path = self.session_dir(session_id) / "thread.jsonl"
        if not path.exists():
            return []

        messages: list[dict[str, Any]] = []
        for line_no, line in enumerate(
            path.read_text(encoding = "utf-8").splitlines(), 
            start = 1
        ):
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError: 
                logger.warning("skip broken thread row session_id=%s line=%s", session_id, line_no)
                continue
            
            role = row.get("role")
            if role not in ("user", "assistant"):
                logger.warning("skip unknown thread role session_id=%s line=%s role=%s", session_id, line, role)
                continue

            messages.append({
                "role": role,
                "content": row.get("content", "")
            })

        return self._trim_orphan_tool_use(messages)
    
    def _trim_orphan_tool_use(
        self,
        messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        pending: set[str] = set()
        last_balanced = 0
        for idx, msg in enumerate(messages, start = 1):
            content = msg.get("content")
            if isinstance(content, list):
                role = msg.get("role")
                if role == "assistant":
                    for block in content:
                        if block.get("type") == "tool_use":
                            pending.add(str(block.get("id", "")))
                if role == "user":
                    for block in content:
                        if block.get("type") == "tool_result":
                            pending.discard(str(block.get("tool_use_id", "")))
                
            if not pending:
                last_balanced = idx

        if pending:
            logger.warning("trim orphan tool_use blocks from thread")
            return messages[:last_balanced]
        
        return messages

    
    def read_notes(
        self,
        session_id: str
    ) -> str:
        path = self.session_dir(session_id) / "notes.md"
        if not path.exists():
            return ""
        
        return path.read_text(encoding = "utf-8")

    def append_notes(
        self,
        session_id: str,
        content: str,
        run_id: str
    ) -> None:
        path = self.session_dir(session_id)
        path.mkdir(parents = True, exist_ok = True)

        with (path / "notes.md").open("a", encoding = "utf-8") as f:
            f.write(f"## Note ({_now()}, {run_id}) \n{content}\n\n")
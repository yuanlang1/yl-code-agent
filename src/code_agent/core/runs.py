
from datetime import UTC, datetime
from pathlib import Path
import uuid

RUNS_DIR = Path("runs")
SESSION_DIR = Path("sessions")

# 返回指定 run_id 对应的目录路径
def run_dir(run_id: str) -> Path:
    return RUNS_DIR / run_id

def session_dir() -> Path:
    return SESSION_DIR

# 返回指定 run_id 的事件日志文件路径
def events_file(run_id: str) -> Path:
    return run_dir(run_id) / "events.jsonl"

def new_run_id() -> str:
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    suffix = uuid.uuid4().hex[:6]
    return f"{ts}-{suffix}"


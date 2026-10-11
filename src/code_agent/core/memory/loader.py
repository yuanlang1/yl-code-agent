
from pathlib import Path


def load_context_file(path: Path) -> str:
    p = path.expanduser()

    if not p.exists():
        return ""
    
    return p.read_text(encoding = "utf-8").strip()
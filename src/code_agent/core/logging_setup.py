from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
import sys

from code_agent.core.config import AgentConfig


_TEXT_FMT = 'level=%(levelname)s ts=%(asctime)s source=%(name)s msg="%(message)s"'
_JSON_FMT = '{"level":"%(levelname)s","ts":"%(asctime)s","source":"%(name)s","msg":"%(message)s"}'

# 配置logger, 设置level, formatter, handler(stderr handler and file handler(可滚动))
def setup_logging(config: AgentConfig) -> None:
    level = getattr(logging, config.logging.level.upper(), logging.INFO)
    format = _JSON_FMT if config.logging.format == "json" else _TEXT_FMT
    formatter = logging.Formatter(format, datefmt = "%Y-%m-%dT%H:%M:%S")

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    
    root.addHandler(stderr_handler)

    if config.logging.file:
        log_path = Path(config.logging.file).expanduser()
        log_path.parent.mkdir(parents = True, exist_ok = True)

        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8"
        )
        file_handler.setFormatter(formatter)

        root.addHandler(file_handler)


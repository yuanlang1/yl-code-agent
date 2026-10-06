from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import tomllib
from typing import Any
from dotenv import load_dotenv

# 根目录下
_PROJECT_DIR = Path(__file__).resolve().parents[3]
_AGENT_DIR =  _PROJECT_DIR / ".agent"

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 7437
_DEFAULT_LOG_LEVEL = "DEBUG"
_DEFAULT_LOG_FILE =  _AGENT_DIR / "logs" / "core.log"
_DEFAULT_LOG_FORMAT = "text"
_DEFAULT_CONFIG_PATH = _AGENT_DIR / "config.toml"
_DEFAULT_MAX_STEPS = 20
_DEFAULT_MODEL = "claude-sonnet-4-6"

@dataclass
class LoggingConfig:
    level: str = _DEFAULT_LOG_LEVEL
    file: str = _DEFAULT_LOG_FILE
    format: str = _DEFAULT_LOG_FORMAT

@dataclass
class LoopConfig:
    max_steps: int = _DEFAULT_MAX_STEPS

@dataclass
class LlmConfig:
    default_model: str = _DEFAULT_MODEL
    router: str = "static"

@dataclass
class AgentConfig:
    host: str = _DEFAULT_HOST
    port: str = _DEFAULT_PORT
    logging: LoggingConfig = field(default_factory = LoggingConfig)
    loop: LoopConfig = field(default_factory = LoopConfig)
    llm: LlmConfig = field(default_factory = LlmConfig)

# 从config.toml中读取config
def get_config() -> AgentConfig:
    config = AgentConfig()

    load_dotenv(".env", override=False)
    config_path = Path(os.environ.get("AGENT_CONFIG", _DEFAULT_CONFIG_PATH)).expanduser()

    if config_path.exists():
        try:
            with open(config_path, "rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise SystemError(f"Config parse error ({config_path}): {e}") from e
        _apply_toml(config, data)
    
    _apply_env(config)
    return config

# 从toml读取参数，写入config中
def _apply_toml(
    config: AgentConfig,
    data: dict[str, Any]
) -> None:
    unknown = set(data.keys()) - {"core", "logging"}
    if unknown:
        raise SystemExit(f"Unknown top-level config keys: {', '.join(sorted(unknown))}")

    if "core" in data:
        core = data["core"]
        if not isinstance(core, dict):
            raise SystemExit("Config error: [core] must be a table")

        unknown_core: set[str] = set(core.keys()) - {"host", "port"}
        if unknown_core:
            raise SystemExit(f"Unknown [core] keys: {', '.join(sorted(unknown_core))}")

        if "host" in core:
            val = core["host"]
            if not isinstance(val, str):
                raise SystemExit("Config error: core.host must be a string")
            config.host = val
        if "port" in core:
            val = core["port"]
            if not isinstance(val, int):
                raise SystemExit("Config error: core.port must be an integer")
            config.port = val
    
    if "logging" in data:
        log = data["logging"]
        if not isinstance(log, dict):
            raise SystemExit("Config error: [logging] must be a table")

        unknown_log: set[str] = set(log.keys()) - {"level", "file", "format"}
        if unknown_log:
            raise SystemExit(f"Unknown [logging] keys: {', '.join(sorted(unknown_log))}")

        for key in ("level", "file", "format"):
            if key in log:
                val = log[key]
                if not isinstance(val, str):
                    raise SystemExit(f"Config error: logging.{key} must be a string")
                setattr(config.logging, key, val)
    if "loop" in data:
        loop = data["loop"]
        if not isinstance(loop, dict):
            raise SystemExit("Config error: [loop] must be a table")

        unknown_loop: set[str] = set(loop.keys()) - {"max_steps"}

        if unknown_loop:
            raise SystemExit(f"Unknown [loop] keys: {', '.join(sorted(unknown_loop))}")

        if "max_steps" in loop:
            val = loop["max_steps"]
            if not isinstance(val, int) or val <= 0:
                raise SystemExit("Config error: loop.max_steps must be a positive integer")
            config.loop.max_steps = val

    if "llm" in data:
        llm = data["llm"]
        if not isinstance(llm, dict):
            raise SystemExit("Config error: [llm] must be a table")

        unknown_llm: set[str] = set(llm.keys()) - {"default_model", "router"}

        if unknown_llm:
            raise SystemExit(f"Unknown [llm] keys: {', '.join(sorted(unknown_llm))}")

        if "default_model" in llm:
            val = llm["default_model"]
            if not isinstance(val, str):
                raise SystemExit("Config error: llm.default_model must be a string")
            config.llm.default_model = val

        if "router" in llm:
            val = llm["router"]
            if not isinstance(val, str):
                raise SystemExit("Config error: llm.router must be a string")
            config.llm.router = val


# 优先环境变量，如果有就用环境变量
def _apply_env(config: AgentConfig) -> None:
    host = os.environ.get("AGENT_HOST")
    if host is not None:
        config.host = host

    port = os.environ.get("AGENT_PORT")
    if port is not None:
        try:
            config.port = port
        except ValueError as e:
            raise SystemError(f"Config: AGENT_PORT must be an Integer, got: {port!r}")

    log_level = os.environ.get("AGENT_LOG_LEVEL")
    if log_level is not None:
        config.logging.level = log_level

    log_file = os.environ.get("AGENT_LOG_FILE")
    if log_file is not None:
        config.logging.file = log_file

    log_format = os.environ.get("AGENT_LOG_FORMAT")
    if log_format is not None:
        config.logging.format = log_format

    max_steps_str = os.environ.get("LOOP_MAX_STEPS")
    if max_steps_str is not None:
        try:
            val = int(max_steps_str)
            if val <= 0:
                raise SystemExit(
                    "Config error: LOOP_MAX_STEPS must be a positive integer,"
                    f" got: {max_steps_str!r}"
                )
            config.loop.max_steps = val
            
        except ValueError:
            raise SystemExit(
                f"Config error: LOOP_MAX_STEPS must be an integer, got: {max_steps_str!r}"
            )

    default_model = os.environ.get("LOOP_LLM_DEFAULT_MODEL")
    if default_model is not None:
        config.llm.default_model = default_model
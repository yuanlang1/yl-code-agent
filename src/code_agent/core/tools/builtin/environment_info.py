from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import tomllib
from pathlib import Path
from pydantic import BaseModel, ConfigDict
from code_agent.core.tools.base import BaseTool, ToolResult


class EnvironmentInfoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EnvironmentInfoTool(BaseTool):
    name = "environment_info"

    description = (
        "Get information about the current execution environment, "
        "including operating system, shell, Python version, "
        "working directory, project configuration and available commands. "
        "Use this tool to determine compatible shell commands "
        "and Python syntax before executing code."
    )

    params_model = EnvironmentInfoParams
    input_schemas: dict[str, object] = (
        params_model.model_json_schema()
    )

    async def invoke(
        self,
        params: dict[str, object],
    ) -> ToolResult:
        self.params_model.model_validate(params)

        cwd = Path.cwd()

        # 检测默认 Shell
        if os.name == "nt":
            shell = os.environ.get("COMSPEC", "cmd.exe")
        else:
            shell = "/bin/sh"

        # 获取基础环境
        info = {
            "os": {
                "system": platform.system(),
                "release": platform.release(),
                "architecture": platform.machine(),
            },
            "shell": shell,
            "python": {
                "version": platform.python_version(),
                "executable": sys.executable,
            },
            "cwd": str(cwd),
            "available_commands": {
                name: shutil.which(name) is not None
                for name in (
                    "python",
                    "uv",
                    "git",
                    "ruff",
                    "mypy",
                    "pytest",
                )
            },
        }

        # 读取项目配置
        pyproject = cwd / "pyproject.toml"

        if pyproject.is_file():
            try:
                with pyproject.open("rb") as f:
                    config = tomllib.load(f)

                project = config.get("project", {})
                tools = config.get("tool", {})

                info["project"] = {
                    "name": project.get("name"),
                    "requires_python": project.get("requires-python"),
                    "configured_tools": list(tools.keys()),
                    "ruff": tools.get("ruff", {}),
                    "mypy": tools.get("mypy", {}),
                }

            except (OSError, tomllib.TOMLDecodeError) as exc:
                info["project"] = {
                    "error": str(exc)
                }
        else:
            info["project"] = None

        return ToolResult(
            content = json.dumps(
                info,
                ensure_ascii = False,
                indent = 2,
                default = str,
            )
        )
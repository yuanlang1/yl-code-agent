
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field
from code_agent.core.tools.base import BaseTool, ToolResult

_MAX_DEPTH = 4
_MAX_ENTRIES = 200

class ListDirParams(BaseModel):
    model_config = ConfigDict(extra = "forbid")
    path: str = Field(
        default = ".",
        description = "Relative path to the directory (default '.')."
    )
    depth: int = Field(
        default = 2,
        ge = 1,
        le = _MAX_DEPTH,
        description = f"How many levels deep to recurse (default 2, max {_MAX_DEPTH})."
    )

class ListDirTool(BaseTool):
    name = "list_dir"
    description = (
        "List the contents of a directory as a tree. "
        "Path must be relative to the current working directory. "
        "Hidden entries (starting with .) are included. "
        f"Maximum depth is {_MAX_DEPTH}, maximum total entries is {_MAX_ENTRIES}."
    )
    params_model = ListDirParams
    input_schemas: dict[str, object] = params_model.model_json_schema()

    async def invoke(
        self, 
        params: dict[str, object]
    ) -> ToolResult:
        validated = self.params_model.model_validate(params)
        path_str = validated.path
        max_depth = validated.depth

        if ".." in Path(path_str).parts:
            raise PermissionError(f"path traversal not allowed: {path_str}")

        root = Path(path_str)
        if not root.exists():
            raise FileNotFoundError(f"no such directory: {path_str}")
        if not root.is_dir():
            raise NotADirectoryError(f"not a directory: {path_str}")

        lines: list[str] = [str(root) + "/"]
        count = 0

        def _walk(directory: Path, depth: int, prefix: str) -> None:
            nonlocal count
            if depth > max_depth or count >= _MAX_ENTRIES:
                return
            entries = sorted(directory.iterdir(), key=lambda e: (e.is_file(), e.name))
            for i, entry in enumerate(entries):
                if count >= _MAX_ENTRIES:
                    lines.append(f"{prefix}... (truncated)")
                    return
                connector = "└── " if i == len(entries) - 1 else "├── "
                suffix = "/" if entry.is_dir() else ""
                lines.append(f"{prefix}{connector}{entry.name}{suffix}")
                count += 1
                if entry.is_dir() and depth < max_depth:
                    extension = "    " if i == len(entries) - 1 else "│   "
                    _walk(entry, depth + 1, prefix + extension)

        _walk(root, 1, "")
        return ToolResult(content = "\n".join(lines))




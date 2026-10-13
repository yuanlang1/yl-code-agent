
from dataclasses import dataclass, field
from pathlib import Path
import re


@dataclass
class SKill:
    name: str
    description: str
    system_prompt_template: str
    allowed_tools: list[str] = field(default_factory = list)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

def _parse_skill_file(path: Path) -> SKill:
    text = path.read_text(encoding = "utf-8")
    name = path.stem
    description = ""
    allowed_tools: list[str] = []
    body = text

    m = _FRONTMATTER_RE.match(text)
    if m:
        front = m.group(1)
        body = text[m.end():]
        lines = front.splitlines()

        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            if stripped.startswith("name:"):
                name = stripped[len("name:"):].strip().strip('"').strip("'")
            
            elif stripped.startswith("description:"):
                val = stripped[len("description:"):].strip().strip('"').strip("'")
                # YAML 块标量：> (折叠) 或 | (保留换行)，后续缩进行是内容
                if val in (">", "|"):
                    fold = val == ">"
                    parts: list[str] = []
                    i += 1
                    while i < len(lines) and (lines[i].startswith(" ") or lines[i].startswith("\t")):
                        parts.append(lines[i].strip())
                        i += 1
                    description = (" ".join(parts) if fold else "\n".join(parts)).strip()
                    continue
                else:
                    description = val
            
            elif stripped.startswith("allowed_tools:"):
                pass
            
            elif stripped.startswith("- "):
                allowed_tools.append(stripped[2:].strip())
            
            i += 1

    return SKill(
        name = name,
        description = description,
        system_prompt_template = body.strip(),
        allowed_tools = allowed_tools
    )


class SkillLoader:
    _BUILTIN_DIR = Path(__file__).expanduser() / "builtin"

    def resolve(
        self,
        name: str
    ) -> SKill | None:
        for path in self._search_path(name):
            if path.exists():
                try:
                    return _parse_skill_file(path)
                except Exception:
                    return None
        
        return None

    def _search_path(
        self,
        name: str
    ) -> list[Path]:
        dirs = [
            Path(".agent/skills"),
            Path("~/.agent/skills").expanduser(),
            self._BUILTIN_DIR
        ]
        paths: list[str] = []

        for d in dirs:
            paths.append(d / f"{name}.md")
            paths.append(d / name / f"{name}.md")
        
        return paths
    
    def list_all(self) -> list[str]:
        seen: dict[str, None] = {}

        for d in [
            Path(".agent/skills"),
            Path("~/.agent/skills").expanduser(),
            self._BUILTIN_DIR
        ]:
            if d.exists():
                for f in sorted(d.glob("*.md")):
                    seen[f.stem] = None
                for f in sorted(d.glob("*/SKILL.md")):
                    seen[f.parent.stem] = None

        return list(seen)

    def list_all_skills(self) -> list[SKill]:
        seen: dict[str, SKill] = {}

        for d in [
            Path(".agent/skills"),
            Path("~/.agent/skills").expanduser(),
            self._BUILTIN_DIR
        ]:
            if d.exists():
                for f in sorted(d.glob("*.md")):
                    try:
                        skill = _parse_skill_file(f)
                        seen[f.stem] = skill
                    except Exception:
                        pass
                for f in sorted(d.glob("*/SKILL.md")):
                    try:
                        skill = _parse_skill_file(f)
                        seen[f.stem] = skill
                    except Exception:
                        pass
        
        return list(seen.values())

    def render_prompt(
        self,
        skill: SKill,
        arguments: str
    ) -> str:
        return skill.system_prompt_template.replace("$ARGUMENTS", arguments)
        
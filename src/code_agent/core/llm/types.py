
from dataclasses import dataclass, field


@dataclass
class UsageStats:
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

@dataclass
class ToolCallBack:
    id: str
    name: str
    input: dict[str, object]

@dataclass
class LlmResponse:
    stop_reason: str
    tool_calls: list[ToolCallBack] = field(default_factory = list)
    text: str = ""
    usage: UsageStats | None = None
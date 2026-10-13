from __future__ import annotations

import logging
from code_agent.core.config import McpServerConfig
from code_agent.core.mcp.client import McpClient
from code_agent.core.mcp.tool import McpTool
from code_agent.core.tools.registry import ToolRegistry

log = logging.getLogger(__name__)

class McpServerManager:
    def __init__(self) -> None:
        self._clients: dict[str, McpClient] = {}
        self._tools: list[McpTool] = []

    # 连接mcp server，获取tools
    async def start_all(
        self,
        servers: list[McpServerConfig]
    ) -> None:
        for cfg in servers:
            try:
                client = await self._connect(cfg)
                tool_defs = client.list_tools()
                for tool_def in tool_defs:
                    self._tools.append(
                        McpTool(client, cfg.name, tool_def)
                    )
                self._clients[cfg.name] = client

                log.info(
                    "mcp: server'%s' connected, %s tool(s) discovered.", 
                    cfg.name, len(tool_defs)
                )
            except Exception:
                log.exception("mcp: server '%s' failed to start, skipping.", cfg.name)
    
    def registry(
        self,
        registry: ToolRegistry
    ) -> None:
        for tool in self._tools:
            registry.register(tool)

    def get_tools(self) -> list[McpTool]:
        return list(self._tools)

    # 暂停所有client
    async def stop_all(self) -> None:
        for name, client in list(self._clients.items()):
            try: 
                await client.close()
                log.info("mcp: server '%s' closed", name)

            except Exception:
                log.warning("mcp: error closing server '%s'", name)

        self._clients.clear()

    # 启动单个client
    async def _connect(
        self,
        cfg: McpServerConfig
    ) -> McpClient:
        client = McpClient()
        if cfg.transport == "stdio":
            if not cfg.command:
                raise ValueError(f"mcp server '{cfg.name}': stdio transport requires 'command'")

            await client.connect_stdio(
                command = cfg.command,
                args = cfg.args,
                env = cfg.env or None  
            )
        
        elif cfg.transport == "tcp":
            await client.connect_tcp(
                host = cfg.host,
                port = cfg.port
            )

        else:
            raise ValueError(f"mcp server '{cfg.name}': unknow transport '{cfg.transport}'")

        return client

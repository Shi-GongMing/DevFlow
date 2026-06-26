# 06 — MCP 协议集成

> **面试问题**："Agent 怎么调用外部工具？为什么选 MCP 而不是自定义协议？"
> **源文件**：[devflow/mcp/](../devflow/mcp/) (3个文件)
> **两层视角**：DevFlow 是 MCP 的**实现者**（写 client 端），OpsPilot 是 MCP 的**消费者**（用别人写的 client）

---

## 一、MCP 在 DevFlow 中的位置

```
Agent 主循环
  └── ToolRegistry
        ├── 内置工具 (Bash, ReadFile, WriteFile, ...)
        └── MCP 工具 (MCPToolWrapper)
              └── MCPManager
                    ├── MCPClient → MCP Server A (stdio)
                    ├── MCPClient → MCP Server B (HTTP/SSE)
                    └── MCPClient → MCP Server C (HTTP)
```

---

## 二、三层架构

### 2.1 MCPClient —— 连接管理

```python
class MCPClient:
    # 管理单个 MCP server 的完整生命周期
    def __init__(self, config: MCPServerConfig):
        self.config = config          # name, command, args, url, transport
        self._session = None          # JSON-RPC 会话

    async def connect(self):
        # stdio 模式：subprocess MCP server 进程, stdin/stdout JSON-RPC
        # HTTP 模式：httpx 连接到 MCP server URL
        # 连接后发送 initialize 请求

    async def list_tools(self) -> list[dict]:
        # 发送 tools/list JSON-RPC 请求
        # 返回 tool 的 name + schema 列表

    async def call_tool(self, name: str, arguments: dict) -> str:
        # 发送 tools/call JSON-RPC 请求
        # 返回工具执行结果

    async def close(self):
        # 清理连接和子进程
```

### 2.2 MCPManager —— 多 Server 管理

```python
class MCPManager:
    _configs: dict[str, MCPServerConfig]   # "context7" → config
    _clients: dict[str, MCPClient]         # "context7" → client

    async def connect_all(self) -> ConnectResult:
        """并发连接所有配置的 MCP 服务器"""
        for name, config in self._configs.items():
            client = MCPClient(config)
            await client.connect()
            # 提取 server instructions
            info = ServerInfo(name=name, instructions=client.instructions)
            # 获取工具列表
            tools = await client.list_tools()
            for tool_def in tools:
                wrapper = MCPToolWrapper(name, tool_def, client)
                result.tools.append(wrapper)

    async def get_client(self, name: str) -> MCPClient:
        """获取客户端，如果断线自动重连"""
        if not client.is_alive:
            await client.close()
            client = MCPClient(self._configs[name])
            await client.connect()
        return client
```

### 2.3 MCPToolWrapper —— 协议适配

```python
class MCPToolWrapper(Tool):
    """将 MCP tool schema 适配为 DevFlow 的 Tool 接口"""

    def __init__(self, server_name: str, tool_def: dict, client: MCPClient):
        self.name = f"{server_name}_{tool_def['name']}"
        self.description = tool_def.get("description", "")
        self._client = client
        self._original_name = tool_def['name']

        # 动态创建 Pydantic params_model
        self.params_model = _build_params_model(tool_def.get("inputSchema", {}))

    async def execute(self, params) -> ToolResult:
        result = await self._client.call_tool(
            self._original_name, params.model_dump()
        )
        return ToolResult(output=result, is_error=False)
```

**为什么需要 ToolWrapper？** MCP 工具的 schema 格式和 DevFlow 内置工具不一致。Wrapper 做规范化——让 Agent 对"这是内置工具还是 MCP 工具"无感知。代价是多一层抽象，但换来了工具生态的即插即用。

---

## 三、为什么选 MCP 而不是自定义协议

```
方案 A（当前）：MCP 标准协议
方案 B（替代）：自定义 JSON-RPC/HTTP 协议
```

**A 比 B 好在哪：**

1. **零适配成本**：任何实现了 MCP 的 server 都可即插即用——npm registry 上现在有 500+ MCP server（database tools, API integrations, search engines 等）
2. **标准化 tool discovery**：`tools/list` 返回标准 schema，不需要手写 tool 描述
3. **标准生命周期**：initialize → list_tools → call_tool → close 的交互顺序是确定的，不需要每次和服务提供方协商
4. **生态网络效应**：Anthropic 主推 MCP，越来越多工具支持

**A 的代价：**

1. **JSON-RPC 负担**：比纯 HTTP API 复杂，要处理 request/response 的匹配、错误格式等
2. **Stdio 模式的子进程管理**：需要启动、监控、清理 MCP server 子进程——进程管理是出错的高发区
3. **协议稳定性**：MCP 还在快速迭代，协议升级可能导致兼容性问题

---

## 四、连接方式和配置

```yaml
# .devflow/config.yaml
mcp_servers:
  # Stdio 模式：启动本地进程，通过 stdin/stdout JSON-RPC 通信
  - name: context7
    command: npx
    args: ["-y", "@upstash/context7-mcp"]

  # HTTP 模式：连接到远程 MCP server
  - name: my-http-mcp
    url: https://example.com/mcp
    transport: http    # "http" (default) or "sse"

  # 带认证的 HTTP 模式
  - name: authenticated-mcp
    url: https://api.example.com/mcp
    transport: http
    headers:
      Authorization: "Bearer ${MY_TOKEN}"  # 环境变量替换
```

---

## 五、Deferred Tool —— 延迟加载机制

```python
# registry 中的 deferred tools 不随 system prompt 发送其 schema
# 而是通过 ToolSearch 工具让 LLM 按需加载

deferred_names = self.registry.get_deferred_tool_names()
if deferred_names:
    conversation.add_system_reminder(
        "The following deferred tools are available via ToolSearch. "
        "Use ToolSearch with query 'select:<name>' to load schemas:"
        + "\n".join(deferred_names)
    )
```

**为什么需要延迟加载？** MCP 工具可能很多（100+），全部 schema 会吃掉大量 system prompt token。延迟加载只暴露搜索入口，LLM 在需要时主动查询。

---

## 六、面试话术模板

> "MCP 的核心价值是标准化。我在 DevFlow 中从零实现了 MCP 客户端——包括 JSON-RPC 通信、工具发现、连接生命周期管理。架构分三层：MCPClient 负责单个 server 的 JSON-RPC 连接，MCPManager 管理多个 server 的并发连接和故障恢复，MCPToolWrapper 做协议适配——把 MCP tool schema 转为框架内部的 Tool 接口，让 Agent 不需要区分工具来源。
>
> 选 MCP 而不是自定义协议的关键理由是即插即用——不需要为每个外部工具写适配代码。一个实现了 MCP 的 server 就可以被直接接入。代价是 MCP 的 JSON-RPC 比纯 HTTP 更复杂，尤其是 stdio 模式的子进程管理——需要处理进程的 start/stop/cleanup。"

---

## 七、进阶面试追问

**Q: MCP server 挂了怎么办？**

A: Manager 的 `get_client()` 做自动重连——检查 `is_alive`，如果断线就 close + 重新 connect。重连在获取 client 时惰性触发，而不是后台自动——节省资源。如果 MCP 工具调用时 server 已不可用，call_tool 会抛出异常，被 agent.py 的 try/except 捕获后返回 `ToolResult(is_error=True)`，不会让 Agent 崩溃。

**Q: 为什么不把所有 MCP 工具都延迟加载？**

A: 延迟加载增加了一轮 tool call（先用 ToolSearch 查 → 再调实际工具）。对于常用的 MCP 工具，直接加载 schema 更高效。当前策略是所有 MCP 工具默认直接加载——延迟加载是可选优化。如果要接 100+ 个 MCP server，就需要更细粒度的加载策略。

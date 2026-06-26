# 01 — Agent 核心循环

> **面试问题**："从用户输入一句话到 Agent 给出回复，中间发生了什么？"
> **源文件**：[devflow/agent.py](../devflow/agent.py) (1294行)
> **依赖关系**：agent.py 是绝对核心，所有其他子系统都通过它被编排

---

## 一、怎么用

```python
# 创建 Agent
agent = Agent(
    client=llm_client,        # LLM 提供商抽象
    registry=tool_registry,    # 工具注册表
    protocol="anthropic",      # 协议类型
    work_dir=".",              # 工作目录
    permission_checker=perm,   # 权限检查器
    context_window=200_000,    # 上下文窗口大小
    memory_manager=mem_mgr,    # 记忆管理器
    hook_engine=hooks,         # Hook 引擎
)

# 流式交互
async for event in agent.run(conversation):
    if isinstance(event, StreamText):
        print(event.text, end="")      # 流式输出
    elif isinstance(event, ToolUseEvent):
        print(f"[调用工具: {event.tool_name}]")
    elif isinstance(event, ToolResultEvent):
        print(f"[工具结果: {event.elapsed:.1f}s]")
    elif isinstance(event, LoopComplete):
        break                           # Agent 完成
```

---

## 二、核心架构：事件驱动的 Agent 循环

### 2.1 整体流程

```
用户输入 → ConversationManager
              │
              ▼
         ┌──────────────────────────────────────┐
         │         Agent.run() 主循环            │
         │                                      │
         │   while True:                        │
         │     1. 自动压缩检查 (auto_compact)     │
         │     2. 构建 system prompt             │
         │     3. 构建 tool schemas              │
         │     4. 应用 tool_result budget        │
         │     5. LLM 流式调用                    │
         │     6. 消费流式事件 (StreamCollector)  │
         │     7. 如果没有 tool_calls → break     │
         │     8. 权限检查 → 执行工具              │
         │     9. tool_results 追加到对话         │
         │    10. 回到 1                          │
         └──────────────────────────────────────┘
              │
              ▼
         LoopComplete 事件
```

### 2.2 事件系统设计（核心）

DevFlow 用 **12 种 dataclass 事件**来表达 Agent 的所有行为：

```python
AgentEvent = (
    StreamText           # LLM 输出的正文片段（流式）
    | ThinkingText       # LLM 的思考过程（流式）
    | ToolUseEvent       # Agent 发起了工具调用
    | ToolResultEvent    # 工具执行完毕
    | TurnComplete       # 一轮推理完成
    | LoopComplete       # Agent 循环结束
    | UsageEvent         # Token 用量统计
    | ErrorEvent         # 错误
    | PermissionRequest  # 权限请求（HITL）
    | CompactNotification # 压缩通知
    | HookEvent          # Hook 执行结果
    | RetryEvent         # 重试信号（如 max_tokens 升级）
)
```

**关键设计细节**：

```python
@dataclass
class StreamText:
    text: str                     # 只有 text，没有 event_type 之类

@dataclass
class ToolUseEvent:
    tool_name: str                # "Bash", "ReadFile", ...
    tool_id: str                  # LLM 生成，用于匹配 tool_result
    arguments: dict[str, Any]     # 已验证的参数（Pydantic）

@dataclass
class ToolResultEvent:
    tool_id: str                  # 匹配 ToolUseEvent.tool_id
    tool_name: str
    output: str                   # 工具的实际输出
    is_error: bool                # 是否执行失败
    elapsed: float                # 执行耗时（秒）
```

### 2.3 StreamCollector —— 将 LLM 流事件转为 Agent 事件

```python
class StreamCollector:
    def __init__(self) -> None:
        self.response = LLMResponse()  # 累积的完整响应

    async def consume(self, stream) -> AsyncIterator[AgentEvent]:
        async for event in stream:
            if isinstance(event, TextDelta):
                self.response.text += event.text
                yield StreamText(text=event.text)       # 逐片转发
            elif isinstance(event, ThinkingDelta):
                yield ThinkingText(text=event.text)
            elif isinstance(event, ThinkingComplete):
                self.response.thinking_blocks.append(...)
            elif isinstance(event, ToolCallComplete):
                self.response.tool_calls.append(event)
                yield ToolUseEvent(...)                  # 完整的 tool call
            elif isinstance(event, StreamEnd):
                # 记下用量和停止原因
                self.response.input_tokens = event.input_tokens
                ...
```

### 2.4 主循环的 8 个关键节点

读 agent.py 的 `run()` 方法，按 8 个节点理解：

| 节点 | 代码位置 | 做什么 | 为什么要在这做 |
|------|----------|--------|---------------|
| **1. 注入上下文** | L441-447 | inject_environment + inject_long_term_memory | 确保每轮都用最新的环境信息和记忆 |
| **2. Hook: turn_start** | L469-473 | 触发 turn_start hook | 允许用户在每轮开始前注入自定义逻辑 |
| **3. 消费 Mailbox** | L475-478 | 检查 team mailbox | 多 Agent 协作的消息入口 |
| **4. 自动压缩** | L481-505 | auto_compact() 检查 | 在 LLM 调用前回收上下文空间 |
| **5. LLM 调用** | L557-559 | client.stream() + collector.consume() | 核心推理 |
| **6. max_tokens 处理** | L582-608 | 检测截断并自动扩容/恢复 | 防止输出被掐断 |
| **7. 工具调用循环** | L635-778 | 权限检查 → 执行 → 收集结果 | Agent 的"行动"阶段 |
| **8. 记忆提取** | L617-621 | 每 5 轮自动触发 | 沉淀用户偏好和项目知识 |

---

## 三、关键设计决策与 Tradeoff

### 3.1 为什么用事件驱动而不是回调？

```
方案 A（DevFlow 选的）：dataclass 事件 + async generator
方案 B（替代方案）：回调函数（on_text, on_tool_call, ...）
```

**A 比 B 好在哪：**
1. **可序列化**：dataclass 是值对象，可以 JSON 序列化后跨进程传递（tmux team mode 需要）
2. **可测试**：测试时收集事件列表，精确断言事件序列：`assert events == [StreamText("hello"), LoopComplete(1)]`
3. **解耦**：事件的"生产"（Agent.run()）和"消费"（TUI/Remote/Test）完全分离，消费者不需要知道 Producer 内部逻辑
4. **组合性**：async generator 天然支持 `async for event in agent.run()` 的消费模式，Python 原生支持

**A 的代价：**
- 事件类型多（12 种），新事件类型需要修改 AgentEvent union type
- 对于简单的"只想要最终文本"场景，需要自己过滤事件

### 3.2 为什么 max_iterations=50 而不是更小/更大？

```python
max_iterations: int = 50
```

- **太小（如 10）**：复杂任务可能需要多轮 tool call 才能完成，太早截断会让 Agent 半途而废
- **太大（如 200）**：如果 Agent 陷入 loop，要等到 200 轮才被强制终止，token 浪费巨大
- **50 是经验值**：匹配 `max_iterations` 的安全网——正常任务通常 2-5 轮完成，50 主要是防御性编程

### 3.3 max_tokens 升级策略

```python
MAX_TOKENS_CEILING = 64000           # 单次输出硬上限
MAX_OUTPUT_TOKENS_RECOVERIES = 3     # 恢复机会次数

# 第一次 cut：升级到 64K
if not max_tokens_escalated:
    self.client.set_max_output_tokens(MAX_TOKENS_CEILING)
    # 追加 resume 消息
    conversation.add_user_message(
        "Output token limit hit. Resume directly from where you stopped."
    )
    yield RetryEvent(reason="max_tokens escalation")
    continue

# 后续 cut：还有 3 次恢复机会
elif output_recoveries < MAX_OUTPUT_TOKENS_RECOVERIES:
    output_recoveries += 1
    # 追加更详细的 resume 消息
    ...
```

**为什么不直接用 64K？** 因为 max_output_tokens 越大，LLM 生成的内容可能越冗长，且成本更高。按需升级的策略在大多数情况下节省 token。

### 3.4 工具批量执行策略

```python
def partition_tool_calls(tool_calls, registry) -> list[ToolBatch]:
    # 并发的工具调用分组：连续的并发安全工具 = 一个并行 batch
    # 非并发安全的工具 = 单独的串行 batch
```

**为什么不是所有 tool call 都并行？** 有些工具之间有数据依赖（如先 mkdir 再写文件），并行执行会出错。只有标记了 `is_concurrency_safe=True` 的工具才放并行 batch。

### 3.5 连续未知工具保护

```python
if consecutive_unknown >= 3:
    yield ErrorEvent(
        message="Agent terminated: too many consecutive unknown tool calls"
    )
    break
```

这是对抗 LLM 幻觉的安全网——当 LLM 连续 3 次编造不存在的工具名时终止，防止无限循环浪费 token。

---

## 四、面试话术模板

> "DevFlow 的 Agent 核心是一个事件驱动的异步循环。每轮迭代首先是自动压缩检查——如果 token 用量接近上限，先做上下文压缩。然后构建 system prompt、获取工具列表，通过 StreamCollector 消费 LLM 的流式输出。流式事件分三类：文本 delta 逐片输出、thinking delta 显示思考过程、tool_call_complete 触发工具执行。
>
> 工具执行前经过四层权限检查——如果用户拒绝了，工具就不执行直接返回拒绝结果。执行成功后结果追加到对话历史，进入下一轮。如果本轮没有 tool call，说明 Agent 完成了任务，循环结束。
>
> 关键设计是事件系统——12 种 dataclass 事件覆盖了 Agent 的所有行为。和传统回调方案相比，事件是值对象——可以序列化后跨进程传递（多 Agent 场景）、可以在测试中精确断言、消费者不需要知道内部逻辑。"

---

## 五、进阶面试追问

**Q: async generator 和 callback 的真正区别是什么？**

A: async generator 是"拉"模型——消费者控制事件消费的节奏。callback 是"推"模型——生产者决定何时调用 callback。在 TUI 场景，"拉"模型天然适合——UI 可以在空闲时消费事件。在多个消费者共享事件流的场景（如同时渲染 TUI 和写日志），"拉"模型可以用 `asyncio.Queue` 做广播。

**Q: 为什么不直接用 LangChain 的 AgentExecutor？**

A: `AgentExecutor` 封装了 Agent 循环的内部逻辑——你无法在"LLM 调用前"和"工具执行后"插入自定义逻辑。DevFlow 需要在这些节点做权限检查、Hook 触发、上下文压缩、记忆提取——这些都需要直接控制循环。当你面试 Agent 基础设施岗位时，面试官期望你理解这些"循环内部"发生了什么。

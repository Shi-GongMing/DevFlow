# 08 — Hooks 扩展机制

> **面试问题**："你的 Agent 系统怎么让用户自定义行为？"
> **源文件**：[devflow/hooks/](../devflow/hooks/) (6个文件)
> **核心思想**：框架作者无法预见所有扩展需求 → 提供事件驱动的拦截点

---

## 一、Hooks 的设计哲学

框架不可能为每个用户写死特定的行为（"每次 bash 调用前记录审计日志"、"Agent 完成后发 Webhook 通知"）。Hooks 是用配置表达"在 X 事件发生时执行 Y 动作"——框架定义事件，用户定义响应。

---

## 二、Hook 的三要素

### 2.1 事件（Event）

```python
class LifecycleEvent(str, Enum):
    SESSION_START = "session_start"    # 会话启动
    SESSION_END = "session_end"        # 会话结束
    TURN_START = "turn_start"          # 每轮迭代开始
    TURN_END = "turn_end"              # 每轮迭代结束
    PRE_TOOL_USE = "pre_tool_use"      # 工具调用前（可拒绝）
    POST_TOOL_USE = "post_tool_use"    # 工具调用后
    PRE_SEND = "pre_send"              # 发送 LLM 请求前
    POST_RECEIVE = "post_receive"      # 收到 LLM 响应后
    USER_SUBMIT = "user_submit"        # 用户提交输入
```

### 2.2 条件（Condition）

```python
@dataclass
class ConditionGroup:
    operator: str = "and"     # "and" or "or"
    conditions: list[Condition]  # 具体条件

@dataclass
class Condition:
    field: str    # "tool_name", "file_path", "message", ...
    pattern: str  # glob/regex pattern
```

YAML 配置：
```yaml
- event: pre_tool_use
  conditions:
    - tool: Bash
      command_pattern: "npm *"     # 仅匹配 npm 命令
  actions: ...
```

### 2.3 动作（Action）

```python
@dataclass
class Action:
    type: str     # "command" | "prompt" | "http" | "agent"
    config: dict  # 具体配置，取决于 type
```

四种 Action 类型：

| type | 做什么 | 配置 | 适用场景 |
|------|--------|------|----------|
| `command` | 执行 shell 命令 | `command: "echo ..."` | 审计日志、通知、触发 CI |
| `prompt` | 注入到 system prompt | `prompt: "记住..."` | 动态上下文注入 |
| `http` | 发 HTTP 请求 | `url`, `method`, `headers` | Webhook、API 回调 |
| `agent` | 触发子 Agent | `agent: "reviewer"` | 自动化审查、测试 |

---

## 三、HookEngine 的执行流程

```python
class HookEngine:
    hooks: list[Hook]
    _prompt_messages: list[str]       # prompt 类型的累积消息
    _notifications: list[HookNotification]  # 通知队列

    async def run_hooks(self, event, ctx):
        # 1. 找到匹配当前事件的 hooks
        matched = self.find_matching_hooks(event, ctx)

        # 2. 对每个匹配的 hook
        for hook in matched:
            hook.mark_executed()  # 更新 cooldown 计数器

            # 3. 同步还是异步？
            if hook.async_exec:
                asyncio.ensure_future(self._run_single(hook, ctx))
                # 异步：不等待结果——后台执行
            else:
                await self._run_single(hook, ctx)
                # 同步：等待结果——可能阻塞主流程
```

**同步 vs 异步的 tradeoff：**
- 同步执行确保 hook 在下一阶段前完成（如 pre_tool_use 的拒绝判断必须同步）
- 异步执行不阻塞主流程——适合通知类型的 hook

### Hook 的限流机制

```python
class Hook:
    cooldown: int = 0         # 冷却时间（秒）
    max_executions: int = 0   # 最大执行次数（0 = 无限制）
    _last_executed: float     # 上次执行时间戳
    _exec_count: int = 0      # 已执行次数

    def should_run(self) -> bool:
        if self.max_executions and self._exec_count >= self.max_executions:
            return False
        if self.cooldown:
            elapsed = time.time() - self._last_executed
            if elapsed < self.cooldown:
                return False
        return True
```

---

## 四、pre_tool_use 的特殊处理 —— 拒绝机制

```python
# engine.py run_pre_tool_hooks()

async def run_pre_tool_hooks(self, ctx) -> ToolRejectedError | None:
    matched = self.find_matching_hooks("pre_tool_use", ctx)
    for hook in matched:
        result = await execute_action(hook.action, ctx)
        if hook.reject:
            return ToolRejectedError(
                tool=ctx.tool_name,
                reason=result.output,
                hook_id=hook.id,
            )
    return None
```

**为什么 pre_tool_use 是特殊的？** pre_tool_use 的结果可以**拒绝**工具调用——这是一个安全拦截点。用户可以用它来：
- "任何 Bash 命令中如果包含 `--force` 就拒绝"
- "任何 WriteFile 写入 `.env` 就拒绝"
- "任何 HTTP 请求到 unknown-host 就拒绝"

Post-tool hooks 不能拒绝——工具已经执行完了。

---

## 五、在 Agent 主循环中的集成点

```python
# agent.py run()
# 1. session_start hook
await self.hook_engine.run_hooks("session_start", ctx)

# 2. turn_start hook
await self.hook_engine.run_hooks("turn_start", ctx)

# 3. pre_send hook (LLM 调用前注入 prompt)
await self.hook_engine.run_hooks("pre_send", ctx)
# 获取 prompt 消息
hook_prompts = self.hook_engine.get_prompt_messages()

# 4. post_receive hook (LLM 响应后)
await self.hook_engine.run_hooks("post_receive", ctx)

# 5. pre_tool_use hook (可拒绝)
rejection = await self.hook_engine.run_pre_tool_hooks(hook_ctx)
if rejection:
    # 返回被拒绝的 ToolResult

# 6. post_tool_use hook
await self.hook_engine.run_hooks("post_tool_use", hook_ctx)

# 7. turn_end / session_end hooks
await self.hook_engine.run_hooks("turn_end", ctx)
await self.hook_engine.run_hooks("session_end", ctx)
```

---

## 六、HookContext —— 在 Action 中可访问的数据

```python
@dataclass
class HookContext:
    event_name: str        # 触发的事件名
    tool_name: str         # 工具名（如果是 tool 相关事件）
    tool_args: dict        # 工具参数
    file_path: str         # 文件路径
    message: str           # LLM 消息或其他文本
    error: str             # 错误消息（如果有）
    cwd: str               # 当前工作目录
```

这些字段在 action 的模板中可以替换：
```yaml
- type: command
  command: 'echo "Agent 调用了 {{tool_name}}，参数: {{tool_args}}" >> audit.log'
```

---

## 七、面试话术模板

> "Hooks 引擎解决的是框架开放性 vs 可维护性的矛盾。我不想在代码中写死'如果工具是 Bash 就记录日志'这类逻辑——不同用户有不同的需求。Hooks 提供了事件驱动的拦截点——框架在关键节点发射事件（session_start, turn_start, pre_tool_use, post_tool_use 等），用户通过 YAML 配置 condition → action 的映射规则。
>
> 四种 action 类型覆盖了主要扩展场景：command 执行 shell 脚本（审计、通知）、prompt 注入到 system prompt（动态上下文）、HTTP 发 Webhook、agent 触发子 Agent。pre_tool_use 是特殊的事件——它的结果可以拒绝工具调用，是安全拦截点。
>
> 关键设计细节是限流和冷却——max_executions 限制每个 hook 的最大执行次数，cooldown 防止频繁触发。没有限流的话，turn_start hook 在长对话中会被调用上百次。"

---

## 八、进阶面试追问

**Q: Hooks 会不会显著影响性能？**

A: 同步 hook 在主循环中执行——每次 pre_tool_use 前等待 hook 返回。如果 hook action 本身很慢（如 HTTP 超时），会直接拖慢 Agent。所以异步 hook 是默认推荐——`async_exec: true` 让 action 在后台执行。但 pre_tool_use 的拒绝判断必须同步——没办法避免。

**Q: 和 Claude Code 的 hooks 机制一样吗？**

A: 架构理念一样。Claude Code (Go) 的 hooks 也支持事件驱动的 action 执行。DevFlow 的 Python 实现和 Go 版在事件类型、action 类型、条件匹配上是对齐的。能讲清楚这个对齐本身——从 Go 版的设计文档理解意图，用 Python 实现同样的架构——证明了"理解框架设计而非模仿实现"的能力。

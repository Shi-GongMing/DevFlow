# 05 — 多 Agent 协作

> **面试问题**："你怎么让多个 Agent 协作完成复杂任务？"
> **源文件**：[devflow/teams/](../devflow/teams/) (10个文件)
> **关键依赖**：agent.py mail消耗 → teams/manager.py → teams/mailbox.py

---

## 一、三种 Spawn 方式

DevFlow 支持三种 Team Agent 运行方式，覆盖不同的场景：

| 方式 | 文件 | 隔离程度 | 通信方式 | 启动速度 |
|------|------|----------|----------|----------|
| **in-process** | spawn_inprocess.py | 共享进程 | Python 对象 | 最快 |
| **tmux** | spawn_tmux.py | 独立 tmux pane | 文件 Mailbox | 中 |
| **iTerm2** | spawn_iterm2.py | 独立 iTerm2 tab | 文件 Mailbox | 中 |

**为什么是三种而不是一种？** 每种都是特定场景的最优解：
- in-process：最快的子 Agent 执行，适合轻量查询任务
- tmux：真实终端环境，Agent 的 TUI 渲染和行为和主 Agent 完全一致
- iTerm2：macOS 原生体验，不需要安装 tmux

---

## 二、文件 Mailbox —— 多 Agent 通信核心

### 2.1 架构

```
Agent A (lead)                    Agent B (teammate)
    │                                    │
    │  send_message(to=B)                │
    ├──────────────────────────────────► │
    │  mailbox.write(B, msg)             │  mailbox.consume(B)
    │                                    │
    │                                    │  send_message(to=A)
    │  mailbox.consume(A) ◄──────────────┤
    │                                    │
```

### 2.2 Mailbox 实现

```python
class Mailbox:
    def __init__(self, dir_path: Path):
        self._dir = dir_path  # ~/.devflow/teams/{team}/mailbox/

    def write(self, to_agent: str, msg: MailboxMessage):
        # 为每个收件人创建一个子目录
        # 消息写入为独立 JSON 文件
        target_dir = self._dir / to_agent
        target_dir.mkdir(parents=True, exist_ok=True)
        msg_path = target_dir / f"{msg.id}.json"
        msg_path.write_text(msg.to_json())

    def consume(self, agent_id: str) -> list[MailboxMessage]:
        # 读取该 Agent 的所有消息文件
        # 读取后删除（consume 语义）
        target_dir = self._dir / agent_id
        messages = []
        for f in target_dir.glob("*.json"):
            messages.append(MailboxMessage.from_file(f))
            f.unlink()  # 消费后删除
        return messages
```

### 2.3 为什么用文件 Mailbox 而不是网络消息队列？

```
方案 A（DevFlow 选的）：文件 Mailbox
方案 B（替代方案）：Redis/RabbitMQ/ZeroMQ
```

**A 比 B 好在哪：**
1. **零外部依赖**：Agent 的操作环境是文件系统和终端，Mailbox 天然在这个环境里——不需要安装 Redis、不需要网络配置
2. **可调试**：消息是 JSON 文件，可以直接 `cat` 查看，不会"消息去哪了"
3. **天生持久化**：文件不会丢失——tmux pane 被 kill 后重启，mailbox 里的消息还在
4. **跨进程天然**：文件和 OS 进程无关，任何语言都能读写

**A 的代价：**
- 延迟高（毫秒级 vs 网络队列的微秒级），但 team 通信是秒级的，不敏感
- 没有消息确认/重试机制——consume 即删除，如果消费进程崩溃消息就丢了

---

## 三、TeamManager —— 团队生命周期管理

```python
class TeamManager:
    _teams: dict[str, AgentTeam]          # team 元数据
    _task_stores: dict[str, SharedTaskStore]  # 共享任务板
    _mailboxes: dict[str, Mailbox]        # 消息队列
    _inprocess_handles: dict[str, InProcessTeammateHandle]  # 进程句柄
    _pane_ids: dict[str, str]             # tmux pane ID
```

**Create Team 的完整流程**：

```python
def create_team(name, lead_agent_id, description, ...):
    # 1. 检测后端 (detect_backend)
    backend = detect_backend(teammate_mode, is_interactive)

    # 2. 生成唯一的 team slug → 创建目录
    slug = unique_team_name(name)
    team_dir = resolve_team_dir(slug)  # ~/.devflow/teams/{slug}/
    team_dir.mkdir(parents=True)

    # 3. 创建 AgentTeam 并持久化 config.json
    team = AgentTeam(name=slug, ...)
    team.save()

    # 4. 初始化共享任务板
    task_store = SharedTaskStore(team_dir / "tasks.json")

    # 5. 初始化 Mailbox
    mailbox_dir = team_dir / "mailbox"
    mailbox = Mailbox(mailbox_dir)

    # 6. 注册到内存
    self._teams[slug] = team
    self._task_stores[slug] = task_store
    self._mailboxes[slug] = mailbox
```

---

## 四、Agent 如何消费 Mailbox

在 agent.py 的主循环中，每轮迭代开始前检查 Mailbox：

```python
# agent.py run() 循环中
self._consume_mailbox(conversation)

def _consume_mailbox(self, conversation):
    if not self.team_name or not self._team_manager:
        return
    mailbox = self._team_manager.get_mailbox(self.team_name)
    messages = mailbox.consume(self.agent_id)
    for msg in messages:
        prefix = f"[Message from {msg.from_agent}]"
        if msg.message_type != "text":
            prefix = f"[{msg.message_type} from {msg.from_agent}]"
        content = f"{prefix} {msg.content}"
        conversation.add_user_message(content)  # 注入到对话
```

**为什么注入为 user 消息？** Agent 只能在自己的"对话"中理解世界。把 `[Message from teammate_b] task X is done` 注入为一条 user 消息，Agent 就知道 teammate 发来了什么。

---

## 五、Coordinator 模式 —— 任务编排者

```python
# teams/coordinator.py
# 环境变量 DEVFLOW_COORDINATOR_MODE=1 激活

def get_coordinator_system_prompt():
    return """You are DevFlow, an AI assistant that orchestrates
    software engineering tasks across multiple workers.

    You have access to tools for:
    - TeamCreate: create a team with N teammates
    - TaskCreate: assign a task to a specific teammate
    - TaskGet/List: check task status
    - TaskUpdate: update task details
    - SendMessage: send messages to teammates"""
```

Coordinator Agent 像项目经理——它不写代码，而是分配任务给 Teammate Agent，追踪进度，汇总结果。

---

## 六、面试话术模板

> "多 Agent 协作的核心挑战是通信和隔离。我的方案是用文件 Mailbox 做异步消息传递——每个 Agent 有自己的 mailbox 目录，消息以 JSON 文件形式写入。Lead Agent 在主循环迭代开始时消费 mailbox，把消息以 user message 的形式注入对话。
>
> 三种 spawn 方式对应不同场景：in-process 最快但没有终端隔离，适合纯计算任务；tmux 提供完整终端隔离，teammate 有独立 TUI；iTerm2 是 macOS 原生方案。Coordinator Agent 像项目经理——它分配任务、追踪进度、汇总结果，不直接写代码。
>
> 文件 Mailbox 的核心 tradeoff 是用文件 IO 的延迟（毫秒级）换取零外部依赖。在 Agent 协作场景——消息频率是秒级不是毫秒级——这个 tradeoff 是合理的。"

---

## 七、进阶面试追问

**Q: 文件 Mailbox 有并发问题吗？**

A: 每个 Mailbox 目录按 agent_id 分子目录——Agent A 只写 Agent B 的子目录，Agent B 只读自己的子目录。没有两个 writer 写同一个文件，所以没有写冲突。consume 操作在读完后 `unlink()`——如果崩溃发生在 read 和 unlink 之间，下次启动会读到重复消息（幂等性问题），但不会丢消息。

**Q: 和 LangGraph 的 multi-agent 有什么区别？**

A: LangGraph 的 multi-agent 是图内的——多个 Agent 在同一张 StateGraph 中共享状态、通过 checkpoint 同步。DevFlow 的 multi-agent 是图间的——每个 Agent 有独立的 Agent 循环和对话历史，通过共享 mailbox 通信。图间模型更灵活但更重——每个 Agent 有完整的 context window。对于编程任务，图间模型通常更好，因为每个 Agent 可以独立进行长推理链。

# DevFlow

基于 **Agent Harness** 架构的终端 AI 编程助手——核心是一个可编程的 Agent 运行时，将 LLM 推理、工具执行、权限门控和上下文生命周期编排为统一的事件驱动管线。

## 架构总览

```
用户输入 → TUI (Textual) → Agent 事件循环 → LLM Client (Anthropic / OpenAI)
                                  ↕
                  Tool Registry ← MCP Server（外部工具扩展）
                  Permission Gate（四模式权限门控）
                  Context Manager（自动压缩 / 摘要 / 恢复）
                  Memory System（自动提取用户偏好和项目上下文）
                  Hooks Engine（用户自定义生命周期回调）
```

每一层都可替换：换模型提供商、通过 MCP 接入外部工具、注入自定义 slash 命令、或通过共享邮箱模式编排多 Agent 协作。

## 核心子系统

| 子系统 | 职责 |
|--------|------|
| **Agent 事件循环** | 事件驱动主循环——流式输出 thinking delta、文本 delta、工具调用 delta、工具结果，支持 plan-mode ReAct 变体 |
| **上下文管理器** | 滑动窗口 + 自动压缩——旧轮次在 token 预算不足时被摘要替换，支持跨重启恢复 |
| **工具注册表** | 15+ 内置工具（bash、read、write、edit、grep、glob、sub-agent、team、worktree）+ MCP 包装的外部工具 |
| **权限引擎** | 四模式门控（default / accept-edits / plan / bypass）+ 规则匹配 + 危险命令检测 + 路径沙箱 |
| **记忆系统** | 从对话中自动提取用户偏好和项目上下文，存入文件级知识库，会话启动时召回 |
| **Hooks 引擎** | 用户自定义生命周期回调——在工具调用、会话启动等事件上触发 shell 命令、HTTP 请求或 prompt 注入 |
| **Teams 多 Agent** | 多 Agent 协作：支持 in-process、tmux、iTerm2 三种 spawn 方式，通过共享邮箱通信 |
| **Skills** | Markdown 定义的可复用工作流（含参数替换），从项目或用户目录加载 |
| **Commands** | 斜杠命令系统，内置处理器 + 用户可扩展 `.devflow/commands/` 自定义命令 |
| **Worktree** | Git worktree 隔离，支持并行 Agent 会话——创建、追踪、清理 worktree 而不干扰主工作树 |

## 快速开始

```bash
# 安装依赖
uv sync

# 配置 API Key —— 复制示例配置并编辑
cp .devflow/config.yaml.example .devflow/config.yaml
# 编辑 .devflow/config.yaml，填入你的 ANTHROPIC_API_KEY 或 OPENAI_API_KEY

# 启动 TUI
uv run devflow

# 或远程 Web 模式
uv run devflow --remote

# 非交互式单次执行
uv run devflow -p "解释这段代码的作用" --output-format text
```

## 配置文件查找顺序

1. `./devflow/config.yaml` — 项目级
2. `./devflow/config.local.yaml` — 本地覆盖（git-ignored）
3. `~/.devflow/config.yaml` — 用户全局回退

API Key 可在配置文件中设置，也可通过环境变量（`ANTHROPIC_API_KEY`、`OPENAI_API_KEY`）。

## 项目目录结构

```
devflow/              # Python 包（Agent Harness 核心）
  agent.py            # Agent 事件循环和事件类型定义
  app.py              # Textual TUI 应用
  client.py           # LLM 提供商抽象层（Anthropic / OpenAI）
  config.py           # 配置加载和模型解析
  agents/             # 子 Agent 定义、fork、trace
  commands/           # 斜杠命令解析器、注册表、处理器
  context/            # 上下文窗口管理（compact / recovery）
  hooks/              # 生命周期 Hook 引擎
  mcp/                # MCP 客户端和工具包装
  memory/             # 自动记忆提取和召回
  permissions/        # 权限门控和沙箱
  skills/             # Skill 加载器、解析器、执行器
  teams/              # 多 Agent 协作
  tools/              # 内置工具实现
  worktree/           # Git worktree 生命周期管理
tests/
.devflow/             # 项目本地配置、skills、agents、commands
```

## 技术栈

- Python >= 3.11
- Textual（终端 UI 框架）
- Anthropic SDK / OpenAI SDK（多模型提供商）
- MCP 协议（Model Context Protocol，外部工具扩展）
- Pydantic（数据校验）
- PyYAML（配置解析）

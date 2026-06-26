# DevFlow 项目说明

## 技术栈
- Python >= 3.11
- Textual (终端 UI 框架)
- Anthropic SDK / OpenAI SDK (多模型提供商)
- MCP 协议 (Model Context Protocol，工具扩展)
- Pydantic (数据校验)
- PyYAML (配置解析)

## 项目类型
终端 AI 编程助手，基于 Agent Harness 架构。核心是一个可编程的 Agent 运行时——事件驱动的主循环编排 LLM 推理、工具调用、权限门控和上下文生命周期。

## 代码规范
- commit message 用英文
- 变量命名用 snake_case
- 类名用 PascalCase
- 类型注解必须完整 (from __future__ import annotations)

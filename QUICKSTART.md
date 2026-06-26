# DevFlow 快速启动指南

## 环境要求

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/) 包管理器（推荐，已有 `uv.lock`）
- Anthropic 或 OpenAI API Key

## 1. 安装依赖

```bash
cd /path/to/MewCode
uv sync
```

这会根据 `uv.lock` 精确安装所有依赖到 `.venv/`。

## 2. 配置 API Key

```bash
cp .devflow/config.yaml.example .devflow/config.yaml
```

编辑 `.devflow/config.yaml`，替换 API Key：

```yaml
providers:
  - name: anthropic-official
    protocol: anthropic
    base_url: https://api.anthropic.com
    api_key: "sk-ant-xxx"   # ← 替换为你的 API Key
    model: claude-sonnet-4-20250514
    thinking: true
```

也可以使用环境变量，跳过配置文件：

```bash
export ANTHROPIC_API_KEY="sk-ant-xxx"
```

## 3. 启动

```bash
# TUI 模式（终端交互界面）
uv run devflow

# 非交互式单次执行
uv run devflow -p "解释 devflow/agent.py 的结构"

# 远程 Web 模式（浏览器访问 http://localhost:18888）
uv run devflow --remote

# 指定权限模式
uv run devflow --mode plan    # 计划模式：需先批准才执行工具
uv run devflow --mode acceptEdits  # 自动接受编辑
```

## 4. 验证安装成功

```bash
uv run devflow --help
```

如果输出 DevFlow 的帮助信息，说明安装成功。实际运行时如果 API Key 无效会报 403，这是正常的——替换真实 Key 即可。

## 5. 开发运行测试

```bash
uv run pytest tests/ -x -v
```

## 常见问题

**Q: 启动报 403 / PermissionDeniedError？**
A: API Key 未配置或无效。检查 `.devflow/config.yaml` 中的 `api_key` 字段，或确认环境变量已设置。

**Q: `uv sync` 报找不到 Python？**
A: 确保 Python >= 3.11，可以用 `uv venv --python 3.11` 指定版本。

**Q: TUI 模式下中文显示乱码？**
A: 确保终端使用支持 Unicode 的字体（推荐 Nerd Font 系列）。

**Q: 如何添加自定义 Skill？**
A: 在 `.devflow/skills/` 下创建 `.md` 文件，写入 frontmatter + 内容。DevFlow 启动时会自动加载。

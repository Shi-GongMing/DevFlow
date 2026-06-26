# 来源：公众号@小林coding
# 后端八股网站：xiaolincoding.com
# Agent网站：xiaolinnote.com
# 简历模版：jianli.xiaolinnote.com

from __future__ import annotations

from devflow.commands.handlers.clear import CLEAR_COMMAND
from devflow.commands.handlers.compact import COMPACT_COMMAND
from devflow.commands.handlers.help import HELP_COMMAND
from devflow.commands.handlers.mcp import MCP_COMMAND
from devflow.commands.handlers.memory import MEMORY_COMMAND
from devflow.commands.handlers.permission import PERMISSION_COMMAND
from devflow.commands.handlers.plan import PLAN_COMMAND
from devflow.commands.handlers.session import SESSION_COMMAND
from devflow.commands.handlers.skill import SKILL_COMMAND
from devflow.commands.handlers.rewind import REWIND_COMMAND
from devflow.commands.handlers.status import STATUS_COMMAND
from devflow.commands.registry import CommandRegistry


ALL_COMMANDS = [
    HELP_COMMAND,
    COMPACT_COMMAND,
    CLEAR_COMMAND,
    PLAN_COMMAND,
    SESSION_COMMAND,
    MCP_COMMAND,
    MEMORY_COMMAND,
    PERMISSION_COMMAND,
    REWIND_COMMAND,
    STATUS_COMMAND,
    SKILL_COMMAND,
]


def register_all_commands(registry: CommandRegistry) -> None:
    for cmd in ALL_COMMANDS:
        registry.register_sync(cmd)


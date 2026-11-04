"""与 MESA 引擎交互的协议层（core，仅标准库）。

包含两个子模块：

- :mod:`core.mesa.commands` —— **命令构造**（做什么）；
- :mod:`core.mesa.terminal` —— **终端启动**（在哪里跑）。

协议冻结说明见 ``core/mesa/commands.py`` 顶部；任何语义变更都必须先改
``tests/test_protocol_snapshot.py`` 与 ``tests/test_core_mesa_commands.py``，
并在提交信息中声明。
"""

from .commands import (
    ACTION_BUILD,
    ACTION_CLEAN,
    ACTION_RESTART,
    ACTION_RUN,
    ACTION_RUN_ALL,
    SCRIPT_SEQUENCES,
    UnknownActionError,
    build_bash_c_command,
    build_shell_command,
    script_sequence,
)

__all__ = [
    "ACTION_BUILD",
    "ACTION_RUN",
    "ACTION_RUN_ALL",
    "ACTION_RESTART",
    "ACTION_CLEAN",
    "SCRIPT_SEQUENCES",
    "UnknownActionError",
    "script_sequence",
    "build_shell_command",
    "build_bash_c_command",
]

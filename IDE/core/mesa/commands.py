"""MESA 命令构造（core 层，仅标准库，无 UI、无进程启动）。

============================================================================
冻结协议（FROZEN PROTOCOL）—— 未获批准不得改变语义
============================================================================
1. 动作 → 命令 的对应关系（在**项目目录**下执行）。
   每个动作是"若干条命令"的序列，命令之间用 ``&&`` 串联；
   每条命令本身是 **argv 数组**（命令名 + 参数），参数**不得**与命令名
   用 ``&&`` 连接（快照名是 ``./re`` 的位置参数，不是另一条命令）：

   ==========  ===========================  ============================
   action      命令序列                      对应原实现
   ==========  ===========================  ============================
   build       ["./mk"]                     compile_and_run(mode="mk")
   run         ["./rn"]                     compile_and_run(mode="rn")
   run_all     ["./mk", "./rn"]             compile_and_run(mode="both")
   restart     ["./re", <snapshot>]         mesa_restart.run_restart
   clean       ["./clean"]                  clean.run_clean
   ==========  ===========================  ============================

2. 必须"先 cd 到项目目录再执行命令"，且 ``cd`` 发生在交互式 shell
   读取 ``~/.bashrc`` **之后**（原有行为，不能改为依赖继承的 cwd，
   因为 ``.bashrc`` 里可能有 ``cd``）。
3. ``restart`` 的快照名为空表示"从最近快照重启"（不传位置参数）。

============================================================================
已获批准的行为变更（阶段 2）
============================================================================
- **P5 修复**：动态内容（项目路径、快照名）不再手工拼进 shell 字符串，
  统一经 :func:`shlex.quote` 转义，消除注入。
  副作用：无需转义的路径/快照名不再出现单引号
  （``cd '/tmp/p'`` → ``cd /tmp/p``），语义完全等价。
- 命令以 argv 数组表达（见 ``SCRIPT_SEQUENCES``），便于其他语言逐条翻译。
- **MESA 环境前置（本阶段批准）**：执行动作前先 ``. <IDE>/mesa_env.sh``。
  原因：WSL 分支经 ``cmd.exe /c start ... wsl.exe -- bash -ic`` 弹出的
  bash **并非交互式**（stdin 无 tty，``$-`` 里没有 ``i``），Ubuntu 的
  ``.bashrc`` 顶部 ``case $- in *i*)`` 保护会提前 ``return``，写进
  ``.bashrc`` 的 MESA 环境块根本不执行 → ``./mk`` 报
  ``MESA_DIR enviroment variable is not set``，``./rn``（含 pgstar 实时
  绘图窗口）从未运行。因此改为显式 source 安装器生成的 ``mesa_env.sh``
  （文件缺失时跳过，错误由 ``./mk`` 自行给出），不依赖交互式 rc 文件。
"""

from __future__ import annotations

import os
import shlex
from collections.abc import Iterable, Sequence

from core.config import project_root

ACTION_BUILD = "build"
ACTION_RUN = "run"
ACTION_RUN_ALL = "run_all"
ACTION_RESTART = "restart"
ACTION_CLEAN = "clean"

#: 单个 argv 数组（命令名 + 参数）
Argv = tuple[str, ...]
#: 动作 → 命令序列（冻结，见模块 docstring）
SCRIPT_SEQUENCES: dict[str, tuple[Argv, ...]] = {
    ACTION_BUILD: (("./mk",),),
    ACTION_RUN: (("./rn",),),
    ACTION_RUN_ALL: (("./mk",), ("./rn",)),
    ACTION_RESTART: (("./re",),),
    ACTION_CLEAN: (("./clean",),),
}

#: 终端窗口执行完命令后保持打开（便于观察 MESA 长时间运行输出）
KEEP_OPEN_SUFFIX = "; exec bash"

#: 安装器生成的 MESA 环境脚本名（与 install.py 的 write_env_file 一致）
ENV_SCRIPT_NAME = "mesa_env.sh"


def env_preamble() -> str:
    """source IDE 自带 ``mesa_env.sh`` 的 shell 片段（文件缺失时跳过）。

    官方风格：安装器把 MESA_DIR / MESASDK_ROOT / PATH 写在生成的环境脚本里，
    终端命令显式加载它即可在任何 shell（含非交互式）下编译运行 MESA。
    """
    env_path = quote(os.path.join(project_root(), ENV_SCRIPT_NAME))
    return f"{{ [ -f {env_path} ] && . {env_path}; }}"


class UnknownActionError(ValueError):
    """传入了未定义的动作名。"""


def quote(value: object) -> str:
    """把任意值安全地转义为可嵌入 shell 的 token。"""
    return shlex.quote(str(value))


def script_sequence(action: str, snapshot: str | None = None) -> tuple[Argv, ...]:
    """返回该动作的命令序列；restart 时把快照名作为 ``./re`` 的位置参数。"""
    try:
        base = SCRIPT_SEQUENCES[action]
    except KeyError:
        raise UnknownActionError(
            f"未知动作: {action!r}；可用: {', '.join(sorted(SCRIPT_SEQUENCES))}"
        ) from None
    if action == ACTION_RESTART and snapshot:
        return (("./re", str(snapshot)),)
    return base


def normalize_commands(commands: Iterable[Argv | str]) -> tuple[Argv, ...]:
    """把"命令字符串"或"argv 序列"统一成 argv 元组序列。"""
    normalized: list[Argv] = []
    for item in commands:
        if isinstance(item, str):
            normalized.append((item,))
        else:
            normalized.append(tuple(str(part) for part in item))
    return tuple(normalized)


def build_script_body(commands: Iterable[Argv | str]) -> str:
    """把命令序列拼成 ``./mk && ./rn`` 形式（每个 token 单独转义）。"""
    normalized = normalize_commands(commands)
    if not normalized:
        raise ValueError("命令序列不能为空")

    rendered: list[str] = []
    for argv in normalized:
        if not argv:
            raise ValueError("命令不能为空 argv")
        rendered.append(" ".join(quote(part) for part in argv))
    return " && ".join(rendered)


def build_shell_command(
    project_path: str,
    action: str,
    snapshot: str | None = None,
    *,
    scripts: Iterable[Argv | str] | None = None,
    keep_open: bool = False,
) -> str:
    """构造"在项目目录执行该动作"的 shell 命令行（注入安全）。

    :param scripts: 仅供测试注入无害命令（如 ``("pwd",)``），生产调用不要传。
    :param keep_open: 是否追加 ``; exec bash``（终端窗口保持打开）。
    """
    commands = script_sequence(action, snapshot) if scripts is None else normalize_commands(scripts)
    command = f"cd {quote(project_path)} && {env_preamble()} && {build_script_body(commands)}"
    return command + KEEP_OPEN_SUFFIX if keep_open else command


def build_bash_c_command(
    project_path: str,
    action: str = ACTION_CLEAN,
    snapshot: str | None = None,
    *,
    scripts: Iterable[Argv | str] | None = None,
) -> list[str]:
    """构造 ``bash -c`` 的完整 argv（用于不需要新终端窗口的场景，如 clean）。"""
    return [
        "bash",
        "-c",
        build_shell_command(project_path, action, snapshot, scripts=scripts, keep_open=False),
    ]

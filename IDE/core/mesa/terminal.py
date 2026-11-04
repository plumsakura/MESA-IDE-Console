"""终端启动（core 层，仅标准库）。

合并了原实现中重复的两份逻辑（P8）：
``compile_and_run.py:6-12,55-79`` 与 ``mesa_restart.py:8-14,48-72``。

声明的行为变更（阶段 2）：

- 统一使用 ``bash -ic``（交互式，会加载 ``~/.bashrc``）。
  原 ``compile_and_run`` 用的是 ``bash -c``；GUI 启动的进程常常拿不到
  ``MESA_DIR``，而它通常写在 ``.bashrc`` 里，因此统一为 ``-ic``
  与 ``mesa_restart`` 一致（这也让"直接安装/运行 MESA 项目"更可靠）。
- 统一显式传递 ``env=os.environ.copy()``（原 compile_and_run 未传，靠继承）。
- WSL 分支不再 ``communicate()`` 等待（原实现会阻塞 UI 线程，P9）。
- **WSL 分支保留 ``shell=True``**：必须借助 ``cmd.exe`` 的 ``start`` 内建
  才能弹出新 Windows 终端窗口，且该字符串已在真机验证可用。动态内容
  已由 :func:`core.mesa.commands.build_shell_command` 转义——**需人工确认**
  是否接受这一处例外（纯 Linux 分支完全不经过 shell）。
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Mapping

PROC_VERSION = "/proc/version"

#: WSL 分支的窗口标题（冻结：与原实现一致）
WSL_WINDOW_TITLE = "MESA Run"


@dataclass(frozen=True)
class TerminalSpec:
    """一个终端模拟器的启动方式。"""

    executable: str
    args: tuple[str, ...]


#: 终端探测顺序（冻结：与原实现一致），args 为传给终端自身的前缀参数
LINUX_TERMINALS: tuple[TerminalSpec, ...] = (
    TerminalSpec("gnome-terminal", ("--", "bash", "-ic")),
    TerminalSpec("konsole", ("-e", "bash", "-ic")),
    TerminalSpec("xfce4-terminal", ("-e", "bash", "-ic")),
    TerminalSpec("terminator", ("-e", "bash", "-ic")),
    TerminalSpec("mate-terminal", ("-e", "bash", "-ic")),
    TerminalSpec("lxterminal", ("-e", "bash", "-ic")),
    TerminalSpec("xterm", ("-e", "bash", "-ic")),
)

NO_TERMINAL_HINT = (
    "未找到可用的终端模拟器。\n请安装 xterm 或配置您的终端环境。\n\n"
    "Ubuntu/Debian: sudo apt install xterm\n"
    "Fedora: sudo dnf install xterm\n"
    "Arch Linux: sudo pacman -S xterm"
)


@dataclass(frozen=True)
class LaunchResult:
    """启动结果（供 UI 决定是否提示用户）。"""

    ok: bool
    detail: str
    executable: str | None = None
    argv: tuple[str, ...] = field(default=())
    via_wsl: bool = False


def is_wsl(version_path: str = PROC_VERSION, opener: Callable[..., object] | None = None) -> bool:
    """检测是否运行在 WSL 中（读 ``/proc/version``，失败时返回 False）。

    ``opener`` 默认为内置 ``open``，且**在调用时解析**（而非作为默认参数固化），
    以便测试/宿主替换文件读取实现。
    """
    reader = open if opener is None else opener
    try:
        with reader(version_path, "r") as handle:  # type: ignore[union-attr]
            return "microsoft" in handle.read().lower()  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 - 保持原实现的静默降级行为
        return False


def find_terminal(which: Callable[[str], str | None] = shutil.which) -> TerminalSpec | None:
    """按冻结顺序返回第一个可用的终端；都没有则返回 None。"""
    for spec in LINUX_TERMINALS:
        if which(spec.executable):
            return spec
    return None


def build_linux_argv(spec: TerminalSpec, shell_command: str) -> list[str]:
    """构造终端进程的 argv（shell_command 已由 commands 层转义）。"""
    return [spec.executable, *spec.args, shell_command]


def build_wsl_command(
    shell_command: str,
    window_title: str = WSL_WINDOW_TITLE,
    distro: str | None = None,
) -> str:
    """构造 WSL 分支经 ``cmd.exe`` 弹新窗口的命令字符串。

    ``distro`` 非空时用官方语法 ``wsl.exe -d <发行版>`` 指定目标发行版。
    **为什么必须指定**：WSL 里 IDE 可能运行在非默认发行版（如 Ubuntu-Third），
    而 ``wsl.exe`` 不带 ``-d`` 时默认进 * 标记的默认发行版 —— 项目目录在
    另一发行版里，新终端会报 ``cd: ...: No such file or directory``。
    ``distro`` 缺省时从环境变量 ``WSL_DISTRO_NAME`` 读取（WSL 会话内自动存在）。
    """
    name = distro if distro is not None else os.environ.get("WSL_DISTRO_NAME", "")
    name = (name or "").strip()
    target = f" -d {shlex.quote(name)}" if name else ""
    return f'cmd.exe /c start "{window_title}" wsl.exe{target} -- bash -ic "{shell_command}"'


def _default_env(env: Mapping[str, str] | None) -> dict[str, str]:
    return dict(os.environ if env is None else env)


def launch_linux(
    shell_command: str,
    env: Mapping[str, str] | None = None,
    *,
    which: Callable[[str], str | None] = shutil.which,
    popen: Callable[..., object] = subprocess.Popen,
) -> LaunchResult:
    """在探测到的终端中启动命令（fire-and-forget，不阻塞、不捕获输出）。"""
    spec = find_terminal(which)
    if spec is None:
        return LaunchResult(ok=False, detail=NO_TERMINAL_HINT)
    argv = build_linux_argv(spec, shell_command)
    popen(
        argv,
        env=_default_env(env),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return LaunchResult(
        ok=True,
        detail=f"已通过 {spec.executable} 启动",
        executable=spec.executable,
        argv=tuple(argv),
    )


def launch_wsl(
    shell_command: str,
    env: Mapping[str, str] | None = None,
    *,
    popen: Callable[..., object] = subprocess.Popen,
    window_title: str = WSL_WINDOW_TITLE,
) -> LaunchResult:
    """在 WSL 中经 ``cmd.exe /c start`` 弹出新的 Windows 终端窗口。

    注意：此处保留 ``shell=True``（需 cmd.exe 的 start 内建），
    详见模块 docstring 的声明。
    """
    resolved_env = _default_env(env)
    command = build_wsl_command(
        shell_command, window_title, distro=resolved_env.get("WSL_DISTRO_NAME", "")
    )
    popen(command, shell=True, env=resolved_env)
    return LaunchResult(
        ok=True,
        detail="已通过 cmd.exe 在 WSL 中启动新终端",
        executable="cmd.exe",
        argv=(command,),
        via_wsl=True,
    )


def launch(
    shell_command: str,
    env: Mapping[str, str] | None = None,
    *,
    which: Callable[[str], str | None] = shutil.which,
    popen: Callable[..., object] = subprocess.Popen,
    wsl_detector: Callable[[], bool] = is_wsl,
) -> LaunchResult:
    """统一入口：WSL 走 cmd.exe，否则按冻结顺序探测 Linux 终端。"""
    if wsl_detector():
        return launch_wsl(shell_command, env, popen=popen)
    return launch_linux(shell_command, env, which=which, popen=popen)

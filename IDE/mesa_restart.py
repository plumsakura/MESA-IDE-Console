"""兼容层（薄代理）：``run_restart`` / ``open_terminal``。

实现已迁移到 :mod:`core.mesa`。``open_terminal`` 保持原语义：
接收"尚未保持打开"的命令行，自行追加 ``; exec bash`` 并 fire-and-forget 启动。

声明的行为变更（阶段 2）：快照名经 ``shlex.quote`` 转义（P5）；
无需转义时不再出现单引号（``./re 'snap1'`` → ``./re snap1``）。
"""

from __future__ import annotations

import os
import shutil  # noqa: F401 - 作为 patch 锚点显式保留
import subprocess  # noqa: F401 - 作为 patch 锚点显式保留
from tkinter import messagebox, simpledialog

from core.mesa import ACTION_RESTART, build_shell_command
from core.mesa.outputs import resolve_outputs
from core.mesa import terminal as core_terminal

RESTART_FAILED_MESSAGE = (
    "无法启动终端界面。\n请确保系统中安装了终端模拟器 (如 gnome-terminal 或 xterm)。"
)


def is_wsl() -> bool:
    """兼容旧接口（原 ``mesa_restart.py:8-14``）。"""
    return core_terminal.is_wsl()


def open_terminal(cmd_str: str) -> bool:
    """启动终端执行 ``cmd_str``，并让窗口保持打开。成功返回 True。"""
    result = core_terminal.launch(
        cmd_str + "; exec bash",
        which=shutil.which,
        popen=subprocess.Popen,
        wsl_detector=is_wsl,
    )
    return result.ok


def run_restart(project_path: str) -> None:
    """按快照重启 MESA；快照名为空表示从最近快照重启。

    手册（``using_mesa/running.rst``）说明快照是 ``photos/`` 里的二进制 dump、
    名字形如 ``x208``，``./re x208`` 从该快照继续。因此这里**把已有快照列给用户**
    并做一次存在性校验，避免拼错名字后 MESA 才报错。
    """
    if not os.path.exists(project_path):
        messagebox.showerror("错误", f"项目路径不存在: {project_path}")
        return

    outputs = resolve_outputs(project_path)
    photos = outputs.existing_photos()
    if photos:
        shown = ", ".join(photos[-10:])
        hint = f"可用快照（{outputs.photo_dir}）：{shown}"
    else:
        hint = f"未找到快照（{outputs.photo_dir} 为空；请先运行一次 ./rn）"

    snap_name = simpledialog.askstring(
        "重启项目", f"请输入快照文件名 (留空则从最近快照重启):\n{hint}", initialvalue=""
    )

    snapshot = snap_name.strip() if snap_name and snap_name.strip() else None
    if snapshot and photos and snapshot not in photos:
        messagebox.showwarning(
            "快照不存在",
            f"在 {outputs.photo_dir} 里找不到快照 '{snapshot}'。\n"
            f"可用快照：{', '.join(photos[-10:])}",
        )
        return
    cmd_str = build_shell_command(project_path, ACTION_RESTART, snapshot)

    if not open_terminal(cmd_str):
        messagebox.showerror("运行失败", RESTART_FAILED_MESSAGE)

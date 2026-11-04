"""兼容层（薄代理）：``compile_and_run``。

实现已迁移到 :mod:`core.mesa.commands` + :mod:`core.mesa.terminal`。
本文件保留 ``subprocess`` / ``shutil`` / ``is_wsl`` 作为**调用时注入的 patch 锚点**，
使 ``tests/test_protocol_snapshot.py`` 的既有打桩位置继续有效
（即：迁移不改变可观测行为，只改变实现位置）。

声明的行为变更（阶段 2）：

1. 动态内容经 ``shlex.quote`` 转义（P5 注入修复）；无需转义的路径不再带单引号。
2. 终端统一使用 ``bash -ic``（原为 ``bash -c``），与 restart 一致 ——
   GUI 启动时能读到 ``.bashrc`` 里的 ``MESA_DIR``。
3. WSL 分支不再 ``communicate()`` 阻塞 UI 线程（P9）。
"""

from __future__ import annotations

import os
import shutil  # noqa: F401 - 作为 patch 锚点显式保留
import subprocess  # noqa: F401 - 作为 patch 锚点显式保留
from tkinter import messagebox

from core.mesa import (
    ACTION_BUILD,
    ACTION_RUN,
    ACTION_RUN_ALL,
    build_shell_command,
)
from core.mesa import terminal as core_terminal

MODE_TO_ACTION = {
    "mk": ACTION_BUILD,
    "rn": ACTION_RUN,
    "both": ACTION_RUN_ALL,
}


def is_wsl() -> bool:
    """兼容旧接口（原 ``compile_and_run.py:6-12``）。"""
    return core_terminal.is_wsl()


def compile_and_run(project_path: str, mode: str = "both") -> None:
    """在项目目录编译/运行 MESA（在新终端中执行，fire-and-forget）。"""
    if not os.path.exists(project_path):
        messagebox.showerror("错误", "项目路径不存在: " + project_path)
        return

    action = MODE_TO_ACTION.get(mode, ACTION_RUN_ALL)
    shell_command = build_shell_command(project_path, action, keep_open=True)

    result = core_terminal.launch(
        shell_command,
        which=shutil.which,
        popen=subprocess.Popen,
        wsl_detector=is_wsl,
    )
    if not result.ok:
        messagebox.showerror("无法启动终端", core_terminal.NO_TERMINAL_HINT)

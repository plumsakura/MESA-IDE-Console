"""兼容层（薄代理）：``run_clean``。

实现已迁移到 :mod:`core.mesa.commands`。保持原有行为：
校验项目路径与 ``clean`` 脚本、确保脚本可执行、后台静默执行（不弹终端、不阻塞）。

声明的行为变更（阶段 2）：命令经 ``shlex.quote`` 转义（P5）；
无需转义的路径不再带单引号；chmod 失败改为 ``logging`` 记录（原为 print）。
"""

from __future__ import annotations

import logging
import os
import subprocess  # noqa: F401 - 作为 patch 锚点显式保留
from tkinter import messagebox

from core.mesa import ACTION_CLEAN, build_bash_c_command

logger = logging.getLogger(__name__)


def run_clean(project_path: str) -> None:
    """在后台静默执行项目目录下的 ``./clean``。"""
    if not os.path.exists(project_path):
        messagebox.showerror("错误", f"项目路径不存在: {project_path}")
        return

    clean_script = os.path.join(project_path, "clean")
    if not os.path.exists(clean_script):
        messagebox.showerror("错误", f"未找到清理脚本: {clean_script}")
        return

    try:
        os.chmod(clean_script, 0o755)
    except Exception as exc:  # noqa: BLE001 - 权限问题不应阻止清理尝试
        logger.warning("无法修改 clean 权限: %s", exc)

    argv = build_bash_c_command(project_path, ACTION_CLEAN)
    try:
        subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=os.environ.copy(),
        )
    except Exception as exc:  # noqa: BLE001 - 原实现同样以弹窗报告
        messagebox.showerror("运行失败", f"无法执行 clean 命令：\n{str(exc)}")

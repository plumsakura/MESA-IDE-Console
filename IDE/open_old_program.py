"""兼容层：打开已有项目（薄代理到 :mod:`core.project`）。

**已消除 P8**：``get_mesa_paths()`` 现在与 ``create_new_program`` 返回同样的
5 个键（原为 3 个）。

**已修复 P6**：原先的校验写成 ``if os.path.exists(...) or True:``（恒真死代码）。
现在改为真实检查：缺少核心 inlist 时记录警告（仍按用户选择打开，不改变交互）。
"""

from __future__ import annotations

import logging
import os
import tkinter as tk
from tkinter import filedialog, messagebox
from ide_ui.fonts import ui_font_family

from core.project import CORE_INLIST_FILES, looks_like_mesa_project, missing_core_inlists, project_paths
from IDE import start_ide

logger = logging.getLogger(__name__)


def get_mesa_paths() -> dict[str, str | None]:
    """兼容旧接口：返回 MESA 相关路径（5 个键，与 create_new_program 一致）。"""
    return project_paths().as_legacy_dict()


class OpenProgramDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("打开现有的 MESA 项目")
        self.geometry("450x300")
        self.transient(parent)
        self.grab_set()

        paths = get_mesa_paths()
        self.ts_path = paths["test_suite"]
        self.user_programs = paths["user_programs"]

        self.selected_path = None

        tk.Label(self, text="请选择要打开的项目源:", font=(ui_font_family(), 10, "bold")).pack(pady=(20, 10))

        tk.Button(self, text="从 MESA test_suite 中选择", width=30,
                  command=self.select_test_suite).pack(pady=5)

        tk.Button(self, text="从 ~/MESA_program 中选择", width=30,
                  command=self.select_user_program).pack(pady=5)

        self.lbl_info = tk.Label(self, text="未选择项目", fg="gray", wraplength=400)
        self.lbl_info.pack(pady=20)

        tk.Button(self, text="打开项目", command=self.confirm, bg="#2196F3", fg="white", width=20).pack(pady=10)

    def select_test_suite(self):
        path = filedialog.askdirectory(initialdir=self.ts_path, title="选择 test_suite 项目")
        if path:
            self.selected_path = path
            self.lbl_info.config(text=f"已选: {path}", fg="black")

    def select_user_program(self):
        path = filedialog.askdirectory(initialdir=self.user_programs, title="选择我的项目")
        if path:
            self.selected_path = path
            self.lbl_info.config(text=f"已选: {path}", fg="black")

    def confirm(self):
        if not self.selected_path:
            messagebox.showwarning("提示", "请先选择一个有效的项目文件夹")
            return
        self.destroy()


def open_old_program(parent_root=None):
    """外部调用函数：打开现有的 MESA 项目。"""
    if parent_root is None:
        parent_root = tk.Tk()
        parent_root.withdraw()

    dialog = OpenProgramDialog(parent_root)
    parent_root.wait_window(dialog)

    if hasattr(dialog, "selected_path") and dialog.selected_path:
        target_path = dialog.selected_path

        # 真实校验（替换原先恒真的 `or True`）：不像 MESA 项目时只记录警告，
        # 不阻止用户打开（保持原有交互行为）。
        if not looks_like_mesa_project(target_path):
            logger.warning(
                "所选目录缺少核心 inlist 文件 %s: %s（仍按用户选择打开）",
                "/".join(CORE_INLIST_FILES),
                target_path,
            )
            missing = missing_core_inlists(target_path)
            logger.warning("缺失文件: %s", ", ".join(missing) or "无")

        try:
            start_ide(target_path)
        except Exception as exc:  # noqa: BLE001 - 原实现同样以弹窗报告失败
            messagebox.showerror("启动失败", f"无法打开项目:\n{str(exc)}")

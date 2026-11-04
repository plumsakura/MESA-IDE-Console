"""兼容层：项目模板定位（薄代理到 :mod:`core.project`）。

**已消除 P8**：本文件与 ``open_old_program.get_mesa_paths()`` 现在返回
完全相同的 5 个键（原先一个 5 键、一个 3 键）。

**新增行为**（阶段 2 声明）：``submit()`` 会校验项目名，拒绝空名、
``.``/``..``、含路径分隔符的名字 —— 原先只判断非空，
形如 ``../../x`` 的项目名可写到 ``~/MESA_program`` 之外。
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox
from ide_ui.fonts import ui_font_family

from core.project import (
    create_project,
    project_dir,
    project_paths,
    user_programs_dir,
    validate_project_name,
)
from IDE import start_ide


def get_mesa_paths() -> dict[str, str | None]:
    """兼容旧接口：返回 MESA 相关路径（5 个键，与 open_old_program 一致）。"""
    return project_paths().as_legacy_dict()


class NewProjectDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("新建 MESA 项目")
        self.geometry("500x500")
        self.transient(parent)
        self.grab_set()

        paths = get_mesa_paths()
        self.work_path = paths["work"]
        self.ts_path = paths["test_suite"]
        self.defaults_path = paths["defaults"]
        self.user_programs = paths["user_programs"] or user_programs_dir()

        self.target_dir = None
        self.project_name = None
        self.source_path = self.work_path

        tk.Label(self, text="1. 输入新项目名称:", font=(ui_font_family(), 10, "bold")).pack(pady=(15, 0), anchor="w", padx=20)
        self.name_entry = tk.Entry(self, width=50)
        self.name_entry.pack(pady=5, padx=20)

        tk.Label(self, text="2. 选择模板:", font=(ui_font_family(), 10, "bold")).pack(pady=(15, 0), anchor="w", padx=20)
        self.var_source = tk.StringVar(value="default")

        tk.Radiobutton(self, text="默认模板 (star/work)", variable=self.var_source, value="default",
                       command=self.update_ui).pack(anchor="w", padx=40)
        tk.Radiobutton(self, text="从 test_suite 选择", variable=self.var_source, value="test_suite",
                       command=self.update_ui).pack(anchor="w", padx=40)
        self.btn_ts = tk.Button(self, text="选择...", state="disabled", command=self.browse_ts)
        self.btn_ts.pack(anchor="w", padx=65)

        tk.Radiobutton(self, text="从 ~/MESA_program 选择", variable=self.var_source, value="custom",
                       command=self.update_ui).pack(anchor="w", padx=40)
        self.btn_cust = tk.Button(self, text="选择...", state="disabled", command=self.browse_cust)
        self.btn_cust.pack(anchor="w", padx=65)

        self.lbl_selected = tk.Label(self, text=f"路径: {self.source_path}", fg="blue", wraplength=400)
        self.lbl_selected.pack(pady=10)

        tk.Button(self, text="确认创建", command=self.submit, bg="#4CAF50", fg="white", width=20, height=2).pack(
            pady=10)

    def update_ui(self):
        s = self.var_source.get()
        if s == "default":
            self.btn_ts.config(state="disabled")
            self.btn_cust.config(state="disabled")
            self.source_path = self.work_path
        elif s == "test_suite":
            self.btn_ts.config(state="normal")
            self.btn_cust.config(state="disabled")
        else:
            self.btn_ts.config(state="disabled")
            self.btn_cust.config(state="normal")
            self.source_path = self.user_programs
        self.lbl_selected.config(text=f"路径: {self.source_path}")

    def browse_ts(self):
        path = filedialog.askdirectory(initialdir=self.ts_path)
        if path:
            self.source_path = path
            self.lbl_selected.config(text=f"路径: {path}")

    def browse_cust(self):
        path = filedialog.askdirectory(initialdir=self.user_programs)
        if path:
            self.source_path = path
            self.lbl_selected.config(text=f"路径: {path}")

    def submit(self):
        try:
            name = validate_project_name(self.name_entry.get())
        except ValueError as exc:
            messagebox.showwarning("警告", str(exc))
            return

        self.project_name = name
        self.target_dir = project_dir(self.user_programs, name)
        self.destroy()


def create_new_program(parent_root=None):
    if parent_root is None:
        parent_root = tk.Tk()
        parent_root.withdraw()

    dialog = NewProjectDialog(parent_root)
    parent_root.wait_window(dialog)

    if not hasattr(dialog, "target_dir") or dialog.target_dir is None:
        return

    try:
        target_dir = create_project(
            name=dialog.project_name,
            template_dir=dialog.source_path,
            user_programs=dialog.user_programs,
            defaults_dir=dialog.defaults_path,
        )
        start_ide(target_dir)
    except ValueError as exc:
        messagebox.showwarning("项目名无效", str(exc))
    except Exception as exc:  # noqa: BLE001 - 原实现同样以弹窗报告失败
        messagebox.showerror("创建失败", f"错误详情:\n{str(exc)}")

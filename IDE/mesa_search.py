"""参数名搜索组件（Tk 视图）。

**P15 修复（阶段 3）**：数据访问不再直接 ``import sqlite3`` 开连接，
统一委托 :class:`core.db.ParamDatabase`（其查询语义由
``tests/test_db_snapshot.py`` / ``tests/test_core_db.py`` 锁定）。

对外行为不变：FTS5 前缀搜索（去引号 + ``*``）、最多 20 条、
双击列表项复制参数名、Esc 关闭弹出面板。
"""

import logging
import tkinter as tk
from tkinter import ttk

from core.db import ParamDatabase

logger = logging.getLogger(__name__)


class MesaSearchComponent:
    def __init__(self, parent_toolbar, db_path=None, database=None):
        self.database = database if database is not None else ParamDatabase(db_path)
        self.db_path = self.database.db_path
        self.parent = parent_toolbar
        self.master_root = parent_toolbar.winfo_toplevel()

        # 必须在注册 StringVar 的 trace **之前**初始化：trace 一装上，
        # 之后任何一次写入（包括初始化占位符）都会立刻回调 on_search_change，
        # 那时再访问 self.popup 就是 AttributeError（N7）。
        self.popup = None
        self.desc_text = None
        self.current_descriptions = {}
        self.tree = None

        self.PLACEHOLDER = " 输入参数名或关键词搜索(如 Dutch)..."

        self.search_var = tk.StringVar(master=self.master_root)
        self.search_var.trace_add("write", self.on_search_change)

        self.entry = ttk.Entry(parent_toolbar, textvariable=self.search_var, width=50)
        self.entry.insert(0, self.PLACEHOLDER)
        self.entry.pack(side=tk.LEFT, padx=10)

        self.entry.bind("<FocusIn>", self._clear_placeholder)
        self.entry.bind("<FocusOut>", self._add_placeholder)

    def _clear_placeholder(self, event):
        if self.search_var.get() == self.PLACEHOLDER:
            self.search_var.set("")
            self.entry.config(foreground="black")

    def _add_placeholder(self, event):
        if self.search_var.get().strip() == "":
            self.search_var.set(self.PLACEHOLDER)
            self.entry.config(foreground="gray")

    def on_search_change(self, *args):
        query = self.search_var.get().strip()
        # 与占位符比较时两边都要 strip：占位符自身带前导空格，
        # 原实现只 strip 了 query，导致占位符被当成查询词而弹出结果面板
        if query == self.PLACEHOLDER.strip() or not query or len(query) < 2:
            self.close_popup()
            return

        results = self.perform_search(query)
        self.show_popup(results)

    def perform_search(self, query):
        """FTS5 前缀搜索；返回 ``ParameterRow`` 列表（失败返回空列表）。"""
        return self.database.search(query, limit=20)

    def show_popup(self, results):
        if not results:
            self.close_popup()
            return

        if self.popup is None:
            self.popup = tk.Toplevel(self.master_root)
            self.popup.overrideredirect(True)
            self.popup.attributes("-topmost", True)

            main_frame = ttk.Frame(self.popup, borderwidth=1, relief="solid")
            main_frame.pack(fill=tk.BOTH, expand=True)

            style = ttk.Style()
            style.configure("Treeview", rowheight=25)

            self.tree = ttk.Treeview(main_frame, columns=("name", "def", "group"),
                                     show="headings", height=8)
            self.tree.heading("name", text="参数名")
            self.tree.heading("def", text="默认值")
            self.tree.heading("group", text="来源(文件)")

            self.tree.column("name", width=220, anchor="w")
            self.tree.column("def", width=100, anchor="center")
            self.tree.column("group", width=120, anchor="center")
            self.tree.pack(side=tk.TOP, fill=tk.BOTH, expand=False)

            desc_frame = ttk.LabelFrame(main_frame, text="参数说明 (双击列表项可复制参数名)")
            desc_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, padx=5, pady=5)

            # 字体族运行期解析：写死 Consolas 在没有它的机器上会落到无中文字形
            # 的族，参数说明里的中文会变方框
            from ide_ui.fonts import mono_font_family

            self.desc_text = tk.Text(desc_frame, height=8, width=60, wrap="word",
                                     font=(mono_font_family(), 10), bg="#f8f9fa")
            self.desc_text.pack(fill=tk.BOTH, expand=True)
            self.desc_text.config(state=tk.DISABLED)

            self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
            self.tree.bind("<Double-1>", self.on_double_click_copy)
            self.tree.bind("<Escape>", lambda e: self.close_popup())

        for item in self.tree.get_children():
            self.tree.delete(item)
        self.current_descriptions.clear()

        for row in results:
            self.tree.insert("", "end",
                             values=(row.name, row.default_value, row.namelist_group))
            self.current_descriptions[row.name] = (
                row.description if row.description else "（该参数暂无详细说明）"
            )

        first_item = self.tree.get_children()[0]
        self.tree.selection_set(first_item)
        self.tree.focus(first_item)

        x = self.entry.winfo_rootx()
        y = self.entry.winfo_rooty() + self.entry.winfo_height()
        self.popup.geometry(f"500x350+{x}+{y}")
        self.popup.deiconify()

    def on_tree_select(self, event):
        selected_items = self.tree.selection()
        if not selected_items:
            return

        item = selected_items[0]
        item_values = self.tree.item(item)['values']
        param_name = item_values[0]
        description_text = self.current_descriptions.get(param_name, "")

        self.desc_text.config(state=tk.NORMAL)
        self.desc_text.delete("1.0", tk.END)
        self.desc_text.insert(tk.END, description_text)
        self.desc_text.config(state=tk.DISABLED)

    def on_double_click_copy(self, event):
        item = self.tree.focus()
        if not item:
            return

        item_values = self.tree.item(item)['values']
        param_name = item_values[0]

        self.master_root.clipboard_clear()
        self.master_root.clipboard_append(param_name)
        logger.debug("已复制参数名到剪贴板: %s", param_name)

        self.close_popup()
        self.search_var.set("")
        self._add_placeholder(None)

    def close_popup(self):
        if self.popup:
            self.popup.destroy()
            self.popup = None
            self.desc_text = None

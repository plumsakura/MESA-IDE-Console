"""项目文件树（左栏）。

拆自原 ``IDE.py`` 的 ``setup_treeview`` / ``populate_tree`` / ``refresh_project_tree``，
并修复：

- **P10**：原 ``populate_tree`` 用裸 ``except: pass`` 吞掉一切异常
  （目录无权限时树静默不完整），现在记录 ``OSError`` 警告；
- 原实现在树节点 ``values[0]`` 里存绝对路径，行为保持不变。
"""

from __future__ import annotations

import logging
import os
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

logger = logging.getLogger(__name__)

HIDDEN_PREFIX = "."


class ProjectTree:
    """项目目录树；双击文件触发 ``on_open``。"""

    def __init__(self, parent: tk.Widget, *, on_open: Callable[[str], object] | None = None) -> None:
        self.frame = ttk.Frame(parent, width=250)
        self.tree = ttk.Treeview(self.frame)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-1>", self._on_double_click)
        self._on_open = on_open
        self.root_path: str | None = None

    # ---------------- 构建 ----------------

    def refresh(self, root_path: str) -> int:
        """重建整棵树，返回插入的条目总数。

        目录不存在/不可读时不再静默留空：插入一条可读的提示节点，
        用户立刻知道"文件树为什么是空的"，而不是以为界面坏了。
        """
        self.root_path = root_path
        self.tree.delete(*self.tree.get_children())
        if not os.path.isdir(root_path):
            self.tree.insert("", "end", text=f"（项目目录不存在: {root_path}）", values=[""])
            return 0
        return self._populate(root_path, "")

    def _populate(self, path: str, node: str) -> int:
        try:
            entries = sorted(os.listdir(path))
        except OSError as exc:
            logger.warning("无法列出目录 %s: %s", path, exc)
            return 0

        count = 0
        for item in entries:
            if item.startswith(HIDDEN_PREFIX):
                continue
            absolute = os.path.join(path, item)
            child = self.tree.insert(node, "end", text=item, values=[absolute])
            count += 1
            if os.path.isdir(absolute):
                count += self._populate(absolute, child)
        return count

    def node_count(self) -> int:
        """当前树中的节点总数（测试用）。"""
        def count_children(node: str) -> int:
            children = self.tree.get_children(node)
            return len(children) + sum(count_children(child) for child in children)

        return count_children("")

    # ---------------- 选择 ----------------

    def selected_path(self) -> str | None:
        item = self.tree.focus()
        if not item:
            return None
        values = self.tree.item(item, "values")
        return str(values[0]) if values else None

    def open_selected(self) -> str | None:
        """打开当前选中项（仅文件）；返回被打开的路径。"""
        path = self.selected_path()
        if path and os.path.isfile(path):
            if self._on_open is not None:
                self._on_open(path)
            return path
        return None

    def _on_double_click(self, _event: object) -> None:
        self.open_selected()

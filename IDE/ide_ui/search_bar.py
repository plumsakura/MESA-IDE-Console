"""参数名搜索条（包装 ``mesa_search.MesaSearchComponent``）。

拆自原 ``IDE.py`` 的 ``toggle_param_search`` / ``_clear_search_bar``，并修复：

- **P19**：原实现用 Tk 内部组件名 ``self.root.children.get("!frame", None)``
  作为 ``pack(after=...)`` 的锚点，脆弱且依赖控件创建顺序
  → 现在由外层显式传入锚点控件（工具栏 ``Frame``）；
- **崩溃的清理 hack**：原实现对 ``MesaSearchComponent`` 实例调用
  ``winfo_children()``（该实例不是控件、无此方法），每次点击"参数名搜索"
  都会抛 ``AttributeError``（被 Tk 静默打印），且从未真正清理任何东西
  → 已删除该 hack。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from mesa_search import MesaSearchComponent


class ParameterSearchBar:
    """可显示/隐藏的参数搜索条。"""

    def __init__(self, parent: tk.Widget, *, database: object | None = None) -> None:
        self.frame = ttk.Frame(parent, padding="5")
        self._anchor: tk.Widget | None = None
        self._visible = False

        self.component = MesaSearchComponent(self.frame, database=database)
        self.component.entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(self.frame, text="[关闭X]", command=self.hide).pack(side=tk.RIGHT, padx=5)

    # ---------------- 显示控制 ----------------

    def set_anchor(self, widget: tk.Widget) -> None:
        """设置 pack 锚点（工具栏），使搜索条出现在工具栏正下方。"""
        self._anchor = widget

    @property
    def visible(self) -> bool:
        return self._visible

    def show(self) -> None:
        if self._visible:
            return
        self.component.close_popup()
        if self._anchor is not None:
            self.frame.pack(side=tk.TOP, fill=tk.X, after=self._anchor)
        else:
            self.frame.pack(side=tk.TOP, fill=tk.X)
        self._visible = True

    def hide(self) -> None:
        self.component.close_popup()
        if not self._visible:
            return
        self.frame.pack_forget()
        self._visible = False

    def toggle(self) -> bool:
        """切换显示状态，返回切换后是否可见。"""
        if self._visible:
            self.hide()
        else:
            self.show()
        return self._visible

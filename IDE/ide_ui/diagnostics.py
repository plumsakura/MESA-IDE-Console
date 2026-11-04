"""诊断面板：消息格式化/解析（纯逻辑）+ Tk 列表视图。

拆自原 ``IDE.py`` 的两份 ``setup_diag_panel``/``hide_diagnostics``/``on_diag_click``
（P1 重复定义），并修复：

- **P19 相邻问题**：原 ``on_diag_click`` 用 ``re.search(r'\\[(.*?)\\] L(\\d+)')``
  就地解析显示文本，文件名含 ``]`` 时会错位；现在格式化与解析集中在
  :func:`format_issue` / :func:`parse_diagnostic`，可单测；
- 原 ``hide_diagnostics`` 有两个版本，其一调用 ``root.update()``（会重入事件循环），
  现只保留 ``update_idletasks()``。
"""

from __future__ import annotations

import re
import tkinter as tk
from collections.abc import Callable, Iterable, Mapping
from tkinter import ttk
from typing import Any

DIAG_PATTERN = re.compile(r"\[(?P<file>.+?)\]\s*L(?P<line>\d+)")
PANEL_TITLE = " ⚠ 诊断与搜索结果面板"
DIAG_LIST_FONT_SIZE = 10


def diag_title_font() -> tuple[str, int, str]:
    """面板标题字体（原写死 YaHei；缺失时回退到可用中文字体）。"""
    from ide_ui.fonts import ui_font_family

    return (ui_font_family(), 10, "bold")


def diag_list_font() -> tuple[str, int]:
    """运行期解析诊断列表字体（原先写死 Consolas；缺失时会落到无中文字形的族）。"""
    from ide_ui.fonts import mono_font_family

    return (mono_font_family(), DIAG_LIST_FONT_SIZE)
SUCCESS_MESSAGE = "✓ 语法检测通过！"
SUCCESS_COLOR = "green"


def _field(issue: Mapping[str, Any] | Any, name: str, default: Any) -> Any:
    if isinstance(issue, Mapping):
        return issue.get(name, default)
    return getattr(issue, name, default)


def format_issue(filename: str, issue: Mapping[str, Any] | Any) -> str:
    """把一条问题格式化成 ``[文件] L行号: 消息``（与原实现一致）。"""
    line = _field(issue, "line", 1)
    message = _field(issue, "message", "未知错误")
    return f"[{filename}] L{line}: {message}"


def parse_diagnostic(message: str) -> tuple[str, int] | None:
    """从诊断文本解析 ``(文件名, 行号)``；无法解析返回 None。"""
    match = DIAG_PATTERN.search(message or "")
    if match is None:
        return None
    return match.group("file"), int(match.group("line"))


class DiagnosticsPanel:
    """诊断与搜索结果面板（不做显示/隐藏，由外层 PanedWindow 控制）。"""

    def __init__(
        self,
        parent: tk.Widget,
        *,
        on_jump: Callable[[str, int], Any] | None = None,
        on_close: Callable[[], Any] | None = None,
    ) -> None:
        self.frame = ttk.Frame(parent, height=200)
        self._on_jump = on_jump

        header = ttk.Frame(self.frame)
        header.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(
            header, text=PANEL_TITLE, font=diag_title_font()
        ).pack(side=tk.LEFT, padx=5)
        ttk.Button(header, text="关闭 [X]", command=self._close).pack(side=tk.RIGHT, padx=5)
        self._on_close = on_close

        self.listbox = tk.Listbox(
            self.frame, font=diag_list_font(), fg="#333", selectmode=tk.SINGLE
        )
        self.listbox.pack(fill=tk.BOTH, expand=True)
        self.listbox.bind("<Double-1>", self._on_double_click)

    # ---------------- 内容 ----------------

    def clear(self) -> None:
        self.listbox.delete(0, tk.END)

    def add(self, message: str, color: str | None = None) -> None:
        self.listbox.insert(tk.END, message)
        if color:
            self.listbox.itemconfig(tk.END, fg=color)

    def add_issues(self, filename: str, issues: Iterable[Mapping[str, Any] | Any]) -> int:
        """追加若干问题，返回追加条数。"""
        count = 0
        for issue in issues:
            self.add(format_issue(filename, issue))
            count += 1
        return count

    def entries(self) -> list[str]:
        return list(self.listbox.get(0, tk.END))

    # ---------------- 事件 ----------------

    def _on_double_click(self, _event: object) -> None:
        self.jump_to_selection()

    def jump_to_selection(self) -> bool:
        """跳转到当前选中项对应的文件与行号；成功返回 True。"""
        selection = self.listbox.curselection()
        if not selection or self._on_jump is None:
            return False
        parsed = parse_diagnostic(self.listbox.get(selection[0]))
        if parsed is None:
            return False
        filename, line_number = parsed
        self._on_jump(filename, line_number)
        return True

    def _close(self) -> None:
        if self._on_close is not None:
            self._on_close()

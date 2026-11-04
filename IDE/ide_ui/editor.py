"""多标签编辑器：纯逻辑注册表 + Tk 视图。

拆自原 ``IDE.py``，消除以下基线缺陷：

- **P1/P2**：``open_file_in_tab``/``initial_open_core_files`` 等 9 个方法在
  ``IDE.py`` 中被重复定义两次（后者静默覆盖前者），本模块只保留一份实现；
- **P20**：标签页原先以 ``basename`` 为键，不同目录的同名文件互相顶替
  → 现在以规范化绝对路径为键，显示名在重名时自动加父目录前缀；
- **数据丢失**：原第二版 ``open_file_in_tab`` 读取失败时 ``except: pass``
  仍注册空标签页，随后"保存并检查"会把空内容写回磁盘
  → 现在读取失败只提示、**不创建标签页**。
"""

from __future__ import annotations

import logging
import os
import tkinter as tk
from collections.abc import Iterable
from dataclasses import dataclass, field
from tkinter import messagebox, scrolledtext

logger = logging.getLogger(__name__)

#: 等宽字体大小；字体族在运行期解析（见 :func:`editor_font`），避免在没有
#: Consolas 也没有中文字体的机器上把中文显示成方框
EDITOR_FONT_SIZE = 12
ERROR_TAG = "error_line"
TAB_END = tk.END


def editor_font() -> tuple[str, int]:
    """运行期解析编辑器字体（调用时需已有 Tk 根窗口）。"""
    from ide_ui.fonts import mono_font_family

    return (mono_font_family(), EDITOR_FONT_SIZE)


def normalize_for_save(content: str) -> str:
    """保存前规范化：CRLF/CR → LF，去首尾空白，末尾补一个换行。

    **与原实现（``IDE.py:252``）逐字一致** —— 包括 ``strip()`` 会改动文件
    首尾空白这一点。修掉它属于"会改变用户文件内容"的变更，需人工确认。
    """
    return content.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"


def document_key(path: str) -> str:
    """标签页唯一键：规范化绝对路径（修复 P20）。"""
    return os.path.normcase(os.path.abspath(path))


def display_label(path: str, taken: Iterable[str] = ()) -> str:
    """标签显示名：文件名；重名时加父目录名，仍重名则编号。"""
    taken_set = set(taken)
    name = os.path.basename(path)
    if name not in taken_set:
        return name
    parent = os.path.basename(os.path.dirname(os.path.abspath(path)))
    candidate = f"{parent}/{name}" if parent else name
    counter = 2
    while candidate in taken_set:
        candidate = f"{parent}({counter})/{name}" if parent else f"{name}({counter})"
        counter += 1
    return candidate


@dataclass
class Document:
    """一个已打开的文档。"""

    path: str
    key: str
    label: str
    widget: object = field(default=None, repr=False, compare=False)

    @property
    def basename(self) -> str:
        return os.path.basename(self.path)


class TabRegistry:
    """已打开文档的注册表（纯逻辑，不依赖 Tk，可单测）。"""

    def __init__(self) -> None:
        self._documents: dict[str, Document] = {}

    def get(self, path: str) -> Document | None:
        return self._documents.get(document_key(path))

    def register(self, path: str, widget: object = None, label: str | None = None) -> Document:
        key = document_key(path)
        existing = self._documents.get(key)
        if existing is not None:
            if widget is not None:
                existing.widget = widget
            return existing
        document = Document(
            path=path,
            key=key,
            label=label or display_label(path, self.labels()),
            widget=widget,
        )
        self._documents[key] = document
        return document

    def unregister(self, path: str) -> Document | None:
        return self._documents.pop(document_key(path), None)

    def labels(self) -> set[str]:
        return {document.label for document in self._documents.values()}

    def paths(self) -> list[str]:
        return [document.path for document in self._documents.values()]

    def find_by_label(self, label: str) -> Document | None:
        for document in self._documents.values():
            if document.label == label or document.basename == label:
                return document
        return None

    def __len__(self) -> int:
        return len(self._documents)

    def __iter__(self):
        return iter(self._documents.values())


class EditorTabs:
    """管理 ``ttk.Notebook`` 中的文本标签页。"""

    def __init__(self, notebook: tk.Widget) -> None:
        self.notebook = notebook
        self.registry = TabRegistry()

    # ---------------- 查询 ----------------

    def documents(self) -> list[Document]:
        return list(self.registry)

    def document_for_path(self, path: str) -> Document | None:
        return self.registry.get(path)

    def __len__(self) -> int:
        return len(self.registry)

    # ---------------- 打开 / 保存 ----------------

    def open_file(self, path: str) -> Document | None:
        """打开文件；已打开则切换标签页。读取失败时提示且不创建标签页。"""
        existing = self.registry.get(path)
        if existing is not None:
            self.notebook.select(existing.widget)
            return existing

        try:
            with open(path, "r", encoding="utf-8") as handle:
                content = handle.read()
        except Exception as exc:  # noqa: BLE001 - 需向用户报告，不能静默
            logger.error("无法读取文件 %s: %s", path, exc)
            messagebox.showerror("错误", f"无法读取文件: {exc}")
            return None

        widget = scrolledtext.ScrolledText(
            self.notebook, undo=True, font=editor_font(), wrap=tk.NONE
        )
        widget.tag_configure(ERROR_TAG, underline=True, underlinefg="red")
        widget.insert(TAB_END, content)

        label = display_label(path, self.registry.labels())
        self.notebook.add(widget, text=label)
        self.notebook.select(widget)
        return self.registry.register(path, widget, label)

    def save_all(self) -> list[str]:
        """把所有已打开标签页写回磁盘，返回写出的路径列表。"""
        written: list[str] = []
        for document in self.registry:
            content = normalize_for_save(document.widget.get("1.0", TAB_END))
            with open(document.path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
            written.append(document.path)
        return written

    # ---------------- 诊断标记 ----------------

    def clear_error_marks(self) -> None:
        for document in self.registry:
            document.widget.tag_remove(ERROR_TAG, "1.0", TAB_END)

    def mark_error_line(self, label: str, line_number: int) -> None:
        document = self.registry.find_by_label(label)
        if document is None:
            return
        document.widget.tag_add(ERROR_TAG, f"{line_number}.0", f"{line_number}.end")

    def focus_line(self, label: str, line_number: int) -> bool:
        """切换到该标签页并把光标移到指定行；找不到返回 False。"""
        document = self.registry.find_by_label(label)
        if document is None:
            return False
        self.notebook.select(document.widget)
        document.widget.see(f"{line_number}.0")
        document.widget.mark_set("insert", f"{line_number}.0")
        document.widget.focus_set()
        return True

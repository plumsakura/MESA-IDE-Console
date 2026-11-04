"""UI 组件测试（Tk 视图层）。

需要可用显示器；``TclError`` 时自动跳过整个类（headless CI 仍能跑其余测试）。
所有用例都继承 ``SafeDialogTestCase``（真实模态弹窗会永久挂起测试）。
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import tkinter as tk
import unittest
from collections.abc import Callable
from tkinter import ttk
from unittest import mock

from core.db import ParamDatabase
from ide_ui.diagnostics import (
    SUCCESS_MESSAGE,
    DiagnosticsPanel,
    format_issue,
    parse_diagnostic,
)
from ide_ui.editor import (
    EditorTabs,
    TabRegistry,
    display_label,
    document_key,
    normalize_for_save,
)
from ide_ui.project_tree import ProjectTree
from ide_ui.search_bar import ParameterSearchBar
from tests.helpers import DB_PATH, SafeDialogTestCase

#: 在子进程中探测 Tk（进程内探测在部分环境下会永久阻塞）
TK_PROBE_CODE = "import tkinter as tk; r = tk.Tk(); r.withdraw(); r.destroy()"
TK_PROBE_TIMEOUT = 10.0
X11_SOCKET_DIR = "/tmp/.X11-unix"

_tk_probe_cache: tuple[bool, str] | None = None


def local_x11_socket_present(
    display: str | None,
    socket_exists: Callable[[str], bool] = os.path.exists,
) -> bool | None:
    """本地 ``:N`` 显示时，快速判断 X11 unix socket 是否存在。

    - 返回 ``True``/``False``：可直接判定；
    - 返回 ``None``：无法判定（远程/TCP 显示或 DISPLAY 缺失之外的形式），
      需交给子进程探测。
    """
    if not display:
        return False
    if not display.startswith(":"):
        return None
    number = display[1:].split(".")[0]
    if not number.isdigit():
        return None
    return socket_exists(os.path.join(X11_SOCKET_DIR, f"X{number}"))


def tk_reachable(
    *,
    display: str | None = None,
    socket_exists: Callable[[str], bool] = os.path.exists,
    runner: Callable[..., "subprocess.CompletedProcess[str]"] = subprocess.run,
    timeout: float = TK_PROBE_TIMEOUT,
    use_cache: bool = True,
) -> tuple[bool, str]:
    """探测 Tk 是否真的可用，返回 ``(是否可用, 说明)``。

    **必须在子进程中探测**：当 X11 socket 不可达（例如沙箱/容器把
    ``/tmp`` 换成 tmpfs，遮蔽了 ``/tmp/.X11-unix``）时，``tk.Tk()`` 会
    **永久阻塞**而不是抛 ``TclError``；在进程内探测会挂死整个测试套件。

    本地 ``:N`` 显示先用 socket 存在性做快速短路，避免每次都白等超时。
    """
    global _tk_probe_cache
    if use_cache and _tk_probe_cache is not None:
        return _tk_probe_cache

    resolved_display = os.environ.get("DISPLAY") if display is None else display
    quick = local_x11_socket_present(resolved_display, socket_exists)
    if quick is False:
        result = (False, f"X11 socket 不存在（DISPLAY={resolved_display!r}）")
    else:
        try:
            completed = runner(
                [sys.executable, "-c", TK_PROBE_CODE],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            result = (False, f"Tk 探测超时 {timeout:g}s（X11 不可达？）")
        except OSError as exc:
            result = (False, f"无法启动探测子进程: {exc}")
        else:
            if completed.returncode == 0:
                result = (True, "ok")
            else:
                lines = (completed.stderr or completed.stdout or "").strip().splitlines()
                result = (False, lines[-1] if lines else f"退出码 {completed.returncode}")

    if use_cache:
        _tk_probe_cache = result
    return result


def reset_tk_probe_cache(value: tuple[bool, str] | None = None) -> None:
    """重置探测缓存（供测试隔离；生产代码不需要）。"""
    global _tk_probe_cache
    _tk_probe_cache = value


def require_tk(test_case_class) -> None:
    """Tk 不可用时跳过整个测试类（绝不阻塞）。"""
    ok, detail = tk_reachable()
    if not ok:
        raise unittest.SkipTest(f"无可用显示，跳过 UI 测试: {detail}")


class TkProbeLogic(unittest.TestCase):
    """探测逻辑本身的自测（不需要显示器，也不允许真的阻塞）。"""

    def setUp(self) -> None:
        # 与同一进程内其他 UI 测试类的探测结果隔离
        self._saved_cache = _tk_probe_cache
        reset_tk_probe_cache(None)

        self.calls: list[tuple] = []

        def fake_runner(*args, **kwargs):
            self.calls.append((args, kwargs))
            return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="", stderr="")

        self.runner = fake_runner

    def tearDown(self) -> None:
        reset_tk_probe_cache(self._saved_cache)

    def test_local_display_without_socket_short_circuits(self) -> None:
        ok, detail = tk_reachable(
            display=":0",
            socket_exists=lambda path: False,
            runner=self.runner,
            use_cache=False,
        )
        self.assertFalse(ok)
        self.assertIn("X11 socket 不存在", detail)
        self.assertEqual(self.calls, [], "socket 缺失时不应启动子进程（避免白等超时）")

    def test_missing_display_is_unreachable(self) -> None:
        ok, _detail = tk_reachable(display="", runner=self.runner, use_cache=False)
        self.assertFalse(ok)
        self.assertEqual(self.calls, [])

    def test_existing_socket_delegates_to_subprocess_probe(self) -> None:
        ok, detail = tk_reachable(
            display=":0",
            socket_exists=lambda path: True,
            runner=self.runner,
            use_cache=False,
        )
        self.assertTrue(ok)
        self.assertEqual(detail, "ok")
        self.assertEqual(len(self.calls), 1, "socket 存在时仍需真实探测")

    def test_remote_display_delegates_to_subprocess_probe(self) -> None:
        ok, _detail = tk_reachable(
            display="host:0.0", runner=self.runner, use_cache=False
        )
        self.assertTrue(ok)
        self.assertEqual(len(self.calls), 1)

    def test_timeout_is_reported_not_raised(self) -> None:
        def timing_out(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd="probe", timeout=1.0)

        ok, detail = tk_reachable(
            display="host:0.0", runner=timing_out, timeout=1.0, use_cache=False
        )
        self.assertFalse(ok)
        self.assertIn("超时", detail)

    def test_nonzero_exit_reports_last_stderr_line(self) -> None:
        def failing(*args, **kwargs):
            return subprocess.CompletedProcess(
                args=args[0], returncode=1, stdout="", stderr="no display name\n"
            )

        ok, detail = tk_reachable(display="host:0.0", runner=failing, use_cache=False)
        self.assertFalse(ok)
        self.assertIn("no display name", detail)

    def test_result_is_cached(self) -> None:
        tk_reachable(display="", use_cache=True)
        ok, _detail = tk_reachable(display=":0", use_cache=True)
        self.assertFalse(ok, "缓存命中后应复用第一次（不可用）的结果")


class TkTestCase(SafeDialogTestCase):
    """带 Tk 根窗口的测试基类。"""

    @classmethod
    def setUpClass(cls) -> None:
        require_tk(cls)

    def setUp(self) -> None:
        super().setUp()
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)


# ---------------------------------------------------------------------------
# 纯逻辑（不依赖 Tk）
# ---------------------------------------------------------------------------

class EditorPureLogic(unittest.TestCase):
    def test_normalize_for_save_matches_baseline(self) -> None:
        self.assertEqual(normalize_for_save("a\r\nb\r\n"), "a\nb\n")
        self.assertEqual(normalize_for_save("a\r\nb\r"), "a\nb\n")
        self.assertEqual(normalize_for_save("  a  "), "a\n")
        self.assertEqual(normalize_for_save("a\n\n\n"), "a\n")

    def test_document_key_distinguishes_same_basename(self) -> None:
        """P20 回归：不同目录的同名文件必须得到不同键。"""
        self.assertNotEqual(document_key("/d1/inlist"), document_key("/d2/inlist"))
        self.assertEqual(document_key("/d1/inlist"), document_key("/d1/./inlist"))

    def test_display_label_disambiguates_duplicates(self) -> None:
        self.assertEqual(display_label("/a/inlist", ()), "inlist")
        self.assertEqual(display_label("/d1/inlist", {"inlist"}), "d1/inlist")
        self.assertEqual(
            display_label("/d2/inlist", {"inlist", "d1/inlist"}), "d2/inlist"
        )
        # 同名同父目录第三次出现 → 编号
        self.assertEqual(
            display_label("/d1/inlist", {"inlist", "d1/inlist"}), "d1(2)/inlist"
        )


class TabRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = TabRegistry()

    def test_register_and_get(self) -> None:
        document = self.registry.register("/a/inlist", widget="W")
        self.assertIs(self.registry.get("/a/inlist"), document)
        self.assertEqual(document.label, "inlist")

    def test_duplicate_path_returns_existing_document(self) -> None:
        first = self.registry.register("/a/inlist", widget="W1")
        second = self.registry.register("/a/inlist", widget="W2")
        self.assertIs(first, second)
        self.assertEqual(len(self.registry), 1)
        self.assertEqual(first.widget, "W2")

    def test_labels_include_disambiguated_names(self) -> None:
        self.registry.register("/d1/inlist")
        self.registry.register("/d2/inlist")
        self.assertEqual(self.registry.labels(), {"inlist", "d2/inlist"})

    def test_unregister(self) -> None:
        self.registry.register("/a/inlist")
        self.assertIsNotNone(self.registry.unregister("/a/inlist"))
        self.assertIsNone(self.registry.get("/a/inlist"))

    def test_find_by_label_prefers_exact_then_basename(self) -> None:
        document = self.registry.register("/d1/inlist")
        self.assertIs(self.registry.find_by_label("inlist"), document)
        self.assertIsNone(self.registry.find_by_label("不存在"))


class DiagnosticsFormatting(unittest.TestCase):
    def test_format_issue_matches_baseline(self) -> None:
        self.assertEqual(
            format_issue("inlist", {"line": 3, "message": "坏了"}),
            "[inlist] L3: 坏了",
        )
        self.assertEqual(
            format_issue("inlist", {"line": 1}), "[inlist] L1: 未知错误"
        )

    def test_parse_diagnostic_roundtrip(self) -> None:
        self.assertEqual(parse_diagnostic("[inlist] L3: 坏了"), ("inlist", 3))

    def test_parse_handles_brackets_inside_filename(self) -> None:
        self.assertEqual(parse_diagnostic("[a]b] L12: x"), ("a]b", 12))

    def test_parse_returns_none_for_garbage(self) -> None:
        self.assertIsNone(parse_diagnostic("没有行号的消息"))
        self.assertIsNone(parse_diagnostic(""))


# ---------------------------------------------------------------------------
# Tk 组件
# ---------------------------------------------------------------------------

class EditorTabsTests(TkTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack()
        self.tabs = EditorTabs(self.notebook)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_open_same_basename_from_two_dirs_creates_two_tabs(self) -> None:
        base = pathlib.Path(self._tmp.name)
        (base / "one").mkdir()
        (base / "two").mkdir()
        first = base / "one" / "inlist"
        second = base / "two" / "inlist"
        first.write_text("a\n", encoding="utf-8")
        second.write_text("b\n", encoding="utf-8")

        doc1 = self.tabs.open_file(str(first))
        doc2 = self.tabs.open_file(str(second))

        self.assertEqual(len(self.tabs), 2, "P20 回归：同名文件必须各占一个标签页")
        self.assertNotEqual(doc1.key, doc2.key)
        self.assertEqual(doc1.label, "inlist")
        self.assertEqual(doc2.label, "two/inlist")

    def test_reopen_existing_path_selects_existing_tab(self) -> None:
        target = pathlib.Path(self._tmp.name) / "inlist"
        target.write_text("a\n", encoding="utf-8")
        doc1 = self.tabs.open_file(str(target))
        doc2 = self.tabs.open_file(str(target))
        self.assertIs(doc1, doc2)
        self.assertEqual(len(self.tabs), 1)

    def test_save_all_normalizes_content(self) -> None:
        target = pathlib.Path(self._tmp.name) / "inlist"
        target.write_text("original\n", encoding="utf-8")
        document = self.tabs.open_file(str(target))

        document.widget.delete("1.0", tk.END)
        document.widget.insert(tk.END, "  X\r\nY\r\n  ")

        written = self.tabs.save_all()
        self.assertEqual(written, [str(target)])
        self.assertEqual(target.read_text(encoding="utf-8"), "X\nY\n")

    def test_unreadable_file_reports_error_and_keeps_file_intact(self) -> None:
        """数据丢失回归：读取失败绝不能注册空标签页（否则保存会写空文件）。"""
        target = pathlib.Path(self._tmp.name) / "locked.txt"
        target.write_text("KEEP ME\n", encoding="utf-8")

        with mock.patch("builtins.open", side_effect=OSError("拒绝访问")):
            document = self.tabs.open_file(str(target))

        self.assertIsNone(document)
        self.assertEqual(len(self.tabs), 0)
        self.assertEqual(target.read_text(encoding="utf-8"), "KEEP ME\n")
        self.assertTrue(
            any(kind == "showerror" for kind, _args, _kw in self.dialog_calls),
            "读取失败必须向用户报告",
        )

    def test_focus_line_moves_insert_mark(self) -> None:
        target = pathlib.Path(self._tmp.name) / "inlist"
        target.write_text("l1\nl2\nl3\n", encoding="utf-8")
        document = self.tabs.open_file(str(target))

        self.assertTrue(self.tabs.focus_line(document.label, 3))
        self.assertEqual(document.widget.index(tk.INSERT), "3.0")
        self.assertFalse(self.tabs.focus_line("不存在的标签", 1))


class DiagnosticsPanelTests(TkTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.jumped = None
        self.closed = False
        self.panel = DiagnosticsPanel(
            self.root,
            on_jump=lambda fname, line: setattr(self, "jumped", (fname, line)),
            on_close=lambda: setattr(self, "closed", True),
        )
        self.panel.frame.pack()

    def test_add_and_entries(self) -> None:
        self.panel.add("第一条")
        self.panel.add("第二条", color="green")
        self.assertEqual(self.panel.entries(), ["第一条", "第二条"])

    def test_add_issues_formats_each(self) -> None:
        issues = [
            {"line": 2, "message": "未知参数 'x'"},
            {"line": 4, "message": "检测到非法注释符 '#'。"},
        ]
        self.assertEqual(self.panel.add_issues("inlist", issues), 2)
        self.assertEqual(
            self.panel.entries(),
            ["[inlist] L2: 未知参数 'x'", "[inlist] L4: 检测到非法注释符 '#'。"],
        )

    def test_jump_invokes_callback_with_parsed_target(self) -> None:
        self.panel.add(format_issue("inlist", {"line": 7, "message": "x"}))
        self.panel.listbox.selection_set(0)
        self.assertTrue(self.panel.jump_to_selection())
        self.assertEqual(self.jumped, ("inlist", 7))

    def test_close_button_invokes_on_close(self) -> None:
        self.panel._close()
        self.assertTrue(self.closed)

    def test_clear_empties_list(self) -> None:
        self.panel.add("x")
        self.panel.clear()
        self.assertEqual(self.panel.entries(), [])


class ProjectTreeTests(TkTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.opened = None
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = pathlib.Path(self._tmp.name)
        (base / "inlist").write_text("&controls\n/\n", encoding="utf-8")
        (base / ".hidden").write_text("x", encoding="utf-8")
        (base / "src").mkdir()
        (base / "src" / "inner.txt").write_text("x", encoding="utf-8")

        self.tree = ProjectTree(self.root, on_open=lambda p: setattr(self, "opened", p))
        self.tree.frame.pack()
        self.tree.refresh(str(base))

    def test_lists_files_and_skips_hidden(self) -> None:
        # inlist + src + src/inner.txt = 3 个节点；.hidden 被跳过
        self.assertEqual(self.tree.node_count(), 3)

    def test_selected_path_and_open(self) -> None:
        top = self.tree.tree.get_children("")
        self.assertEqual([self.tree.tree.item(i, "text") for i in top], ["inlist", "src"])
        self.tree.tree.focus(top[0])
        self.assertEqual(os.path.basename(self.tree.selected_path() or ""), "inlist")
        opened = self.tree.open_selected()
        self.assertEqual(opened, self.tree.selected_path())
        self.assertEqual(self.opened, opened)

    def test_refresh_replaces_nodes(self) -> None:
        self.assertEqual(self.tree.node_count(), 3)
        self.tree.refresh(str(pathlib.Path(self._tmp.name)))
        self.assertEqual(self.tree.node_count(), 3)

    def test_unreadable_dir_is_logged_not_raised(self) -> None:
        with mock.patch("os.listdir", side_effect=OSError("无权限")):
            self.assertEqual(self.tree.refresh("/whatever"), 0)


class ParameterSearchBarTests(TkTestCase):
    def setUp(self) -> None:
        super().setUp()
        if not DB_PATH.exists():
            self.skipTest(f"缺少数据库文件: {DB_PATH}")
        self.toolbar = ttk.Frame(self.root)
        self.toolbar.pack(side=tk.TOP, fill=tk.X)
        self.bar = ParameterSearchBar(self.root, database=ParamDatabase(DB_PATH))
        self.addCleanup(self.database_close)
        self.bar.set_anchor(self.toolbar)

    def database_close(self) -> None:
        self.bar.component.database.close()

    def test_show_hide_toggle(self) -> None:
        self.assertFalse(self.bar.visible)
        self.bar.show()
        self.assertTrue(self.bar.visible)
        self.bar.hide()
        self.assertFalse(self.bar.visible)
        self.assertTrue(self.bar.toggle())
        self.assertFalse(self.bar.toggle())

    def test_component_delegates_search_to_core_database(self) -> None:
        results = self.bar.component.perform_search("initial_mass")
        self.assertEqual(len(results), 5)
        self.assertIn("initial_mass", {row.name for row in results})
        self.assertTrue(all(hasattr(row, "namelist_group") for row in results))

    def test_show_twice_is_idempotent(self) -> None:
        self.bar.show()
        self.bar.show()
        self.assertTrue(self.bar.visible)

    def test_typing_before_any_popup_does_not_raise(self) -> None:
        """N7 回归：改动搜索框内容会触发 trace 回调，此时内部状态必须已就绪。

        原实现在 ``StringVar.trace_add`` **之后**才初始化 ``self.popup``，
        于是"第一次输入就抛 AttributeError"（Tk 只把它打到 stderr，界面看着正常，
        搜索却可能悄悄失效）。
        """
        errors: list[BaseException] = []
        self.root.report_callback_exception = (
            lambda exc, val, tb: errors.append(val)  # type: ignore[assignment]
        )

        for text in ("", "i", "in", "initial", self.bar.component.PLACEHOLDER):
            self.bar.component.search_var.set(text)
            self.root.update()

        self.assertEqual(errors, [], f"输入时不应有回调异常: {errors}")
        # 最后写入的是占位符 → 不应弹出结果面板
        self.assertIsNone(self.bar.component.popup)

    def test_valid_query_opens_and_closes_popup_cleanly(self) -> None:
        self.bar.component.search_var.set("initial_mass")
        self.root.update()

        self.assertIsNotNone(self.bar.component.popup, "有效查询应弹出结果面板")
        self.bar.component.close_popup()
        self.assertIsNone(self.bar.component.popup)
        self.assertIsNone(self.bar.component.desc_text)

    def test_popup_state_is_initialised_before_trace_registration(self) -> None:
        component = self.bar.component
        self.assertIsNone(component.popup)
        self.assertIsNone(component.desc_text)
        self.assertEqual(component.current_descriptions, {})


if __name__ == "__main__":
    unittest.main()

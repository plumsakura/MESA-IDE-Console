"""架构守卫测试：这些断言是重构的验收条件本身。

- DuplicateMethodGuard：阶段 3 前 IDE.py 有 9 处重复方法定义（P1，后者静默
  覆盖前者），该守卫当时以 expectedFailure 记录缺陷；阶段 3 修复后已转正，
  成为正式回归测试。
- LayeringGuard：``core/`` 只允许标准库且不得依赖 tkinter/matplotlib；
  ``ide_ui/`` 不得直接依赖 sqlite3/subprocess（数据访问与进程一律经 core）。
"""

from __future__ import annotations

import ast
import pathlib
import sys
import unittest

from tests.helpers import PROJECT_ROOT

DUPLICATE_METHOD_ALLOWLIST: dict[str, list[int]] = {}


def _methods_by_qualified_name(path: pathlib.Path) -> dict[str, list[int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: dict[str, list[int]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found.setdefault(f"{node.name}.{item.name}", []).append(item.lineno)
    return found


def _imported_top_level_modules(path: pathlib.Path) -> set[str]:
    """返回该文件真正 import 的顶层模块名（AST 分析，不看注释/字符串）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # level > 0 表示相对导入，不属于外部依赖
            if node.module and node.level == 0:
                names.add(node.module.split(".")[0])
    return names


class DuplicateMethodGuard(unittest.TestCase):
    def test_ide_py_has_no_duplicate_method_definitions(self) -> None:
        methods = _methods_by_qualified_name(PROJECT_ROOT / "IDE.py")
        duplicates = {
            name: lines
            for name, lines in methods.items()
            if len(lines) > 1 and name not in DUPLICATE_METHOD_ALLOWLIST
        }
        self.assertEqual(duplicates, {}, f"IDE.py 存在重复定义（后者静默覆盖前者）: {duplicates}")

    def test_guard_detects_duplicates_by_construction(self) -> None:
        """自检：守卫本身真的能发现重复定义（避免守卫写成永远通过）。"""
        import tempfile

        src = (
            "class X:\n"
            "    def a(self):\n"
            "        pass\n"
            "    def a(self):\n"
            "        pass\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "sample.py"
            path.write_text(src, encoding="utf-8")
            methods = _methods_by_qualified_name(path)
        self.assertEqual(methods["X.a"], [2, 4])


class LayeringGuard(unittest.TestCase):
    """core/ 必须与 UI 框架解耦（这是将来换语言移植的前提）。"""

    def test_core_package_exists(self) -> None:
        if not (PROJECT_ROOT / "core").is_dir():
            self.skipTest("core/ 尚未创建（阶段 2）")

    def test_core_does_not_import_tkinter_or_matplotlib(self) -> None:
        core = PROJECT_ROOT / "core"
        if not core.is_dir():
            self.skipTest("core/ 尚未创建（阶段 2）")
        forbidden = {"tkinter", "matplotlib"}
        offenders = []
        for py in sorted(core.rglob("*.py")):
            hit = _imported_top_level_modules(py) & forbidden
            if hit:
                offenders.append(f"{py.relative_to(PROJECT_ROOT)}: {sorted(hit)}")
        self.assertEqual(offenders, [], f"core/ 不得依赖 UI/绘图框架: {offenders}")

    def test_core_imports_only_standard_library(self) -> None:
        """core/ 还不得依赖第三方运行库（mesa_reader 也不行）—— 移植友好性要求。"""
        core = PROJECT_ROOT / "core"
        if not core.is_dir():
            self.skipTest("core/ 尚未创建（阶段 2）")
        allowed_third_party: set[str] = set()
        stdlib = set(sys.stdlib_module_names)
        offenders = []
        for py in sorted(core.rglob("*.py")):
            for module in _imported_top_level_modules(py):
                if module == "core" or module.startswith("_"):
                    continue
                if module in stdlib or module in allowed_third_party:
                    continue
                offenders.append(f"{py.relative_to(PROJECT_ROOT)}: {module}")
        self.assertEqual(offenders, [], f"core/ 出现非标准库依赖: {offenders}")

    def test_ide_ui_package_exists(self) -> None:
        if not (PROJECT_ROOT / "ide_ui").is_dir():
            self.skipTest("ide_ui/ 尚未创建（阶段 3）")

    def test_ide_ui_does_not_import_sqlite3_or_subprocess(self) -> None:
        """UI 层不得直接访问数据库或启动进程（数据与协议一律经 core）。"""
        ui = PROJECT_ROOT / "ide_ui"
        if not ui.is_dir():
            self.skipTest("ide_ui/ 尚未创建（阶段 3）")
        forbidden = {"sqlite3", "subprocess"}
        offenders = []
        for py in sorted(ui.rglob("*.py")):
            hit = _imported_top_level_modules(py) & forbidden
            if hit:
                offenders.append(f"{py.relative_to(PROJECT_ROOT)}: {sorted(hit)}")
        self.assertEqual(offenders, [], f"ide_ui/ 不得直接访问数据/进程: {offenders}")

    def test_mesa_search_delegates_to_core_db(self) -> None:
        """P15：搜索组件的 SQLite 访问必须委托 core.db。"""
        search = PROJECT_ROOT / "mesa_search.py"
        if not search.is_file():
            self.skipTest("mesa_search.py 不存在")
        imported = _imported_top_level_modules(search)
        self.assertNotIn("sqlite3", imported, "P15：UI 层不得直接打开 SQLite 连接")
        self.assertIn("core", imported, "数据访问应委托 core.db")


def _shell_true_lines(path: pathlib.Path) -> list[int]:
    """返回真正以 ``shell=True`` 调用 subprocess 的行号（AST 分析，忽略注释/文档串）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg != "shell":
                continue
            if isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                lines.append(node.lineno)
    return lines


class Stage4Guards(unittest.TestCase):
    """阶段 4 守卫：非阻塞任务、日志化、不再拼接 shell 字符串。"""

    CLI_FILES = ("install.py", "run_mesa.py", "main.py")

    def test_no_shell_true_in_entrypoints(self) -> None:
        offenders = []
        for name in self.CLI_FILES:
            path = PROJECT_ROOT / name
            if not path.is_file():
                continue
            for line in _shell_true_lines(path):
                offenders.append(f"{name}:{line}")
        self.assertEqual(offenders, [], f"这些入口仍在使用 shell=True: {offenders}")

    def test_wsl_launcher_is_the_only_sanctioned_shell_true(self) -> None:
        """唯一获批例外：WSL 分支必须借 cmd.exe 的 start 内建弹新窗口。

        见《审计与迁移评估报告》"需人工确认"第 10 项；此处钉住出现次数，
        防止例外扩散到其他模块。
        """
        terminal = PROJECT_ROOT / "core" / "mesa" / "terminal.py"
        if not terminal.is_file():
            self.skipTest("core/mesa/terminal.py 不存在")
        self.assertEqual(len(_shell_true_lines(terminal)), 1)

    def test_mesa_video_maker_delegates_to_core_video(self) -> None:
        """P9：视频合成必须走 core.video 的非阻塞状态机，不得自己起进程。"""
        path = PROJECT_ROOT / "mesa_video_maker.py"
        if not path.is_file():
            self.skipTest("mesa_video_maker.py 不存在")
        imported = _imported_top_level_modules(path)
        self.assertNotIn("subprocess", imported, "视频层不得直接管理子进程")
        self.assertIn("core", imported, "应委托 core.video")

    def test_core_and_ui_use_logging_not_print(self) -> None:
        """P22/日志化：core 与 ide_ui 内不得再用 print 输出诊断信息。"""
        offenders = []
        for folder in ("core", "ide_ui"):
            base = PROJECT_ROOT / folder
            if not base.is_dir():
                continue
            for py in sorted(base.rglob("*.py")):
                if "print(" in py.read_text(encoding="utf-8"):
                    offenders.append(str(py.relative_to(PROJECT_ROOT)))
        self.assertEqual(offenders, [], f"这些文件仍在用 print: {offenders}")

    def test_long_running_work_goes_through_jobs(self) -> None:
        """视频与 clean 必须经 core.jobs（受管任务），而不是裸 Popen。"""
        video = (PROJECT_ROOT / "core" / "video.py").read_text(encoding="utf-8")
        self.assertIn("from core.jobs import", video)
        self.assertNotIn("subprocess", _imported_top_level_modules(PROJECT_ROOT / "core" / "video.py"))


if __name__ == "__main__":
    unittest.main()

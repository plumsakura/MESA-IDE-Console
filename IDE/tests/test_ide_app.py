"""MESA_IDE 主窗口冒烟/集成测试（真实 Tk，无显示器时自动跳过）。

这是阶段 3 拆分的验收：原 386 行 ``IDE.py`` 拆为 ``ide_ui/*`` 后，
主窗口行为（打开核心 inlist、文件树、诊断面板、编译运行编排）必须不变。
"""

from __future__ import annotations

import pathlib
import tempfile
import tkinter as tk
import unittest
from unittest import mock

from core.mesa.frames import FrameSet
from core.project import CORE_INLIST_FILES, ensure_png_dir
from ide_ui.app import MESA_IDE
from ide_ui.diagnostics import SUCCESS_MESSAGE
from tests.test_ui_components import require_tk
from tests.helpers import SafeDialogTestCase


class FakeVideoTask:
    """可控的假 ``MesaVideoTask``（不启动任何进程）。"""

    instances: list["FakeVideoTask"] = []

    def __init__(self, project_path, prefix, *, fps=10, **kwargs) -> None:
        self.project_path = project_path
        self.prefix = prefix
        self.fps = fps
        self.start_calls = 0
        self.start_result = True
        self.cancelled = False
        self.state = "running"
        self.message = ""
        self.finished = False
        self.succeeded = False
        self.poll_states: list[str] = []
        self.warning = None
        self.frames = FrameSet(
            f"{project_path}/png", prefix, files=(f"{prefix}_000001.png",)
        )
        FakeVideoTask.instances.append(self)

    def start(self, env=None) -> bool:
        self.start_calls += 1
        if not self.start_result:
            self.state = "failed"
            self.message = "错误：未找到 ffmpeg，请确保安装了 ffmpeg。"
            self.finished = True
        return self.start_result

    def poll(self) -> str:
        if self.poll_states:
            self.state = self.poll_states.pop(0)
        self.finished = self.state in ("succeeded", "failed", "cancelled")
        self.succeeded = self.state == "succeeded"
        return self.state

    def cancel(self) -> bool:
        self.cancelled = True
        self.state = "cancelled"
        self.finished = True
        return True


class RestartSnapshotValidation(SafeDialogTestCase):
    """按手册校验重启快照名（``photos/`` 里的 ``xNNN``）。

    改造前只弹一个空输入框，名字拼错要到 MESA 报错才发现；
    现在提示里列出可用快照，且拒绝不存在的名字。
    """

    @classmethod
    def setUpClass(cls) -> None:
        require_tk(cls)

    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = pathlib.Path(self._tmp.name) / "proj"
        (self.base / "photos").mkdir(parents=True)
        for name in ("x005", "x010"):
            (self.base / "photos" / name).write_bytes(b"x")
        (self.base / "inlist").write_text("&controls\n/\n", encoding="utf-8")

    def test_prompt_lists_available_snapshots(self) -> None:
        import mesa_restart

        with mock.patch.object(mesa_restart.simpledialog, "askstring", return_value="") as ask, \
                mock.patch.object(mesa_restart, "open_terminal", return_value=True):
            mesa_restart.run_restart(str(self.base))

        prompt = ask.call_args[0][1]
        self.assertIn("x005", prompt)
        self.assertIn("x010", prompt)

    def test_unknown_snapshot_is_rejected_with_warning(self) -> None:
        import mesa_restart

        with mock.patch.object(mesa_restart.simpledialog, "askstring", return_value="x999"), \
                mock.patch.object(mesa_restart, "open_terminal", return_value=True) as launch:
            mesa_restart.run_restart(str(self.base))

        launch.assert_not_called()
        self.assertIn("showwarning", [kind for kind, _a, _k in self.dialog_calls])

    def test_known_snapshot_launches_restart(self) -> None:
        import mesa_restart

        with mock.patch.object(mesa_restart.simpledialog, "askstring", return_value="x010"), \
                mock.patch.object(mesa_restart, "open_terminal", return_value=True) as launch:
            mesa_restart.run_restart(str(self.base))

        launch.assert_called_once()
        command = launch.call_args[0][0]
        self.assertIn("./re", command)
        self.assertIn("x010", command)


class MESA_IDESmoke(SafeDialogTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        require_tk(cls)

    def setUp(self) -> None:
        super().setUp()
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = pathlib.Path(self._tmp.name)

        for name in CORE_INLIST_FILES:
            (self.base / name).write_text(
                "&controls\n   initial_mass = 1.0d0\n/\n", encoding="utf-8"
            )
        (self.base / "src").mkdir()
        (self.base / "src" / "extra.txt").write_text("x\n", encoding="utf-8")
        (self.base / ".hidden").write_text("x\n", encoding="utf-8")

        self.app = MESA_IDE(str(self.base))
        self.addCleanup(self._destroy_app)

    def _destroy_app(self) -> None:
        try:
            self.app.root.destroy()
        except tk.TclError:  # pragma: no cover - 已在测试中销毁
            pass

    # ---------------- 启动行为 ----------------

    def test_opens_all_core_inlist_files_as_tabs(self) -> None:
        self.assertEqual(len(self.app.tabs), 3)
        self.assertEqual(
            {doc.basename for doc in self.app.tabs.documents()},
            set(CORE_INLIST_FILES),
        )

    def test_opens_only_existing_core_files(self) -> None:
        # 新项目只有 inlist
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / "inlist").write_text("&controls\n/\n", encoding="utf-8")
            app = MESA_IDE(tmp)
            try:
                self.assertEqual(len(app.tabs), 1)
                self.assertEqual(app.tabs.documents()[0].basename, "inlist")
            finally:
                app.root.destroy()

    def test_file_tree_lists_project_contents(self) -> None:
        # inlist×3 + src + src/extra.txt = 5 个节点（.hidden 跳过）
        self.assertEqual(self.app.project_tree.node_count(), 5)

    def test_diagnostics_panel_is_hidden_initially(self) -> None:
        self.assertFalse(self.app.diagnostics_visible())

    def test_show_and_hide_diagnostics_actually_toggles_panel(self) -> None:
        """回归守卫：基线用控件对象比较 ``panes()``，导致"关闭 [X]"失效。"""
        self.app.show_diagnostics()
        self.assertTrue(self.app.diagnostics_visible())
        self.app.show_diagnostics()  # 幂等：不得重复 add
        self.assertTrue(self.app.diagnostics_visible())

        self.app.hide_diagnostics()
        self.assertFalse(self.app.diagnostics_visible())

    def test_lint_targets_are_only_core_inlist_files(self) -> None:
        extra = self.base / "notes.txt"
        extra.write_text("x\n", encoding="utf-8")
        self.app.tabs.open_file(str(extra))
        self.assertEqual(
            {doc.basename for doc in self.app.lint_targets()}, set(CORE_INLIST_FILES)
        )

    # ---------------- 诊断 ----------------

    def test_lint_reports_unknown_parameter_and_shows_panel(self) -> None:
        document = self.app.tabs.document_for_path(str(self.base / "inlist"))
        document.widget.delete("1.0", tk.END)
        # 行为变更（阶段 5）：未知参数改为拼写纠错式，用"库里相近的名字"触发
        document.widget.insert(tk.END, "&controls\n   initial_mas = 1.0d0\n/\n")

        total = self.app.run_lint_logic()

        self.assertGreaterEqual(total, 1)
        entries = self.app.diagnostics.entries()
        self.assertTrue(any("initial_mas" in entry for entry in entries), entries)
        self.assertTrue(self.app.diagnostics_visible())

    def test_lint_clean_content_shows_success(self) -> None:
        total = self.app.run_lint_logic()
        self.assertEqual(total, 0)
        self.assertEqual(self.app.diagnostics.entries(), [SUCCESS_MESSAGE])

    def test_jump_to_diagnostic_focuses_line(self) -> None:
        document = self.app.tabs.document_for_path(str(self.base / "inlist"))
        self.assertTrue(self.app.jump_to_diagnostic(document.label, 2))
        self.assertEqual(document.widget.index(tk.INSERT), "2.0")

    # ---------------- 动作编排 ----------------

    def test_compile_and_run_calls_proxy_directly_and_creates_png_dir(self) -> None:
        """P13 修复回归：不再 subprocess.Popen(["python3","-c",...]) 绕道执行。"""
        with mock.patch("ide_ui.app.compile_and_run") as compile_run, \
             mock.patch("ide_ui.app.ensure_png_dir", wraps=ensure_png_dir) as png:
            self.app.action_compile_and_run()

        compile_run.assert_called_once_with(self.app.project_path)
        png.assert_called_once_with(self.app.project_path)
        self.assertTrue((self.base / "png").is_dir())

    def test_clean_action_delegates_and_refreshes(self) -> None:
        with mock.patch("ide_ui.app.run_clean") as run_clean, \
             mock.patch.object(self.app, "refresh_project_tree", wraps=self.app.refresh_project_tree) as refresh:
            self.app.action_clean()
        run_clean.assert_called_once_with(self.app.project_path)
        refresh.assert_called_once()

    def test_restart_action_delegates_and_refreshes(self) -> None:
        with mock.patch("ide_ui.app.run_restart") as run_restart, \
             mock.patch.object(self.app, "refresh_project_tree", wraps=self.app.refresh_project_tree) as refresh:
            self.app.action_restart()
        run_restart.assert_called_once_with(self.app.project_path)
        refresh.assert_called_once()

    # ---------------- 视频合成（阶段 4：非阻塞状态机） ----------------

    def _patch_video_task(self):
        FakeVideoTask.instances = []
        return mock.patch("ide_ui.app.MesaVideoTask", FakeVideoTask)

    def test_make_video_starts_task_without_blocking(self) -> None:
        with self._patch_video_task(), \
             mock.patch("ide_ui.app.simpledialog.askstring", return_value="hr"):
            started = self.app.action_make_video()

        self.assertTrue(started)
        task = FakeVideoTask.instances[0]
        self.assertEqual(task.start_calls, 1)
        self.assertEqual(task.project_path, self.app.project_path)
        self.assertEqual(task.prefix, "hr")
        self.assertEqual(task.fps, self.app.settings.video_fps)
        self.assertFalse(task.finished, "action_make_video 不得同步等待任务完成")
        self.assertTrue(
            any("正在生成视频" in entry for entry in self.app.diagnostics.entries())
        )

    def test_make_video_with_empty_prefix_does_nothing(self) -> None:
        with self._patch_video_task(), \
             mock.patch("ide_ui.app.simpledialog.askstring", return_value=None):
            started = self.app.action_make_video()
        self.assertFalse(started)
        self.assertEqual(FakeVideoTask.instances, [])

    def test_make_video_start_failure_is_reported(self) -> None:
        class FailingStartTask(FakeVideoTask):
            def start(self, env=None) -> bool:
                self.start_calls += 1
                self.state = "failed"
                self.message = "错误：未找到 ffmpeg，请确保安装了 ffmpeg。"
                self.finished = True
                return False

        FakeVideoTask.instances = []
        with mock.patch("ide_ui.app.MesaVideoTask", FailingStartTask), \
             mock.patch("ide_ui.app.simpledialog.askstring", return_value="hr"):
            started = self.app.action_make_video()

        self.assertFalse(started)
        entries = self.app.diagnostics.entries()
        self.assertTrue(any("❌ 错误：未找到 ffmpeg" in entry for entry in entries), entries)
        self.assertIsNone(self.app._video_task)

    def test_poll_video_task_reports_success_and_refreshes_tree(self) -> None:
        with self._patch_video_task(), \
             mock.patch("ide_ui.app.simpledialog.askstring", return_value="hr"), \
             mock.patch.object(self.app, "refresh_project_tree",
                               wraps=self.app.refresh_project_tree) as refresh:
            self.app.action_make_video()
            task = FakeVideoTask.instances[0]
            task.poll_states = ["succeeded"]
            task.message = "成功生成视频: evolution_movie.mp4"

            state = self.app.poll_video_task()

        self.assertEqual(state, "succeeded")
        self.assertTrue(
            any("✅ 成功生成视频" in entry for entry in self.app.diagnostics.entries())
        )
        refresh.assert_called_once()
        self.assertIsNone(self.app._video_task)

    def test_poll_video_task_keeps_polling_while_running(self) -> None:
        with self._patch_video_task(), \
             mock.patch("ide_ui.app.simpledialog.askstring", return_value="hr"):
            self.app.action_make_video()

        task = FakeVideoTask.instances[0]
        task.poll_states = ["running"]

        self.assertEqual(self.app.poll_video_task(), "running")
        self.assertIs(self.app._video_task, task, "未完成时任务必须保留以便继续轮询")
        self.assertIsNotNone(self.app._video_poll_id)

    def test_poll_video_task_reports_failure_without_refresh(self) -> None:
        with self._patch_video_task(), \
             mock.patch("ide_ui.app.simpledialog.askstring", return_value="hr"), \
             mock.patch.object(self.app, "refresh_project_tree",
                               wraps=self.app.refresh_project_tree) as refresh:
            self.app.action_make_video()
            task = FakeVideoTask.instances[0]
            task.poll_states = ["failed"]
            task.message = "FFmpeg error: boom"

            state = self.app.poll_video_task()

        self.assertEqual(state, "failed")
        self.assertTrue(any("❌ FFmpeg error: boom" in e for e in self.app.diagnostics.entries()))
        refresh.assert_not_called()
        self.assertIsNone(self.app._video_task)

    def test_poll_without_task_is_noop(self) -> None:
        self.assertIsNone(self.app.poll_video_task())

    def test_cancel_video_task(self) -> None:
        with self._patch_video_task(), \
             mock.patch("ide_ui.app.simpledialog.askstring", return_value="hr"):
            self.app.action_make_video()
        task = FakeVideoTask.instances[0]

        self.assertTrue(self.app.cancel_video_task())
        self.assertTrue(task.cancelled)
        self.assertIsNone(self.app._video_task)
        self.assertFalse(self.app.cancel_video_task(), "无任务时应返回 False")

    def test_on_close_cancels_running_video_and_destroys_window(self) -> None:
        with self._patch_video_task(), \
             mock.patch("ide_ui.app.simpledialog.askstring", return_value="hr"):
            self.app.action_make_video()
        task = FakeVideoTask.instances[0]

        self.app.on_close()

        self.assertTrue(task.cancelled, "关闭窗口必须取消未完成的 ffmpeg，避免孤儿进程")
        self.assertEqual(self.app.root.winfo_exists(), 0, "窗口应已销毁")

    # ---------------- 视频合成（阶段 6：任务生命周期 + 输入反馈） ----------------

    def test_second_start_cancels_previous_task(self) -> None:
        """重复点「生成视频」必须收掉上一个 ffmpeg，否则它变成孤儿进程。"""
        with self._patch_video_task(), \
             mock.patch("ide_ui.app.simpledialog.askstring", return_value="hr"):
            self.assertTrue(self.app.action_make_video())
            first = FakeVideoTask.instances[0]
            self.assertTrue(self.app.action_make_video())

        second = FakeVideoTask.instances[1]
        self.assertTrue(first.cancelled, "上一个任务必须被取消")
        self.assertIs(self.app._video_task, second, "窗口里只保留最新任务")
        self.assertTrue(
            any(
                "已取消上一个未完成的视频任务" in entry
                for entry in self.app.diagnostics.entries()
            ),
            self.app.diagnostics.entries(),
        )

    def test_start_reports_matched_frame_count(self) -> None:
        with self._patch_video_task(), \
             mock.patch("ide_ui.app.simpledialog.askstring", return_value="hr"):
            self.app.action_make_video()

        task = FakeVideoTask.instances[0]
        self.assertTrue(
            any(
                entry.endswith(task.frames.describe())
                for entry in self.app.diagnostics.entries()
            ),
            self.app.diagnostics.entries(),
        )

    def test_start_reports_frame_order_warning(self) -> None:
        class WarnedTask(FakeVideoTask):
            def start(self, env=None) -> bool:
                self.warning = "注意：帧序可疑"
                return super().start(env)

        FakeVideoTask.instances = []
        with mock.patch("ide_ui.app.MesaVideoTask", WarnedTask), \
             mock.patch("ide_ui.app.simpledialog.askstring", return_value="hr"):
            self.app.action_make_video()

        self.assertTrue(
            any("⚠️ 注意：帧序可疑" in entry for entry in self.app.diagnostics.entries()),
            self.app.diagnostics.entries(),
        )

    def test_cancel_reports_task_that_already_finished(self) -> None:
        """取消返回 False 且任务其实已完成时，成片消息不能被静默丢掉。"""

        class FinishedTask(FakeVideoTask):
            def cancel(self) -> bool:
                self.state, self.finished, self.succeeded = "succeeded", True, True
                self.message = "成功生成视频: evolution_movie.mp4"
                return False

        FakeVideoTask.instances = []
        with mock.patch("ide_ui.app.MesaVideoTask", FinishedTask), \
             mock.patch("ide_ui.app.simpledialog.askstring", return_value="hr"):
            self.app.action_make_video()
            self.assertFalse(self.app.cancel_video_task())

        self.assertTrue(
            any("✅ 成功生成视频" in entry for entry in self.app.diagnostics.entries()),
            self.app.diagnostics.entries(),
        )


if __name__ == "__main__":
    unittest.main()

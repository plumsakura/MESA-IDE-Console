"""协议快照测试：锁定与 MESA 引擎交互的命令构造与终端启动行为。

本文件是**协议冻结的守卫**：除下文声明的变更外，任何期望值变化都说明协议
被意外破坏。

阶段 1 基线（原实现）：
  - 命令以手工拼接的 shell 字符串交给终端：``cd '<路径>' && ./mk && ./rn``；
  - 终端参数为 ``bash -c``；动态内容直接插值（注入风险 P5）。

阶段 2 声明变更（已在提交信息中声明）：
  - **P5 修复**：动态内容统一经 ``shlex.quote`` 转义；无需转义的路径不再带单引号
    （``cd '/tmp/p'`` → ``cd /tmp/p``）；
  - 终端统一使用 ``bash -ic``（与 restart 一致，可加载 ``.bashrc``）；
  - WSL 分支不再 ``communicate()`` 阻塞 UI 线程（P9）。
  - **MESA 环境前置（本阶段批准）**：动作命令前插入
    ``{ [ -f <IDE>/mesa_env.sh ] && . <IDE>/mesa_env.sh; }`` —— WSL 弹出的
    新终端是非交互 shell，读不到 ``.bashrc`` 的环境块，必须显式加载。

所有用例都继承 ``SafeDialogTestCase``：真实 Tk 弹窗会永久阻塞测试，
该基线类从机制上杜绝挂起。
"""

from __future__ import annotations

import os
import pathlib
import shlex
import shutil
import tempfile
import unittest
from unittest import mock

import clean
import compile_and_run
import mesa_restart
from core.mesa.commands import env_preamble
from tests.helpers import SafeDialogTestCase

#: 命令前置片段（与 build_shell_command 一致；协议快照按此构造期望值）
PRE = env_preamble()


def _which_only(target: str):
    """返回一个只认得 target 的 shutil.which 替身。"""
    return lambda name: f"/usr/bin/{name}" if name == target else None


class _RealProjectTestCase(SafeDialogTestCase):
    """提供一个**真实存在**的临时项目目录。

    必须真实存在：命令构造函数在路径不存在时会走 messagebox 分支并直接返回，
    用假路径会得到"没有启动任何进程"的错误断言结果。
    """

    def setUp(self) -> None:
        super().setUp()
        self.proj = tempfile.mkdtemp(prefix="mesa-proj-")
        self.addCleanup(shutil.rmtree, self.proj, ignore_errors=True)

    def make_temp_dir(self, prefix: str) -> str:
        path = tempfile.mkdtemp(prefix=prefix)
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path


class CompileAndRunSnapshot(_RealProjectTestCase):
    def test_missing_project_shows_error_and_does_not_spawn(self) -> None:
        with mock.patch.object(compile_and_run.messagebox, "showerror") as err, \
             mock.patch.object(compile_and_run.subprocess, "Popen") as popen:
            compile_and_run.compile_and_run("/nonexistent/mesa/proj")

        err.assert_called_once()
        self.assertEqual(err.call_args[0][0], "错误")
        self.assertIn("/nonexistent/mesa/proj", err.call_args[0][1])
        popen.assert_not_called()

    def _run_and_capture(self, mode: str = "both", project: str | None = None):
        calls: list[tuple[tuple, dict]] = []
        target = project or self.proj

        def fake_popen(*args, **kwargs):
            calls.append((args, kwargs))
            return mock.MagicMock()

        with mock.patch.object(compile_and_run, "is_wsl", return_value=False), \
             mock.patch.object(compile_and_run.shutil, "which", _which_only("gnome-terminal")), \
             mock.patch.object(compile_and_run.subprocess, "Popen", side_effect=fake_popen):
            compile_and_run.compile_and_run(target, mode=mode)
        return calls

    def test_default_mode_is_mk_then_rn(self) -> None:
        calls = self._run_and_capture()
        self.assertEqual(len(calls), 1)
        argv, kwargs = calls[0]
        self.assertEqual(
            argv[0],
            ["gnome-terminal", "--", "bash", "-ic",
             f"cd {self.proj} && {PRE} && ./mk && ./rn; exec bash"],
        )
        self.assertEqual(kwargs["stdout"], compile_and_run.subprocess.DEVNULL)
        self.assertEqual(kwargs["stderr"], compile_and_run.subprocess.DEVNULL)
        self.assertTrue(kwargs["start_new_session"])

    def test_mode_mk_only(self) -> None:
        calls = self._run_and_capture(mode="mk")
        self.assertEqual(len(calls), 1)
        argv, _kwargs = calls[0]
        self.assertEqual(argv[0][4], f"cd {self.proj} && {PRE} && ./mk; exec bash")

    def test_mode_rn_only(self) -> None:
        calls = self._run_and_capture(mode="rn")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0][0][4], f"cd {self.proj} && {PRE} && ./rn; exec bash")

    def test_unknown_mode_falls_back_to_both(self) -> None:
        calls = self._run_and_capture(mode="something-else")
        self.assertEqual(calls[0][0][0][4], f"cd {self.proj} && {PRE} && ./mk && ./rn; exec bash")

    def test_path_with_space_is_quoted(self) -> None:
        spaced = self.make_temp_dir("mesa proj ")
        calls = self._run_and_capture(project=spaced)
        argv, _kwargs = calls[0]
        self.assertEqual(argv[0][4], f"cd '{spaced}' && {PRE} && ./mk && ./rn; exec bash")

    def test_hostile_path_is_escaped_and_stays_one_token(self) -> None:
        """P5 回归守卫：含引号/分号的路径不得拆成多个 shell token。"""
        hostile = self.make_temp_dir("mesa'; touch PWNED; '")
        calls = self._run_and_capture(project=hostile)
        command = calls[0][0][0][4]
        tokens = shlex.split(command)
        self.assertEqual(tokens[:3], ["cd", hostile, "&&"])
        self.assertIn("./mk", tokens)
        self.assertTrue(any(token.startswith("./rn") for token in tokens))
        # 关键：恶意路径必须整体是一个 token，不得拆出额外的 shell 词
        self.assertEqual(tokens.count(hostile), 1)

    def test_terminal_fallback_order_first_available_wins(self) -> None:
        """konsole 存在而 gnome-terminal 不存在时，选中 konsole。"""
        calls = []
        with mock.patch.object(compile_and_run, "is_wsl", return_value=False), \
             mock.patch.object(compile_and_run.shutil, "which", _which_only("konsole")), \
             mock.patch.object(compile_and_run.subprocess, "Popen",
                               side_effect=lambda *a, **k: calls.append((a, k))):
            compile_and_run.compile_and_run(self.proj)
        self.assertEqual(calls[0][0][0][:2], ["konsole", "-e"])

    def test_no_terminal_available_shows_error(self) -> None:
        with mock.patch.object(compile_and_run, "is_wsl", return_value=False), \
             mock.patch.object(compile_and_run.shutil, "which", return_value=None), \
             mock.patch.object(compile_and_run.subprocess, "Popen") as popen, \
             mock.patch.object(compile_and_run.messagebox, "showerror") as err:
            compile_and_run.compile_and_run(self.proj)
        popen.assert_not_called()
        self.assertEqual(err.call_args[0][0], "无法启动终端")

    def test_wsl_branch_uses_cmd_exe_start(self) -> None:
        with mock.patch.object(compile_and_run, "is_wsl", return_value=True), \
             mock.patch.object(compile_and_run.subprocess, "Popen") as popen:
            compile_and_run.compile_and_run(self.proj, mode="rn")

        (shell_cmd,), kwargs = popen.call_args
        self.assertIn("cmd.exe /c start", shell_cmd)
        self.assertIn("wsl.exe", shell_cmd)
        self.assertIn("bash -ic", shell_cmd)
        self.assertIn("./rn", shell_cmd)
        self.assertTrue(kwargs["shell"])
        # 阶段 2 声明变更：不再 communicate() 阻塞 UI 线程
        popen.return_value.communicate.assert_not_called()

    def test_is_wsl_true_for_microsoft_kernel(self) -> None:
        with mock.patch("builtins.open",
                        mock.mock_open(read_data="Linux version 6.6.87.2-microsoft-standard-WSL2")):
            self.assertTrue(compile_and_run.is_wsl())

    def test_is_wsl_false_for_plain_linux(self) -> None:
        with mock.patch("builtins.open", mock.mock_open(read_data="Linux version 6.6.0-generic")):
            self.assertFalse(compile_and_run.is_wsl())

    def test_is_wsl_swallows_errors(self) -> None:
        """基线行为：读取 /proc/version 失败时静默返回 False（裸 except）。"""
        with mock.patch("builtins.open", side_effect=OSError("boom")):
            self.assertFalse(compile_and_run.is_wsl())


class RestartSnapshot(_RealProjectTestCase):
    def test_open_terminal_linux_builds_expected_argv(self) -> None:
        calls = []
        with mock.patch.object(mesa_restart, "is_wsl", return_value=False), \
             mock.patch.object(mesa_restart.shutil, "which", _which_only("gnome-terminal")), \
             mock.patch.object(mesa_restart.subprocess, "Popen",
                               side_effect=lambda *a, **k: calls.append((a, k))):
            ok = mesa_restart.open_terminal("cd '/tmp/proj' && ./re")

        self.assertTrue(ok)
        argv, kwargs = calls[0]
        self.assertEqual(
            argv[0],
            ["gnome-terminal", "--", "bash", "-ic",
             "cd '/tmp/proj' && ./re; exec bash"],
        )
        self.assertEqual(kwargs["env"], os.environ.copy())
        self.assertTrue(kwargs["start_new_session"])

    def test_open_terminal_returns_false_when_none_available(self) -> None:
        with mock.patch.object(mesa_restart, "is_wsl", return_value=False), \
             mock.patch.object(mesa_restart.shutil, "which", return_value=None):
            self.assertFalse(mesa_restart.open_terminal("cd '/tmp/proj' && ./re"))

    def test_restart_with_snapshot_name(self) -> None:
        with mock.patch.object(mesa_restart.simpledialog, "askstring", return_value="snap1"), \
             mock.patch.object(mesa_restart, "open_terminal", return_value=True) as terminal:
            mesa_restart.run_restart(self.proj)
        terminal.assert_called_once_with(f"cd {self.proj} && {PRE} && ./re snap1")

    def test_restart_with_snapshot_name_containing_space_is_quoted(self) -> None:
        with mock.patch.object(mesa_restart.simpledialog, "askstring", return_value="my snap"), \
             mock.patch.object(mesa_restart, "open_terminal", return_value=True) as terminal:
            mesa_restart.run_restart(self.proj)
        terminal.assert_called_once_with(f"cd {self.proj} && {PRE} && ./re 'my snap'")

    def test_restart_with_empty_snapshot_uses_latest(self) -> None:
        with mock.patch.object(mesa_restart.simpledialog, "askstring", return_value="   "), \
             mock.patch.object(mesa_restart, "open_terminal", return_value=True) as terminal:
            mesa_restart.run_restart(self.proj)
        terminal.assert_called_once_with(f"cd {self.proj} && {PRE} && ./re")

    def test_restart_missing_project_shows_error(self) -> None:
        with mock.patch.object(mesa_restart.simpledialog, "askstring", return_value=""), \
             mock.patch.object(mesa_restart, "open_terminal") as terminal, \
             mock.patch.object(mesa_restart.messagebox, "showerror") as err:
            mesa_restart.run_restart("/nonexistent/mesa/proj")
        terminal.assert_not_called()
        self.assertEqual(err.call_args[0][0], "错误")

    def test_restart_reports_failure_when_terminal_is_missing(self) -> None:
        with mock.patch.object(mesa_restart.simpledialog, "askstring", return_value=""), \
             mock.patch.object(mesa_restart, "open_terminal", return_value=False), \
             mock.patch.object(mesa_restart.messagebox, "showerror") as err:
            mesa_restart.run_restart(self.proj)
        self.assertEqual(err.call_args[0][0], "运行失败")


class CleanSnapshot(_RealProjectTestCase):
    def _make_script(self, directory: str) -> pathlib.Path:
        script = pathlib.Path(directory) / "clean"
        script.write_text("#!/bin/bash\ntrue\n", encoding="utf-8")
        script.chmod(0o644)
        return script

    def test_missing_project_shows_error(self) -> None:
        with mock.patch.object(clean.messagebox, "showerror") as err, \
             mock.patch.object(clean.subprocess, "Popen") as popen:
            clean.run_clean("/nonexistent/mesa/proj")
        popen.assert_not_called()
        self.assertEqual(err.call_args[0][0], "错误")

    def test_missing_clean_script_shows_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(clean.messagebox, "showerror") as err, \
             mock.patch.object(clean.subprocess, "Popen") as popen:
            clean.run_clean(tmp)
        popen.assert_not_called()
        self.assertIn("未找到清理脚本", err.call_args[0][1])

    def test_runs_clean_detached_and_makes_script_executable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = self._make_script(tmp)

            with mock.patch.object(clean.subprocess, "Popen") as popen:
                clean.run_clean(tmp)

            (cmd,), kwargs = popen.call_args
            self.assertEqual(cmd, ["bash", "-c", f"cd {tmp} && {PRE} && ./clean"])
            self.assertEqual(kwargs["stdout"], clean.subprocess.DEVNULL)
            self.assertEqual(kwargs["stderr"], clean.subprocess.DEVNULL)
            self.assertTrue(kwargs["start_new_session"])
            self.assertIn("env", kwargs)
            self.assertEqual(oct(script.stat().st_mode & 0o777), oct(0o755))

    def test_path_with_space_is_quoted(self) -> None:
        spaced = self.make_temp_dir("mesa clean ")
        self._make_script(spaced)
        with mock.patch.object(clean.subprocess, "Popen") as popen:
            clean.run_clean(spaced)
        (cmd,), _kwargs = popen.call_args
        self.assertEqual(cmd, ["bash", "-c", f"cd '{spaced}' && {PRE} && ./clean"])


if __name__ == "__main__":
    unittest.main()

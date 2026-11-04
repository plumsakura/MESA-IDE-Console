"""core.mesa.terminal 单元测试：终端探测顺序、argv 构造、WSL 分支。

终端表与探测顺序属**冻结协议**（与原实现一致），本文件锁定它们。
"""

from __future__ import annotations

import os
import subprocess
import unittest
from unittest import mock

from core.mesa import terminal as core_terminal
from core.mesa.terminal import (
    LINUX_TERMINALS,
    NO_TERMINAL_HINT,
    TerminalSpec,
    build_linux_argv,
    build_wsl_command,
    find_terminal,
    is_wsl,
    launch,
    launch_linux,
    launch_wsl,
)

EXPECTED_ORDER = (
    "gnome-terminal",
    "konsole",
    "xfce4-terminal",
    "terminator",
    "mate-terminal",
    "lxterminal",
    "xterm",
)


class TerminalTable(unittest.TestCase):
    def test_probe_order_is_frozen(self) -> None:
        self.assertEqual(tuple(spec.executable for spec in LINUX_TERMINALS), EXPECTED_ORDER)

    def test_every_terminal_uses_interactive_bash(self) -> None:
        """阶段 2 声明变更：统一为 bash -ic（原 compile_and_run 用 bash -c）。"""
        for spec in LINUX_TERMINALS:
            self.assertEqual(spec.args[-2:], ("bash", "-ic"), spec.executable)

    def test_find_terminal_returns_first_available(self) -> None:
        spec = find_terminal(lambda name: f"/usr/bin/{name}" if name == "xterm" else None)
        self.assertIsNotNone(spec)
        self.assertEqual(spec.executable, "xterm")

    def test_find_terminal_prefers_earlier_entry(self) -> None:
        spec = find_terminal(lambda name: "/usr/bin/" + name)
        self.assertEqual(spec.executable, "gnome-terminal")

    def test_find_terminal_none_when_nothing_available(self) -> None:
        self.assertIsNone(find_terminal(lambda name: None))

    def test_build_linux_argv_appends_shell_command_last(self) -> None:
        spec = TerminalSpec("konsole", ("-e", "bash", "-ic"))
        self.assertEqual(
            build_linux_argv(spec, "cd /tmp/p && ./rn"),
            ["konsole", "-e", "bash", "-ic", "cd /tmp/p && ./rn"],
        )


class WslDetectionAndCommand(unittest.TestCase):
    def test_build_wsl_command_is_frozen_format(self) -> None:
        """没有发行版信息时保持原冻结格式（向后兼容）。"""
        self.assertEqual(
            build_wsl_command("cd /tmp/p && ./rn", distro=""),
            'cmd.exe /c start "MESA Run" wsl.exe -- bash -ic "cd /tmp/p && ./rn"',
        )

    def test_build_wsl_command_targets_current_distro(self) -> None:
        """多发行版场景：必须用 wsl.exe -d <发行版>，否则新终端进默认发行版，
        项目目录不存在（真实故障: cd: .../MESA_program/123: No such file）。"""
        self.assertEqual(
            build_wsl_command("cd /tmp/p && ./rn", distro="Ubuntu-Third"),
            'cmd.exe /c start "MESA Run" wsl.exe -d Ubuntu-Third -- bash -ic "cd /tmp/p && ./rn"',
        )

    def test_distro_name_with_space_is_quoted(self) -> None:
        command = build_wsl_command("cd /tmp", distro="My Arch")
        self.assertIn("wsl.exe -d 'My Arch' -- bash -ic", command)

    def test_distro_defaults_to_env_when_not_given(self) -> None:
        with mock.patch.dict(os.environ, {"WSL_DISTRO_NAME": "Ubuntu-Third"}, clear=False):
            self.assertEqual(
                build_wsl_command("cd /tmp/p"),
                'cmd.exe /c start "MESA Run" wsl.exe -d Ubuntu-Third -- bash -ic "cd /tmp/p"',
            )

    def test_is_wsl_true_for_microsoft_kernel(self) -> None:
        with mock.patch("builtins.open",
                        mock.mock_open(read_data="Linux version 6.6-microsoft-standard-WSL2")):
            self.assertTrue(is_wsl())

    def test_is_wsl_false_for_plain_linux(self) -> None:
        with mock.patch("builtins.open", mock.mock_open(read_data="Linux version 6.6.0-generic")):
            self.assertFalse(is_wsl())

    def test_is_wsl_swallows_io_errors(self) -> None:
        with mock.patch("builtins.open", side_effect=OSError("boom")):
            self.assertFalse(is_wsl())


class LaunchLinux(unittest.TestCase):
    def test_launch_uses_detected_terminal_and_frozen_kwargs(self) -> None:
        calls = []

        result = launch_linux(
            "CMD",
            which=lambda name: "/usr/bin/konsole" if name == "konsole" else None,
            popen=lambda *args, **kwargs: calls.append((args, kwargs)),
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.executable, "konsole")
        argv, kwargs = calls[0]
        self.assertEqual(argv[0], ["konsole", "-e", "bash", "-ic", "CMD"])
        self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(kwargs["env"], os.environ.copy())

    def test_launch_reports_missing_terminal(self) -> None:
        result = launch_linux("CMD", which=lambda name: None, popen=lambda *a, **k: None)
        self.assertFalse(result.ok)
        self.assertIsNone(result.executable)
        self.assertEqual(result.detail, NO_TERMINAL_HINT)

    def test_launch_passes_custom_env(self) -> None:
        calls = []
        launch_linux(
            "CMD",
            env={"MESA_DIR": "/opt/mesa"},
            which=lambda name: "/usr/bin/xterm" if name == "xterm" else None,
            popen=lambda *args, **kwargs: calls.append(kwargs),
        )
        self.assertEqual(calls[0]["env"], {"MESA_DIR": "/opt/mesa"})


class LaunchWsl(unittest.TestCase):
    def test_launch_wsl_uses_cmd_exe_with_shell_true(self) -> None:
        calls = []
        result = launch_wsl("CMD", popen=lambda *args, **kwargs: calls.append((args, kwargs)))

        self.assertTrue(result.ok)
        self.assertTrue(result.via_wsl)
        (command,), kwargs = calls[0]
        self.assertEqual(command, build_wsl_command("CMD"))
        self.assertTrue(kwargs["shell"])
        self.assertEqual(kwargs["env"], os.environ.copy())

    def test_launch_wsl_passes_custom_env(self) -> None:
        calls = []
        launch_wsl("CMD", env={"A": "B"}, popen=lambda *a, **k: calls.append(k))
        self.assertEqual(calls[0]["env"], {"A": "B"})


class LaunchDispatch(unittest.TestCase):
    def test_dispatches_to_linux_terminal_when_not_wsl(self) -> None:
        calls = []
        launch(
            "CMD",
            which=lambda name: "/usr/bin/xterm" if name == "xterm" else None,
            popen=lambda *args, **kwargs: calls.append(args),
            wsl_detector=lambda: False,
        )
        self.assertEqual(calls[0][0][0], "xterm")

    def test_dispatches_to_wsl_when_detected(self) -> None:
        calls = []
        launch(
            "CMD",
            popen=lambda *args, **kwargs: calls.append(args),
            wsl_detector=lambda: True,
        )
        self.assertTrue(str(calls[0][0]).startswith("cmd.exe /c start"))

    def test_no_terminal_yields_not_ok(self) -> None:
        result = launch(
            "CMD",
            which=lambda name: None,
            popen=lambda *a, **k: None,
            wsl_detector=lambda: False,
        )
        self.assertFalse(result.ok)
        self.assertIn("未找到可用的终端模拟器", result.detail)

    def test_no_terminal_detail_mentions_install_hint(self) -> None:
        self.assertIn("sudo apt install xterm", core_terminal.NO_TERMINAL_HINT)


if __name__ == "__main__":
    unittest.main()

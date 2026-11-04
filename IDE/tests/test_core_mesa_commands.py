"""core.mesa.commands 单元测试：命令构造与注入安全（含真实 bash 执行验证）。

这里锁定的是**冻结协议**：动作→脚本映射、``cd`` 到项目目录、
``&&`` 串联、restart 的位置参数、以及 keep-open 后缀。
"""

from __future__ import annotations

import os
import pathlib
import shlex
import subprocess
import tempfile
import unittest

from core.config import project_root
from core.mesa import (
    ACTION_BUILD,
    ACTION_CLEAN,
    ACTION_RESTART,
    ACTION_RUN,
    ACTION_RUN_ALL,
    SCRIPT_SEQUENCES,
    UnknownActionError,
    build_bash_c_command,
    build_shell_command,
    script_sequence,
)
from core.mesa.commands import build_script_body


class ScriptSequenceProtocol(unittest.TestCase):
    def test_frozen_action_to_script_mapping(self) -> None:
        self.assertEqual(script_sequence(ACTION_BUILD), (("./mk",),))
        self.assertEqual(script_sequence(ACTION_RUN), (("./rn",),))
        self.assertEqual(script_sequence(ACTION_RUN_ALL), (("./mk",), ("./rn",)))
        self.assertEqual(script_sequence(ACTION_CLEAN), (("./clean",),))
        self.assertEqual(script_sequence(ACTION_RESTART), (("./re",),))

    def test_mapping_table_is_exactly_these_five_actions(self) -> None:
        self.assertEqual(
            set(SCRIPT_SEQUENCES),
            {ACTION_BUILD, ACTION_RUN, ACTION_RUN_ALL, ACTION_RESTART, ACTION_CLEAN},
        )

    def test_restart_with_snapshot_appends_positional_argument(self) -> None:
        """快照名是 ./re 的**参数**，绝不能被当成另一条命令用 && 串联。"""
        self.assertEqual(script_sequence(ACTION_RESTART, "snap1"), (("./re", "snap1"),))

    def test_restart_without_snapshot_uses_latest(self) -> None:
        self.assertEqual(script_sequence(ACTION_RESTART, None), (("./re",),))
        self.assertEqual(script_sequence(ACTION_RESTART, ""), (("./re",),))

    def test_unknown_action_is_rejected(self) -> None:
        with self.assertRaises(UnknownActionError):
            script_sequence("definitely-not-an-action")

    def test_empty_script_sequence_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_script_body(())

    def test_empty_argv_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_script_body(((),))

    def test_command_strings_are_normalized_to_single_token_argv(self) -> None:
        self.assertEqual(build_script_body(("pwd",)), "pwd")
        self.assertEqual(build_script_body((("./re", "a b"),)), "./re 'a b'")


def _env() -> str:
    """测试机上的 mesa_env.sh 路径（与 build_shell_command 的 env_preamble 一致）。"""
    return str(project_root() / "mesa_env.sh")


def _expect(lead: str, rest: str) -> str:
    """构造"cd <路径> && { [ -f env ] && . env; } && <动作>"的期望字符串。"""
    return f"{lead} && {{ [ -f {_env()} ] && . {_env()}; }} && {rest}"


class ShellCommandConstruction(unittest.TestCase):
    def test_simple_path_is_not_quoted(self) -> None:
        self.assertEqual(build_shell_command("/tmp/p", ACTION_RUN), _expect("cd /tmp/p", "./rn"))

    def test_run_all_joins_with_and(self) -> None:
        self.assertEqual(
            build_shell_command("/tmp/p", ACTION_RUN_ALL), _expect("cd /tmp/p", "./mk && ./rn")
        )

    def test_keep_open_appends_exec_bash(self) -> None:
        self.assertEqual(
            build_shell_command("/tmp/p", ACTION_RUN, keep_open=True),
            _expect("cd /tmp/p", "./rn") + "; exec bash",
        )

    def test_path_with_space_is_single_quoted(self) -> None:
        self.assertEqual(
            build_shell_command("/tmp/my proj", ACTION_BUILD), _expect("cd '/tmp/my proj'", "./mk")
        )

    def test_snapshot_with_space_is_single_quoted(self) -> None:
        self.assertEqual(
            build_shell_command("/tmp/p", ACTION_RESTART, "my snap"),
            _expect("cd /tmp/p", "./re 'my snap'"),
        )

    def test_bash_c_command_shape_for_clean(self) -> None:
        self.assertEqual(
            build_bash_c_command("/tmp/p"),
            ["bash", "-c", _expect("cd /tmp/p", "./clean")],
        )


class InjectionSafety(unittest.TestCase):
    """P5 回归守卫：用户可控内容（项目路径、快照名）不得逃出数据位置。"""

    def test_hostile_path_roundtrips_as_single_token(self) -> None:
        hostile = "/tmp/x'; touch PWNED; '"
        tokens = shlex.split(build_shell_command(hostile, ACTION_RUN))
        self.assertEqual(tokens, ["cd", hostile, "&&", "{", "[", "-f", _env(), "]", "&&", ".", _env() + ";", "}", "&&", "./rn"])

    def test_hostile_path_with_and_operator_is_neutralised(self) -> None:
        hostile = "/tmp/a && rm -rf / && b"
        tokens = shlex.split(build_shell_command(hostile, ACTION_RUN))
        self.assertEqual(tokens, ["cd", hostile, "&&", "{", "[", "-f", _env(), "]", "&&", ".", _env() + ";", "}", "&&", "./rn"])

    def test_hostile_snapshot_is_passed_as_literal_argument(self) -> None:
        tokens = shlex.split(build_shell_command("/tmp/p", ACTION_RESTART, "; touch PWNED2"))
        self.assertEqual(tokens, ["cd", "/tmp/p", "&&", "{", "[", "-f", _env(), "]", "&&", ".", _env() + ";", "}", "&&", "./re", "; touch PWNED2"])

    def test_real_bash_execution_stays_in_directory(self) -> None:
        """真实执行验证：用无害脚本序列（pwd）确认 cwd 正确且无注入副作用。

        脚本序列由测试注入，因此**不会**真的调用 ./mk / ./rn。
        """
        with tempfile.TemporaryDirectory() as base:
            evil_dir = os.path.join(base, "proj; touch PWNED")
            os.makedirs(evil_dir)
            command = build_shell_command(evil_dir, ACTION_RUN, scripts=("pwd",))

            completed = subprocess.run(
                ["bash", "-c", command], capture_output=True, text=True, check=False
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                os.path.realpath(completed.stdout.strip()), os.path.realpath(evil_dir)
            )
            self.assertFalse(os.path.exists(os.path.join(base, "PWNED")))
            self.assertFalse(os.path.exists(os.path.join(os.getcwd(), "PWNED")))

    def test_real_execution_passes_snapshot_as_single_argument(self) -> None:
        """真实执行 ``./re``（测试自建的桩脚本）：恶意快照名只作为参数抵达。"""
        with tempfile.TemporaryDirectory() as base:
            re_script = pathlib.Path(base) / "re"
            re_script.write_text(
                "#!/bin/bash\nprintf 'ARG=%s\\n' \"$1\"\n", encoding="utf-8"
            )
            re_script.chmod(0o755)

            hostile_snapshot = "s n a p; touch PWNED"
            command = build_shell_command(base, ACTION_RESTART, hostile_snapshot)
            completed = subprocess.run(
                ["bash", "-c", command], capture_output=True, text=True, check=False
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), f"ARG={hostile_snapshot}")
            self.assertFalse(os.path.exists(os.path.join(base, "PWNED")))


if __name__ == "__main__":
    unittest.main()

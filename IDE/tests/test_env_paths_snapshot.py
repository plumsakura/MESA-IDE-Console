"""路径解析快照：两份 ``get_mesa_paths`` 已在阶段 2 统一（P8 修复）。

阶段 1 基线记录的两处缺陷已按"声明变更"修复：

1. **P8 键分歧**：``create_new_program`` 返回 5 键、``open_old_program`` 返回 3 键
   → 现在两者都经 ``core.project.project_paths()``，返回同样的 5 键。
2. **P21b 静默回退**：无效 ``MESA_DIR`` 会被静默替换为 ``~/mesa``
   → 现在保留该路径作为"最佳猜测"并在 ``warnings`` 中说明原因。

因此本文件不再断言旧的分歧行为，改为断言统一后的契约。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

import create_new_program
import open_old_program
from core.project import project_paths

FIVE_KEYS = {"mesa_dir", "defaults", "test_suite", "work", "user_programs"}


class UnifiedPathResolution(unittest.TestCase):
    def test_both_modules_return_the_same_five_keys(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MESA_DIR", None)
            new_keys = set(create_new_program.get_mesa_paths())
            old_keys = set(open_old_program.get_mesa_paths())

        self.assertEqual(new_keys, FIVE_KEYS)
        self.assertEqual(old_keys, FIVE_KEYS, "P8 修复后两者必须一致")

    def test_shared_values_when_mesa_dir_unset(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch("core.env._glob_candidates", return_value=[]):
            os.environ.pop("MESA_DIR", None)
            new = create_new_program.get_mesa_paths()
            old = open_old_program.get_mesa_paths()

        home_mesa = os.path.expanduser("~/mesa")
        self.assertEqual(new["mesa_dir"], home_mesa)
        self.assertEqual(new["mesa_dir"], old["mesa_dir"])
        self.assertEqual(new["test_suite"], old["test_suite"])
        self.assertEqual(new["user_programs"], old["user_programs"])
        self.assertEqual(new["defaults"], os.path.join(home_mesa, "star", "defaults"))
        self.assertEqual(new["work"], os.path.join(home_mesa, "star", "work"))
        self.assertEqual(new["user_programs"], os.path.expanduser("~/MESA_program"))

    def test_existing_mesa_dir_env_is_honoured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"MESA_DIR": tmp}), \
                    mock.patch("core.env._glob_candidates", return_value=[]):
                new = create_new_program.get_mesa_paths()
                old = open_old_program.get_mesa_paths()
        self.assertEqual(new["mesa_dir"], tmp)
        self.assertEqual(old["mesa_dir"], tmp)
        self.assertEqual(new["defaults"], os.path.join(tmp, "star", "defaults"))

    def test_bogus_mesa_dir_is_not_silently_replaced(self) -> None:
        """P21b 修复后：保留用户设置并给出警告，而不是偷偷换成 ~/mesa。"""
        with mock.patch.dict(os.environ, {"MESA_DIR": "/definitely/not/here"}), \
                mock.patch("core.env._glob_candidates", return_value=[]):
            new = create_new_program.get_mesa_paths()
        self.assertEqual(new["mesa_dir"], "/definitely/not/here")

    def test_core_exposes_warnings_and_validity(self) -> None:
        detected = project_paths(env={"MESA_DIR": "/definitely/not/here"}, fallbacks=(), glob_patterns=())
        self.assertFalse(detected.is_valid)
        self.assertTrue(any("MESA_DIR" in warning for warning in detected.warnings))

    def test_user_programs_can_be_overridden(self) -> None:
        with mock.patch.dict(os.environ, {"MESA_PROGRAMS_DIR": "/tmp/my-programs"}):
            self.assertEqual(
                create_new_program.get_mesa_paths()["user_programs"], "/tmp/my-programs"
            )
            self.assertEqual(
                open_old_program.get_mesa_paths()["user_programs"], "/tmp/my-programs"
            )


if __name__ == "__main__":
    unittest.main()

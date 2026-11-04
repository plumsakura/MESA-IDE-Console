"""core.env 单元测试：MESA 安装检测（零副作用，全临时目录）。

这是用户要求"如果已安装就检查"的规格：检测结果必须显式区分
"环境变量已设置"、"路径存在"、"确实是可用安装"，且**不得静默回退**。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from core import env as core_env


def make_fake_mesa(root: Path, subdirs: tuple[str, ...] = ("star/defaults", "star/work", "star/test_suite")) -> str:
    for relative in subdirs:
        (root / relative).mkdir(parents=True, exist_ok=True)
    return str(root)


class ValidateMesaDir(unittest.TestCase):
    def test_complete_install_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            make_fake_mesa(Path(tmp))
            is_valid, missing_required, missing_expected = core_env.validate_mesa_dir(tmp)
        self.assertTrue(is_valid)
        self.assertEqual(missing_required, ())
        self.assertEqual(missing_expected, ())

    def test_missing_star_defaults_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "star").mkdir()
            is_valid, missing_required, _ = core_env.validate_mesa_dir(tmp)
        self.assertFalse(is_valid)
        self.assertIn("star/defaults", missing_required)

    def test_missing_optional_dirs_still_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "star" / "defaults").mkdir(parents=True)
            is_valid, missing_required, missing_expected = core_env.validate_mesa_dir(tmp)
        self.assertTrue(is_valid)
        self.assertEqual(missing_required, ())
        self.assertEqual(set(missing_expected), {"star/work", "star/test_suite"})

    def test_nonexistent_dir_is_invalid(self) -> None:
        is_valid, missing_required, _ = core_env.validate_mesa_dir("/definitely/not/here")
        self.assertFalse(is_valid)
        self.assertEqual(missing_required, core_env.REQUIRED_SUBDIRS)


class DetectMesa(unittest.TestCase):
    def test_env_var_pointing_to_valid_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            make_fake_mesa(Path(tmp))
            detected = core_env.detect_mesa(env={"MESA_DIR": tmp}, fallbacks=(), glob_patterns=())
        self.assertTrue(detected.is_valid)
        self.assertEqual(detected.source, core_env.SOURCE_ENV)
        self.assertEqual(detected.mesa_dir, tmp)
        self.assertEqual(detected.warnings, ())
        self.assertIn("可用", detected.summary())

    def test_bogus_env_var_is_reported_not_silent(self) -> None:
        """基线缺陷修复点：原实现遇到无效 MESA_DIR 会静默回退到 ~/mesa。"""
        detected = core_env.detect_mesa(env={"MESA_DIR": "/definitely/not/here"}, fallbacks=(), glob_patterns=())
        self.assertFalse(detected.is_valid)
        self.assertTrue(any("MESA_DIR" in w for w in detected.warnings), detected.warnings)
        self.assertIn("路径不存在", " ".join(detected.warnings))

    def test_falls_back_to_valid_candidate_and_keeps_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mesa = make_fake_mesa(Path(tmp) / "mesa")
            detected = core_env.detect_mesa(
                env={"MESA_DIR": "/definitely/not/here"}, fallbacks=(mesa,), glob_patterns=()
            )
        self.assertTrue(detected.is_valid)
        self.assertEqual(detected.mesa_dir, mesa)
        self.assertEqual(detected.source, core_env.SOURCE_DEFAULT)
        self.assertTrue(any("MESA_DIR" in w for w in detected.warnings))

    def test_no_install_found(self) -> None:
        detected = core_env.detect_mesa(env={}, fallbacks=("/definitely/not/here",), glob_patterns=())
        self.assertFalse(detected.is_valid)
        self.assertEqual(detected.source, core_env.SOURCE_DEFAULT)
        self.assertTrue(detected.warnings)
        self.assertIn("未找到可用的 MESA 安装", detected.warnings[-1])
        self.assertIn("不可用", detected.summary())

    def test_incomplete_install_reports_missing_optional_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "star" / "defaults").mkdir(parents=True)
            detected = core_env.detect_mesa(env={"MESA_DIR": tmp}, fallbacks=(), glob_patterns=())
        self.assertTrue(detected.is_valid)
        self.assertEqual(set(detected.missing), {"star/work", "star/test_suite"})
        self.assertTrue(any("可选" in w for w in detected.warnings))
        self.assertIn("缺少目录", detected.summary())

    def test_subdir_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            make_fake_mesa(Path(tmp))
            detected = core_env.detect_mesa(env={"MESA_DIR": tmp}, fallbacks=(), glob_patterns=())
        self.assertEqual(detected.star_defaults, os.path.join(tmp, "star", "defaults"))
        self.assertEqual(detected.star_work, os.path.join(tmp, "star", "work"))
        self.assertEqual(detected.star_test_suite, os.path.join(tmp, "star", "test_suite"))

    def test_no_candidates_at_all_yields_none_paths(self) -> None:
        """一个候选都没有时（env 为空 + fallbacks 为空），路径类属性必须为 None。"""
        detected = core_env.detect_mesa(env={}, fallbacks=(), glob_patterns=())
        self.assertFalse(detected.is_valid)
        self.assertIsNone(detected.mesa_dir)
        self.assertIsNone(detected.star_defaults)
        self.assertIsNone(detected.star_work)
        self.assertIsInstance(detected.summary(), str)

    def test_invalid_candidate_keeps_its_path_as_best_guess(self) -> None:
        """未找到可用安装时仍返回"最佳猜测路径"（供调用方提示用户），
        但 is_valid=False 且 warnings 非空 —— 不是静默回退。"""
        detected = core_env.detect_mesa(env={}, fallbacks=("/definitely/not/here",), glob_patterns=())
        self.assertFalse(detected.is_valid)
        self.assertEqual(detected.mesa_dir, "/definitely/not/here")
        self.assertEqual(detected.star_defaults, "/definitely/not/here/star/defaults")
        self.assertTrue(detected.warnings)

    def test_glob_discovers_install_when_env_is_bogus(self) -> None:
        """MESA_DIR 写错时，glob 扫描能找到 ~/mesa/mesa-<版本> 布局的安装。"""
        with tempfile.TemporaryDirectory() as tmp:
            make_fake_mesa(Path(tmp) / "mesa" / "mesa-24.08.1")
            detected = core_env.detect_mesa(
                env={"MESA_DIR": "/definitely/not/here"},
                fallbacks=(),
                glob_patterns=(os.path.join(tmp, "mesa", "mesa-*"),),
            )
        self.assertTrue(detected.is_valid)
        self.assertEqual(detected.mesa_dir, os.path.join(tmp, "mesa", "mesa-24.08.1"))
        self.assertEqual(detected.source, core_env.SOURCE_GLOB)
        self.assertTrue(any("MESA_DIR" in w for w in detected.warnings),
                        "无效环境变量仍要留下警告")

    def test_glob_discovers_install_without_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            make_fake_mesa(Path(tmp) / "mesa" / "mesa-24.08.1")
            detected = core_env.detect_mesa(
                env={}, fallbacks=(), glob_patterns=(os.path.join(tmp, "mesa", "mesa-*"),)
            )
        self.assertTrue(detected.is_valid)
        self.assertEqual(detected.source, core_env.SOURCE_GLOB)


class Candidates(unittest.TestCase):
    def test_env_var_comes_first(self) -> None:
        tried = core_env.candidates(env={"MESA_DIR": "/opt/mesa-custom"}, fallbacks=("~/mesa",), glob_patterns=())
        self.assertEqual(tried[0], (core_env.SOURCE_ENV, "/opt/mesa-custom"))
        self.assertEqual(tried[1], (core_env.SOURCE_DEFAULT, os.path.expanduser("~/mesa")))

    def test_blank_env_var_is_ignored(self) -> None:
        tried = core_env.candidates(env={"MESA_DIR": "   "}, fallbacks=("~/mesa",), glob_patterns=())
        self.assertEqual([source for source, _ in tried], [core_env.SOURCE_DEFAULT])

    def test_duplicate_candidates_are_deduplicated(self) -> None:
        tried = core_env.candidates(env={"MESA_DIR": "~/mesa"}, fallbacks=("~/mesa",), glob_patterns=())
        self.assertEqual(len(tried), 1)

    def test_tilde_is_expanded(self) -> None:
        tried = core_env.candidates(env={}, fallbacks=("~/mesa",), glob_patterns=())
        self.assertEqual(tried[0][1], os.path.expanduser("~/mesa"))
        self.assertNotIn("~", tried[0][1])

    def test_glob_candidates_append_after_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "mesa" / "mesa-24.08.1").mkdir(parents=True)
            tried = core_env.candidates(
                env={}, fallbacks=(), glob_patterns=(os.path.join(tmp, "mesa", "mesa-*"),)
            )
        self.assertEqual(tried, [(core_env.SOURCE_GLOB, os.path.join(tmp, "mesa", "mesa-24.08.1"))])


class ReadVersion(unittest.TestCase):
    def test_reads_first_existing_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            (data / "version_number").write_text("24.08.1\n", encoding="utf-8")
            self.assertEqual(core_env.read_version(tmp), "24.08.1")

    def test_absent_version_files_return_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(core_env.read_version(tmp))

    def test_none_and_missing_dir_return_none(self) -> None:
        self.assertIsNone(core_env.read_version(None))
        self.assertIsNone(core_env.read_version("/definitely/not/here"))


if __name__ == "__main__":
    unittest.main()

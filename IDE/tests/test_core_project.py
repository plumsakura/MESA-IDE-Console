"""core.project 单元测试：统一路径解析、项目名校验、模板复制。

覆盖阶段 2 的三项修复：
- P8：两份 ``get_mesa_paths`` 合并为统一实现（同样 5 个键）；
- P21b：无效 ``MESA_DIR`` 不再静默回退；
- 路径穿越：项目名不得逃出用户项目目录。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from core.project import (
    CORE_INLIST_FILES,
    DEFAULT_TEMPLATE_FILES,
    PNG_DIRNAME,
    copy_default_columns,
    copy_template_tree,
    create_project,
    ensure_png_dir,
    looks_like_mesa_project,
    missing_core_inlists,
    project_dir,
    project_paths,
    user_programs_dir,
    validate_project_name,
)


def _make_fake_mesa(root: Path, with_defaults_files: bool = True) -> str:
    for relative in ("star/defaults", "star/work", "star/test_suite"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    if with_defaults_files:
        for name in DEFAULT_TEMPLATE_FILES:
            (root / "star" / "defaults" / name).write_text(f"# {name}\n", encoding="utf-8")
    return str(root)


class UnifiedProjectPaths(unittest.TestCase):
    def test_returns_five_keys_used_by_legacy_shim(self) -> None:
        paths = project_paths(env={}, fallbacks=(), glob_patterns=())
        self.assertEqual(
            set(paths.as_legacy_dict()),
            {"mesa_dir", "defaults", "test_suite", "work", "user_programs"},
        )

    def test_valid_fake_install_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_fake_mesa(Path(tmp))
            paths = project_paths(env={"MESA_DIR": tmp}, fallbacks=(), glob_patterns=())
        self.assertTrue(paths.is_valid)
        self.assertEqual(paths.defaults, os.path.join(tmp, "star", "defaults"))
        self.assertEqual(paths.work, os.path.join(tmp, "star", "work"))
        self.assertEqual(paths.test_suite, os.path.join(tmp, "star", "test_suite"))
        self.assertEqual(paths.source, "env:MESA_DIR")

    def test_bogus_mesa_dir_is_kept_and_reported(self) -> None:
        """P21b：不再静默回退到 ~/mesa。"""
        paths = project_paths(env={"MESA_DIR": "/definitely/not/here"}, fallbacks=(), glob_patterns=())
        self.assertFalse(paths.is_valid)
        self.assertEqual(paths.mesa_dir, "/definitely/not/here")
        self.assertTrue(paths.warnings)

    def test_user_programs_default(self) -> None:
        self.assertEqual(user_programs_dir(env={}), os.path.expanduser("~/MESA_program"))

    def test_user_programs_override(self) -> None:
        self.assertEqual(user_programs_dir(env={"MESA_PROGRAMS_DIR": "/tmp/mp"}), "/tmp/mp")
        paths = project_paths(env={"MESA_PROGRAMS_DIR": "/tmp/mp"}, fallbacks=(), glob_patterns=())
        self.assertEqual(paths.user_programs, "/tmp/mp")

    def test_tilde_in_override_is_expanded(self) -> None:
        self.assertEqual(
            user_programs_dir(env={"MESA_PROGRAMS_DIR": "~/elsewhere"}),
            os.path.expanduser("~/elsewhere"),
        )


class ProjectNameValidation(unittest.TestCase):
    def test_accepts_reasonable_names(self) -> None:
        for name in ("star_work", "我的项目", "proj-1.2", "a b", "2179"):
            with self.subTest(name=name):
                self.assertEqual(validate_project_name(name), name)

    def test_strips_surrounding_whitespace(self) -> None:
        self.assertEqual(validate_project_name("  proj  "), "proj")

    def test_rejects_empty_and_whitespace_only(self) -> None:
        for name in ("", "   "):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    validate_project_name(name)

    def test_rejects_dot_names(self) -> None:
        for name in (".", ".."):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    validate_project_name(name)

    def test_rejects_path_separators(self) -> None:
        for name in ("a/b", "a\\b", "/abs", "../x", "..\\x", "a/../b"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    validate_project_name(name)

    def test_rejects_null_byte(self) -> None:
        with self.assertRaises(ValueError):
            validate_project_name("a\x00b")

    def test_traversal_is_blocked_before_touching_filesystem(self) -> None:
        with self.assertRaises(ValueError):
            project_dir(os.path.expanduser("~/MESA_program"), "../../etc/passwd")

    def test_project_dir_joins_valid_name(self) -> None:
        self.assertEqual(
            project_dir("/base", "proj"), os.path.join("/base", "proj")
        )


class TemplateCopying(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.template = base / "template"
        (self.template / "sub").mkdir(parents=True)
        (self.template / "inlist").write_text("&controls\n/\n", encoding="utf-8")
        (self.template / "inlist_pgstar").write_text("&pgstar\n/\n", encoding="utf-8")
        (self.template / "sub" / "nested.txt").write_text("nested\n", encoding="utf-8")
        self.defaults = base / "defaults"
        self.defaults.mkdir()
        for name in DEFAULT_TEMPLATE_FILES:
            (self.defaults / name).write_text(f"# default {name}\n", encoding="utf-8")
        self.target = base / "target"
        self.target.mkdir()

    def test_copy_template_tree_copies_files_and_subdirs(self) -> None:
        copied = copy_template_tree(str(self.template), str(self.target))
        self.assertEqual(set(copied), {"inlist", "inlist_pgstar", "sub"})
        self.assertTrue((self.target / "inlist").is_file())
        self.assertTrue((self.target / "sub" / "nested.txt").is_file())

    def test_copy_template_tree_merges_existing_subdir(self) -> None:
        (self.target / "sub").mkdir()
        (self.target / "sub" / "keep.txt").write_text("keep\n", encoding="utf-8")
        copy_template_tree(str(self.template), str(self.target))
        self.assertTrue((self.target / "sub" / "keep.txt").is_file())
        self.assertTrue((self.target / "sub" / "nested.txt").is_file())

    def test_missing_template_dir_copies_nothing(self) -> None:
        self.assertEqual(copy_template_tree("/definitely/not/here", str(self.target)), [])

    def test_copy_default_columns_only_when_absent(self) -> None:
        existing = self.target / DEFAULT_TEMPLATE_FILES[0]
        existing.write_text("# 用户已有内容\n", encoding="utf-8")

        copied = copy_default_columns(str(self.defaults), str(self.target))

        self.assertEqual(copied, [DEFAULT_TEMPLATE_FILES[1]])
        self.assertEqual(existing.read_text(encoding="utf-8"), "# 用户已有内容\n")

    def test_copy_default_columns_without_defaults_dir(self) -> None:
        self.assertEqual(copy_default_columns(None, str(self.target)), [])

    def test_ensure_png_dir_creates_and_is_idempotent(self) -> None:
        first = ensure_png_dir(str(self.target))
        second = ensure_png_dir(str(self.target))
        self.assertEqual(first, second)
        self.assertTrue(Path(first).is_dir())
        self.assertEqual(Path(first).name, PNG_DIRNAME)

    def test_create_project_end_to_end(self) -> None:
        base = Path(self._tmp.name) / "user_programs"
        target = create_project(
            name="my_star",
            template_dir=str(self.template),
            user_programs=str(base),
            defaults_dir=str(self.defaults),
        )
        self.assertEqual(target, str(base / "my_star"))
        self.assertTrue((base / "my_star" / "inlist").is_file())
        self.assertTrue((base / "my_star" / PNG_DIRNAME).is_dir())
        for name in DEFAULT_TEMPLATE_FILES:
            self.assertTrue((base / "my_star" / name).is_file())

    def test_create_project_rejects_traversal_name(self) -> None:
        base = Path(self._tmp.name) / "user_programs"
        with self.assertRaises(ValueError):
            create_project(
                name="../../escaped",
                template_dir=str(self.template),
                user_programs=str(base),
            )
        self.assertFalse((Path(self._tmp.name).parent / "escaped").exists())


class ProjectRecognition(unittest.TestCase):
    def test_missing_core_inlists_lists_all_when_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(set(missing_core_inlists(tmp)), set(CORE_INLIST_FILES))
            self.assertFalse(looks_like_mesa_project(tmp))

    def test_partial_project_reports_only_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "inlist").write_text("&controls\n/\n", encoding="utf-8")
            self.assertTrue(looks_like_mesa_project(tmp))
            self.assertEqual(
                set(missing_core_inlists(tmp)), {"inlist_pgstar", "inlist_project"}
            )


if __name__ == "__main__":
    unittest.main()

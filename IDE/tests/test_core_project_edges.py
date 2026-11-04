"""core.project 边界用例：模板复制、项目名校验、路径解析。

原有 ``tests/test_core_project.py`` 覆盖正常路径；这里专门补**边界**：

- 复制：模板缺失 / 子目录合并 / 同名文件覆盖 / 符号链接 / 默认列不覆盖已有；
- 创建：非法项目名不得落盘（路径穿越回归）、部分失败时的现场；
- 路径：``MESA_PROGRAMS_DIR`` 覆盖、``~`` 展开、候选目录优先级；
- 校验：空格与 Unicode 允许，分隔符/``..``/空字符/空串拒绝。
"""

from __future__ import annotations

import os
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

from core.project import (
    CORE_INLIST_FILES,
    DEFAULT_TEMPLATE_FILES,
    DEFAULT_USER_PROGRAMS,
    ProjectPaths,
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


class ValidateProjectNameEdges(unittest.TestCase):
    def test_valid_names_are_trimmed_and_kept_verbatim(self) -> None:
        self.assertEqual(validate_project_name("  1M_pre_ms  "), "1M_pre_ms")
        self.assertEqual(validate_project_name("项目-1"), "项目-1")
        self.assertEqual(validate_project_name("a b"), "a b", "空格属于合法项目名")

    def test_rejects_empty_and_whitespace_only(self) -> None:
        for name in ("", "   ", "\t\n"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    validate_project_name(name)

    def test_rejects_dot_and_dotdot(self) -> None:
        for name in (".", "..", " .. "):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    validate_project_name(name)

    def test_rejects_embedded_dotdot(self) -> None:
        for name in ("../evil", "a/../../evil", "..\\evil"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    validate_project_name(name)

    def test_rejects_path_separators(self) -> None:
        for name in ("a/b", "a\\b", "/abs", "C:/x"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    validate_project_name(name)

    def test_rejects_null_byte(self) -> None:
        with self.assertRaises(ValueError):
            validate_project_name("bad\x00name")

    def test_project_dir_never_escapes_user_programs(self) -> None:
        base = "/home/u/MESA_program"
        self.assertEqual(project_dir(base, "ok"), os.path.join(base, "ok"))
        for hostile in ("../x", "..", "/etc/passwd", "a/../../b"):
            with self.subTest(hostile=hostile):
                with self.assertRaises(ValueError):
                    project_dir(base, hostile)


class UserProgramsDirEdges(unittest.TestCase):
    def test_default_when_env_missing_or_blank(self) -> None:
        self.assertEqual(
            user_programs_dir({}), os.path.expanduser(DEFAULT_USER_PROGRAMS)
        )
        self.assertEqual(
            user_programs_dir({"MESA_PROGRAMS_DIR": "   "}),
            os.path.expanduser(DEFAULT_USER_PROGRAMS),
        )

    def test_env_override_wins_and_expands_user(self) -> None:
        self.assertEqual(user_programs_dir({"MESA_PROGRAMS_DIR": "/data/projs"}), "/data/projs")
        self.assertEqual(
            user_programs_dir({"MESA_PROGRAMS_DIR": "~/projs"}),
            os.path.expanduser("~/projs"),
        )

    def test_none_means_real_environment(self) -> None:
        with mock.patch.dict(os.environ, {"MESA_PROGRAMS_DIR": "/tmp/p"}, clear=False):
            self.assertEqual(user_programs_dir(), "/tmp/p")


class ProjectPathsEdges(unittest.TestCase):
    def test_keys_are_unified_five(self) -> None:
        paths = ProjectPaths("m", "d", "t", "w", "u")
        self.assertEqual(
            set(paths.as_legacy_dict()),
            {"mesa_dir", "defaults", "test_suite", "work", "user_programs"},
        )

    def test_mesa_dir_env_is_preferred_over_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mesa = pathlib.Path(tmp) / "real_mesa"
            (mesa / "star" / "defaults").mkdir(parents=True)
            (mesa / "star" / "work").mkdir(parents=True)
            # 故意不建 star/test_suite：它是"可选目录"
            fallback = pathlib.Path(tmp) / "other"
            (fallback / "star" / "defaults").mkdir(parents=True)

            paths = project_paths(
                env={"MESA_DIR": str(mesa), "MESA_PROGRAMS_DIR": str(pathlib.Path(tmp) / "progs")},
                fallbacks=[str(fallback)],
                glob_patterns=(),
            )

        self.assertTrue(paths.is_valid)
        self.assertEqual(os.path.realpath(paths.mesa_dir), os.path.realpath(mesa))
        self.assertEqual(paths.source, "env:MESA_DIR")
        self.assertEqual(paths.defaults, str(mesa / "star" / "defaults"))
        self.assertEqual(paths.work, str(mesa / "star" / "work"))
        self.assertEqual(paths.test_suite, str(mesa / "star" / "test_suite"))
        self.assertFalse(os.path.isdir(paths.test_suite), "可选目录确实不存在")
        self.assertTrue(
            any("test_suite" in warning for warning in paths.warnings),
            "缺失可选目录必须出现在 warnings 里",
        )

    def test_user_programs_comes_from_env_even_without_mesa(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = project_paths(
                env={"MESA_PROGRAMS_DIR": tmp},
                fallbacks=[str(pathlib.Path(tmp) / "none")],
                glob_patterns=(),
            )

        self.assertFalse(paths.is_valid)
        self.assertEqual(paths.user_programs, tmp)
        self.assertEqual(paths.mesa_dir, str(pathlib.Path(tmp) / "none"))
        self.assertTrue(paths.warnings)


class CopyTemplateTreeEdges(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = pathlib.Path(self.tmp.name)
        self.source = self.base / "template"
        self.target = self.base / "target"
        self.source.mkdir()
        self.target.mkdir()

    def test_missing_source_is_skipped_without_creating_target(self) -> None:
        empty = self.base / "does_not_exist"
        copied = copy_template_tree(str(empty), str(self.target))
        self.assertEqual(copied, [])
        self.assertEqual(list(self.target.iterdir()), [])

    def test_subdirectories_are_merged_not_replaced(self) -> None:
        (self.source / "src").mkdir()
        (self.source / "src" / "run.f90").write_text("program x\n", encoding="utf-8")
        (self.target / "src").mkdir()
        (self.target / "src" / "keep.txt").write_text("keep\n", encoding="utf-8")

        copied = copy_template_tree(str(self.source), str(self.target))

        self.assertEqual(copied, ["src"])
        self.assertEqual(
            sorted(p.name for p in (self.target / "src").iterdir()),
            ["keep.txt", "run.f90"],
            "目标目录里已有的文件必须保留",
        )

    def test_same_name_files_are_overwritten(self) -> None:
        (self.source / "inlist").write_text("new\n", encoding="utf-8")
        (self.target / "inlist").write_text("old\n", encoding="utf-8")

        copy_template_tree(str(self.source), str(self.target))

        self.assertEqual((self.target / "inlist").read_text(encoding="utf-8"), "new\n")

    def test_permissions_and_mtime_are_preserved_for_files(self) -> None:
        script = self.source / "mk"
        script.write_text("#!/bin/bash\n", encoding="utf-8")
        os.chmod(script, 0o755)
        os.utime(script, (1_600_000_000, 1_600_000_000))

        copy_template_tree(str(self.source), str(self.target))

        copied = self.target / "mk"
        self.assertTrue(os.access(copied, os.X_OK), "可执行位必须保留")
        self.assertAlmostEqual(copied.stat().st_mtime, 1_600_000_000, delta=2)

    def test_symlinked_directory_is_copied_as_real_directory(self) -> None:
        (self.source / "real").mkdir()
        (self.source / "real" / "f.txt").write_text("x\n", encoding="utf-8")
        os.symlink("real", self.source / "link")

        copy_template_tree(str(self.source), str(self.target))

        link = self.target / "link"
        self.assertTrue(link.is_dir())
        self.assertFalse(link.is_symlink(), "copytree 会跟随符号链接（记录当前行为）")
        self.assertTrue((link / "f.txt").is_file())

    def test_empty_template_reports_nothing_copied(self) -> None:
        self.assertEqual(copy_template_tree(str(self.source), str(self.target)), [])


class CopyDefaultColumnsEdges(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = pathlib.Path(self.tmp.name)
        self.defaults = self.base / "defaults"
        self.target = self.base / "target"
        self.defaults.mkdir()
        self.target.mkdir()

    def test_defaults_dir_none_or_missing_copies_nothing(self) -> None:
        self.assertEqual(copy_default_columns(None, str(self.target)), [])
        self.assertEqual(copy_default_columns(str(self.base / "nope"), str(self.target)), [])

    def test_existing_target_file_is_not_overwritten(self) -> None:
        for name in DEFAULT_TEMPLATE_FILES:
            (self.defaults / name).write_text("default\n", encoding="utf-8")
        (self.target / "history_columns.list").write_text("custom\n", encoding="utf-8")

        copied = copy_default_columns(str(self.defaults), str(self.target))

        self.assertEqual(copied, ["profile_columns.list"])
        self.assertEqual(
            (self.target / "history_columns.list").read_text(encoding="utf-8"),
            "custom\n",
            "用户自定义的列定义不得被默认文件覆盖",
        )

    def test_only_requested_names_are_considered(self) -> None:
        (self.defaults / "other.list").write_text("x\n", encoding="utf-8")
        copied = copy_default_columns(str(self.defaults), str(self.target))
        self.assertEqual(copied, [])
        self.assertFalse((self.target / "other.list").exists())

    def test_custom_names_argument(self) -> None:
        (self.defaults / "extra.list").write_text("x\n", encoding="utf-8")
        copied = copy_default_columns(
            str(self.defaults), str(self.target), names=("extra.list",)
        )
        self.assertEqual(copied, ["extra.list"])


class EnsurePngDirEdges(unittest.TestCase):
    def test_creates_and_reuses_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = ensure_png_dir(tmp)
            second = ensure_png_dir(tmp)
            self.assertTrue(os.path.isdir(first))
            self.assertEqual(first, second)

    def test_makedirs_failure_propagates(self) -> None:
        def boom(*_args, **_kwargs):
            raise PermissionError("只读文件系统")

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PermissionError):
                ensure_png_dir(tmp, makedirs=boom)


class CreateProjectEdges(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = pathlib.Path(self.tmp.name)
        self.user_programs = self.base / "MESA_program"
        self.template = self.base / "work"
        self.template.mkdir(parents=True)
        (self.template / "inlist").write_text("&controls\n/\n", encoding="utf-8")
        (self.template / "src").mkdir()
        (self.template / "src" / "run.f90").write_text("program x\n", encoding="utf-8")
        self.defaults = self.base / "defaults"
        self.defaults.mkdir()
        for name in DEFAULT_TEMPLATE_FILES:
            (self.defaults / name).write_text(f"{name}\n", encoding="utf-8")

    def test_full_layout_is_created(self) -> None:
        target = create_project(
            "m1", str(self.template), str(self.user_programs), str(self.defaults)
        )

        self.assertEqual(os.path.realpath(target),
                         os.path.realpath(self.user_programs / "m1"))
        for relative in ("inlist", "src/run.f90", "png", *DEFAULT_TEMPLATE_FILES):
            self.assertTrue(os.path.exists(os.path.join(target, relative)), relative)

    def test_invalid_name_creates_nothing(self) -> None:
        with self.assertRaises(ValueError):
            create_project(
                "../escape", str(self.template), str(self.user_programs), str(self.defaults)
            )
        self.assertFalse(self.user_programs.exists(), "非法项目名不得创建任何目录")

    def test_existing_project_is_reused_and_updated(self) -> None:
        target = self.user_programs / "m1"
        target.mkdir(parents=True)
        (target / "user_note.txt").write_text("mine\n", encoding="utf-8")

        returned = create_project(
            "m1", str(self.template), str(self.user_programs), str(self.defaults)
        )

        self.assertEqual(os.path.realpath(returned), os.path.realpath(target))
        self.assertTrue((target / "user_note.txt").is_file(), "已有文件必须保留")
        self.assertTrue((target / "inlist").is_file())

    def test_missing_template_still_yields_usable_project(self) -> None:
        target = create_project(
            "m2", str(self.base / "no_template"), str(self.user_programs), None
        )

        self.assertTrue(os.path.isdir(os.path.join(target, "png")))
        self.assertEqual(list(pathlib.Path(target).iterdir())[0].name, "png")


class ProjectRecognitionEdges(unittest.TestCase):
    def test_missing_core_inlists_lists_all_when_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(missing_core_inlists(tmp), CORE_INLIST_FILES)
            self.assertFalse(looks_like_mesa_project(tmp))

    def test_partial_project_reports_only_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / "inlist").write_text("&controls\n/\n", encoding="utf-8")
            self.assertEqual(
                missing_core_inlists(tmp), ("inlist_pgstar", "inlist_project")
            )
            self.assertTrue(looks_like_mesa_project(tmp))

    def test_exists_probe_is_injectable(self) -> None:
        seen: list[str] = []

        def probe(path: str) -> bool:
            seen.append(os.path.basename(path))
            return os.path.basename(path) == "inlist"

        self.assertEqual(
            missing_core_inlists("/proj", exists=probe), ("inlist_pgstar", "inlist_project")
        )
        self.assertTrue(looks_like_mesa_project("/proj", exists=probe))
        self.assertIn("inlist", seen)

    def test_nonexistent_directory_is_not_a_project(self) -> None:
        self.assertFalse(looks_like_mesa_project("/definitely/not/here"))


class CopyTemplateTreeFailureModes(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = pathlib.Path(self.tmp.name)
        self.source = self.base / "src"
        self.source.mkdir()
        (self.source / "inlist").write_text("x\n", encoding="utf-8")
        self.target = self.base / "target"
        self.target.mkdir()

    def test_unreadable_source_propagates_error(self) -> None:
        """列目录失败必须抛出（注入 listdir，避免依赖真实文件权限）。"""

        def denied(_path: str):
            raise PermissionError("denied")

        with self.assertRaises(PermissionError):
            copy_template_tree(str(self.source), str(self.target), listdir=denied)

    def test_single_file_copy_failure_propagates(self) -> None:
        with mock.patch("shutil.copy2", side_effect=OSError("磁盘满了")):
            with self.assertRaises(OSError):
                copy_template_tree(str(self.source), str(self.target))

    def test_copytree_failure_propagates(self) -> None:
        (self.source / "src").mkdir()
        with mock.patch("shutil.copytree", side_effect=OSError("磁盘满了")):
            with self.assertRaises(OSError):
                copy_template_tree(str(self.source), str(self.target))


if __name__ == "__main__":
    unittest.main()

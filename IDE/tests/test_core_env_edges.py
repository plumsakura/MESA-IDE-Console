"""core.env 边界用例：候选优先级、不静默回退、版本号读取。

原有 ``tests/test_core_env.py`` 覆盖正常路径；这里补**边界**：

- ``MESA_DIR`` 为空/空白/``~`` 扩展、候选去重、fallback 覆盖;
- 无效 ``MESA_DIR`` 不得被静默忽略（必须进 ``warnings`` 且 ``source`` 保留）；
- 必需目录 vs 可选目录的区分；
- ``read_version``：候选顺序、空文件、读取失败、解码失败、多行内容。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.env import (
    ENV_VAR,
    FALLBACK_DIRS,
    REQUIRED_SUBDIRS,
    SOURCE_DEFAULT,
    SOURCE_ENV,
    VERSION_FILES,
    MesaEnvironment,
    candidates,
    detect_mesa,
    read_version,
    validate_mesa_dir,
)


def fake_exists(paths: set[str]):
    """返回一个只认 ``paths`` 的 ``exists`` 探针（零文件系统副作用）。"""
    normalized = {os.path.normpath(p) for p in paths}

    def exists(path: str) -> bool:
        return os.path.normpath(path) in normalized

    return exists


def install_at(root: str) -> set[str]:
    root = os.path.normpath(root)
    return {root, *(os.path.join(root, rel) for rel in REQUIRED_SUBDIRS)}


class ValidateMesaDirEdges(unittest.TestCase):
    def test_empty_or_none_path_is_invalid(self) -> None:
        for value in ("", "   ", "/nonexistent"):
            with self.subTest(value=value):
                is_valid, missing_required, missing_expected = validate_mesa_dir(
                    value, exists=fake_exists(set())
                )
                self.assertFalse(is_valid)
                self.assertEqual(missing_required, tuple(REQUIRED_SUBDIRS))
                self.assertEqual(missing_expected, tuple(
                    rel for rel in ("star/work", "star/test_suite")
                ))

    def test_required_present_expected_missing_is_valid(self) -> None:
        root = "/opt/mesa"
        is_valid, missing_required, missing_expected = validate_mesa_dir(
            root, exists=fake_exists(install_at(root))
        )
        self.assertTrue(is_valid)
        self.assertEqual(missing_required, ())
        self.assertIn("star/work", missing_expected)
        self.assertIn("star/test_suite", missing_expected)

    def test_all_dirs_present_has_no_missing(self) -> None:
        root = "/opt/mesa"
        present = install_at(root) | {
            os.path.join(root, "star/work"),
            os.path.join(root, "star/test_suite"),
        }
        is_valid, missing_required, missing_expected = validate_mesa_dir(
            root, exists=fake_exists(present)
        )
        self.assertTrue(is_valid)
        self.assertEqual(missing_required, ())
        self.assertEqual(missing_expected, ())

    def test_real_filesystem_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "star" / "defaults").mkdir(parents=True)
            is_valid, missing_required, missing_expected = validate_mesa_dir(tmp)
            self.assertTrue(is_valid)
            self.assertEqual(missing_required, ())
            self.assertTrue(missing_expected)


class CandidatesEdges(unittest.TestCase):
    def test_no_env_falls_back_to_default_dirs_in_order(self) -> None:
        result = candidates(env={}, glob_patterns=())
        self.assertEqual([source for source, _ in result],
                         [SOURCE_DEFAULT] * len(FALLBACK_DIRS))
        self.assertEqual(
            [path for _, path in result], [os.path.expanduser(p) for p in FALLBACK_DIRS]
        )

    def test_blank_env_is_ignored(self) -> None:
        result = candidates(env={ENV_VAR: "   "}, glob_patterns=())
        self.assertNotIn(SOURCE_ENV, [source for source, _ in result])

    def test_env_is_first_and_expands_user(self) -> None:
        result = candidates(env={ENV_VAR: "~/mesa"}, glob_patterns=())
        self.assertEqual(result[0], (SOURCE_ENV, os.path.expanduser("~/mesa")))

    def test_duplicate_of_env_path_is_not_repeated(self) -> None:
        home_mesa = os.path.expanduser("~/mesa")
        result = candidates(env={ENV_VAR: home_mesa}, fallbacks=("~/mesa",), glob_patterns=())
        self.assertEqual(result, [(SOURCE_ENV, home_mesa)])

    def test_custom_fallbacks_replace_defaults(self) -> None:
        result = candidates(env={}, fallbacks=("/a", "/b"), glob_patterns=())
        self.assertEqual(result, [(SOURCE_DEFAULT, "/a"), (SOURCE_DEFAULT, "/b")])

    def test_duplicate_fallbacks_are_collapsed(self) -> None:
        result = candidates(env={}, fallbacks=("/a", "/a", "/b"), glob_patterns=())
        self.assertEqual([path for _, path in result], ["/a", "/b"])

    def test_real_environment_is_used_when_env_is_none(self) -> None:
        with mock.patch.dict(os.environ, {ENV_VAR: "/from/env"}, clear=False):
            self.assertEqual(candidates(glob_patterns=())[0], (SOURCE_ENV, "/from/env"))


class DetectMesaEdges(unittest.TestCase):
    def test_invalid_env_does_not_silently_fall_back(self) -> None:
        """P21b 回归：无效 MESA_DIR 必须记 warning，并如实报告来源。"""
        result = detect_mesa(env={ENV_VAR: "/bad/mesa"}, fallbacks=(), glob_patterns=(), exists=fake_exists(set()))

        self.assertFalse(result.is_valid)
        self.assertEqual(result.mesa_dir, "/bad/mesa", "保留最佳猜测路径供 UI 展示")
        self.assertEqual(result.source, SOURCE_ENV)
        self.assertTrue(
            any("不是可用的 MESA 安装" in warning for warning in result.warnings)
        )
        self.assertIn("/bad/mesa", result.summary())

    def test_valid_fallback_wins_when_env_is_invalid(self) -> None:
        fallback = "/usr/local/mesa"
        result = detect_mesa(
            env={ENV_VAR: "/bad/mesa"},
            fallbacks=(fallback,),
            glob_patterns=(),
            exists=fake_exists(install_at(fallback)),
        )

        self.assertTrue(result.is_valid)
        self.assertEqual(result.mesa_dir, fallback)
        self.assertEqual(result.source, SOURCE_DEFAULT)
        self.assertTrue(
            any("不是可用的 MESA 安装" in warning for warning in result.warnings),
            "无效的 MESA_DIR 仍必须被报告",
        )
        self.assertTrue(result.summary().startswith("MESA 安装可用"))

    def test_incomplete_fallback_is_reported_separately(self) -> None:
        incomplete = "/opt/mesa"
        result = detect_mesa(
            env={},
            fallbacks=(incomplete,),
            glob_patterns=(),
            exists=fake_exists({incomplete}),
        )

        self.assertFalse(result.is_valid)
        self.assertTrue(any("候选 MESA 安装不完整" in w for w in result.warnings))
        self.assertEqual(result.missing, REQUIRED_SUBDIRS)

    def test_no_candidates_at_all(self) -> None:
        result = detect_mesa(env={}, fallbacks=(), glob_patterns=(), exists=fake_exists(set()))

        self.assertFalse(result.is_valid)
        self.assertIsNone(result.mesa_dir)
        self.assertEqual(result.source, "not_found")
        self.assertEqual(result.warnings, ("未找到可用的 MESA 安装（已尝试: ）",))
        self.assertEqual(result.summary(), "未检测到 MESA 安装；缺少目录: star/defaults")

    def test_expected_dirs_missing_produces_warning_but_valid(self) -> None:
        root = "/opt/mesa"
        result = detect_mesa(env={ENV_VAR: root}, fallbacks=(), glob_patterns=(), exists=fake_exists(install_at(root)))

        self.assertTrue(result.is_valid)
        self.assertTrue(any("缺少可选目录" in warning for warning in result.warnings))
        self.assertIn("star/work", result.missing)
        self.assertIn("缺少目录", result.summary())

    def test_first_valid_candidate_wins(self) -> None:
        first, second = "/a/mesa", "/b/mesa"
        result = detect_mesa(
            env={},
            fallbacks=(first, second),
            glob_patterns=(),
            exists=fake_exists(install_at(first) | install_at(second)),
        )
        self.assertEqual(result.mesa_dir, first)
        self.assertEqual(result.source, SOURCE_DEFAULT)

    def test_relative_path_is_kept_as_is(self) -> None:
        result = detect_mesa(env={ENV_VAR: "./mesa"}, fallbacks=(), glob_patterns=(), exists=fake_exists(set()))
        self.assertEqual(result.mesa_dir, "./mesa")


class MesaEnvironmentValueObject(unittest.TestCase):
    def test_subdir_helpers(self) -> None:
        env = MesaEnvironment("/opt/mesa", SOURCE_ENV, True)
        self.assertEqual(env.star_defaults, "/opt/mesa/star/defaults")
        self.assertEqual(env.star_work, "/opt/mesa/star/work")
        self.assertEqual(env.star_test_suite, "/opt/mesa/star/test_suite")
        self.assertEqual(env.subdir("png"), "/opt/mesa/png")

    def test_subdir_helpers_without_mesa_dir(self) -> None:
        env = MesaEnvironment(None, "not_found", False)
        self.assertIsNone(env.subdir("star"))
        self.assertIsNone(env.star_defaults)
        self.assertIsNone(env.star_work)
        self.assertIsNone(env.star_test_suite)

    def test_summary_variants(self) -> None:
        unavailable = MesaEnvironment("/x", SOURCE_ENV, False, missing=("star/defaults",))
        self.assertIn("MESA 安装不可用", unavailable.summary())
        self.assertIn("缺少目录: star/defaults", unavailable.summary())

    def test_is_frozen_and_hashable(self) -> None:
        env = MesaEnvironment("/x", SOURCE_ENV, True)
        with self.assertRaises(Exception):
            env.mesa_dir = "/y"  # type: ignore[misc]
        self.assertEqual(hash(env), hash(MesaEnvironment("/x", SOURCE_ENV, True)))


class ReadVersionEdges(unittest.TestCase):
    def test_none_or_empty_dir_returns_none(self) -> None:
        self.assertIsNone(read_version(None))
        self.assertIsNone(read_version(""))

    def test_first_candidate_wins(self) -> None:
        seen: list[str] = []

        class Handle:
            def __init__(self, text: str) -> None:
                self._text = text

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def read(self) -> str:
                return self._text

        def opener(path: str, *_args, **_kwargs):
            seen.append(os.path.basename(path))
            return Handle("r24.08.1\n" if path.endswith("version_number") else "")

        self.assertEqual(read_version("/opt/mesa", opener=opener), "r24.08.1")
        self.assertEqual(seen[0], "version_number")

    def test_whitespace_only_file_is_skipped(self) -> None:
        paths: list[str] = []

        def opener(path: str, *_args, **_kwargs):
            paths.append(path)
            text = "   \n\n" if path.endswith("data/version_number") else "v2\n"

            class Handle:
                def __enter__(self):
                    return self

                def __exit__(self, *_exc):
                    return False

                def read(self):
                    return text

            return Handle()

        self.assertEqual(read_version("/opt/mesa", opener=opener), "v2")
        self.assertEqual(len(paths), 2)

    def test_all_candidates_missing_returns_none(self) -> None:
        def opener(*_args, **_kwargs):
            raise FileNotFoundError("no such file")

        self.assertIsNone(read_version("/opt/mesa", opener=opener))

    def test_multi_line_file_returns_first_line(self) -> None:
        def opener(*_args, **_kwargs):
            class Handle:
                def __enter__(self):
                    return self

                def __exit__(self, *_exc):
                    return False

                def read(self):
                    return "  r24.08.1  \nsecond line\n"

            return Handle()

        self.assertEqual(read_version("/opt/mesa", opener=opener), "r24.08.1")

    def test_unicode_errors_do_not_raise(self) -> None:
        """读取时 errors="replace"，坏字节也必须返回文本而不是抛异常。"""
        with tempfile.TemporaryDirectory() as tmp:
            version_dir = Path(tmp) / "data"
            version_dir.mkdir()
            (version_dir / "version_number").write_bytes(b"\xff\xfe r24.08\n")
            # errors="replace"：坏字节变成替换符而不是抛 UnicodeDecodeError
            self.assertEqual(read_version(tmp), "\ufffd\ufffd r24.08")

    def test_real_filesystem_candidates_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "version_number").write_text("plain\n", encoding="utf-8")
            self.assertEqual(read_version(tmp), "plain")
            self.assertTrue(
                (Path(tmp) / VERSION_FILES[1]).is_file(), "用的是候选里的第二个文件"
            )

    def test_opener_receives_utf8_and_replace(self) -> None:
        captured: dict = {}

        def opener(path: str, mode: str, **kwargs):
            captured.update(path=path, mode=mode, **kwargs)

            class Handle:
                def __enter__(self):
                    return self

                def __exit__(self, *_exc):
                    return False

                def read(self):
                    return "v1\n"

            return Handle()

        self.assertEqual(read_version("/x", opener=opener), "v1")
        self.assertEqual(captured["mode"], "r")
        self.assertEqual(captured["encoding"], "utf-8")
        self.assertEqual(captured["errors"], "replace")


if __name__ == "__main__":
    unittest.main()

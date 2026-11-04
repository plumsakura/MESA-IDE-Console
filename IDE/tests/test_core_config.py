"""core.config 单元测试：版本单一来源、设置覆盖、日志落地。

注意：配置根 logger 会全局生效，因此本模块的用例都会在结束时恢复原状。
"""

from __future__ import annotations

import logging
import os
import tempfile
import unittest
from pathlib import Path

from core.config import (
    APP_NAME,
    DEFAULT_LOG_FILENAME,
    DEFAULT_VIDEO_FPS,
    DEFAULT_VIDEO_PREFIX,
    Settings,
    __version__,
    configure_logging,
    default_log_path,
    load_settings,
    project_root,
)


class LoggingStateTestCase(unittest.TestCase):
    """保存/恢复根 logger 状态，避免污染其他测试的输出。"""

    def setUp(self) -> None:
        super().setUp()
        root = logging.getLogger()
        self._saved_handlers = list(root.handlers)
        self._saved_level = root.level
        self._saved_path = getattr(root, "_mesa_ide_log_path", None)
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        root = logging.getLogger()
        for handler in list(root.handlers):
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:  # noqa: BLE001 - 关闭失败不影响测试
                pass
        for handler in self._saved_handlers:
            root.addHandler(handler)
        root.setLevel(self._saved_level)
        root._mesa_ide_log_path = self._saved_path  # type: ignore[attr-defined]


class VersionAndTitle(unittest.TestCase):
    def test_version_is_single_source(self) -> None:
        settings = Settings()
        self.assertEqual(settings.app_name, APP_NAME)
        self.assertEqual(settings.version, __version__)

    def test_window_label_matches_baseline_wording(self) -> None:
        """基线启动面板显示的就是这一行，重构只是把版本号收拢到单一来源。"""
        self.assertEqual(Settings().window_label(), "MESA Control Console v1.1 (Environment Managed)")
        self.assertEqual(Settings().title(), "MESA Control Console v1.1")


class LoadSettings(unittest.TestCase):
    def test_defaults_match_baseline_behaviour(self) -> None:
        settings = load_settings(env={})
        self.assertEqual(settings.log_level, "INFO")
        self.assertEqual(settings.video_fps, DEFAULT_VIDEO_FPS)
        self.assertEqual(settings.video_prefix, DEFAULT_VIDEO_PREFIX)
        self.assertIsNone(settings.log_file)
        self.assertEqual(settings.user_programs, os.path.expanduser("~/MESA_program"))

    def test_environment_overrides(self) -> None:
        settings = load_settings(
            env={
                "MESA_IDE_LOG_LEVEL": "debug",
                "MESA_IDE_LOG_FILE": "/tmp/custom.log",
                "MESA_IDE_VIDEO_FPS": "24",
                "MESA_IDE_VIDEO_PREFIX": "rho",
                "MESA_PROGRAMS_DIR": "/tmp/programs",
            }
        )
        self.assertEqual(settings.log_level, "DEBUG")
        self.assertEqual(settings.log_file, "/tmp/custom.log")
        self.assertEqual(settings.video_fps, 24)
        self.assertEqual(settings.video_prefix, "rho")
        self.assertEqual(settings.user_programs, "/tmp/programs")

    def test_invalid_values_fall_back(self) -> None:
        settings = load_settings(
            env={"MESA_IDE_LOG_LEVEL": "胡说", "MESA_IDE_VIDEO_FPS": "abc"}
        )
        self.assertEqual(settings.log_level, "INFO")
        self.assertEqual(settings.video_fps, DEFAULT_VIDEO_FPS)

    def test_non_positive_fps_falls_back(self) -> None:
        self.assertEqual(load_settings(env={"MESA_IDE_VIDEO_FPS": "0"}).video_fps, DEFAULT_VIDEO_FPS)

    def test_blank_prefix_falls_back(self) -> None:
        self.assertEqual(
            load_settings(env={"MESA_IDE_VIDEO_PREFIX": "   "}).video_prefix, DEFAULT_VIDEO_PREFIX
        )


class LogPathAndConfigure(LoggingStateTestCase):
    def test_default_log_path_is_inside_project(self) -> None:
        path = default_log_path()
        self.assertEqual(path.parent.parent, project_root())
        self.assertEqual(path.name, DEFAULT_LOG_FILENAME)

    def test_configure_logging_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "nested" / "mesa.log"
            settings = Settings(log_file=str(log_file), log_level="DEBUG")

            returned = configure_logging(settings, force=True)
            logging.getLogger("tests.config").debug("hello-log")

            self.assertEqual(returned, log_file)
            self.assertTrue(log_file.is_file())
            self.assertIn("hello-log", log_file.read_text(encoding="utf-8"))

    def test_configure_logging_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(log_file=str(Path(tmp) / "a.log"))
            first = configure_logging(settings, force=True)
            handlers_after_first = len(logging.getLogger().handlers)

            second = configure_logging(settings)

            self.assertEqual(first, second)
            self.assertEqual(len(logging.getLogger().handlers), handlers_after_first)

    def test_unwritable_log_file_degrades_to_console_only(self) -> None:
        settings = Settings(log_file="/proc/definitely-not-writable/mesa.log")
        returned = configure_logging(settings, force=True)
        self.assertIsNone(returned)
        self.assertTrue(logging.getLogger().handlers, "仍应有控制台 handler")

    def test_level_is_applied_to_root_logger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            configure_logging(
                Settings(log_file=str(Path(tmp) / "b.log"), log_level="WARNING"), force=True
            )
            self.assertEqual(logging.getLogger().level, logging.WARNING)


if __name__ == "__main__":
    unittest.main()

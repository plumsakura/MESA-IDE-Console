"""core.config 的界面字体偏好（纯数据，供 UI 层解析）。

对应"修改 UI 文字显示 bug"：偏好表本身是**可移植数据**，因此放在 core 并有
独立用例；Tk 侧"从偏好里挑出真实可用族"的逻辑在 ``tests/test_ui_fonts.py``。
"""

from __future__ import annotations

import unittest

from core.config import (
    DEFAULT_MONO_FONT_PREFERENCES,
    DEFAULT_UI_FONT_PREFERENCES,
    ENV_UI_FONT,
    Settings,
    load_settings,
    parse_font_preferences,
)


class ParseFontPreferences(unittest.TestCase):
    def test_blank_input_means_no_override(self) -> None:
        for value in (None, "", "   ", ",", " , ; , "):
            with self.subTest(value=value):
                self.assertEqual(parse_font_preferences(value), ())

    def test_comma_and_semicolon_separated(self) -> None:
        self.assertEqual(
            parse_font_preferences("Noto Sans CJK SC, WenQuanYi Micro Hei"),
            ("Noto Sans CJK SC", "WenQuanYi Micro Hei"),
        )
        self.assertEqual(parse_font_preferences("A;B"), ("A", "B"))

    def test_whitespace_and_quotes_are_stripped(self) -> None:
        self.assertEqual(
            parse_font_preferences("  'Noto Sans CJK SC' , \"YaHei\"  "),
            ("Noto Sans CJK SC", "YaHei"),
        )

    def test_empty_items_are_dropped(self) -> None:
        self.assertEqual(parse_font_preferences("A,,B,"), ("A", "B"))


class DefaultPreferences(unittest.TestCase):
    def test_bundled_ui_font_stays_first(self) -> None:
        """自带字体排第一：任何机器（含空白 WSL2）都能拿到有 CJK 的界面字体。"""
        self.assertEqual(DEFAULT_UI_FONT_PREFERENCES[0], "Noto Sans SC")

    def test_preferences_include_cjk_candidates(self) -> None:
        joined = " ".join(DEFAULT_UI_FONT_PREFERENCES)
        for expected in ("YaHei", "Noto Sans CJK", "WenQuanYi", "SimHei", "Droid Sans Fallback"):
            self.assertIn(expected, joined)

    def test_preferences_have_no_duplicates_or_blanks(self) -> None:
        for table in (DEFAULT_UI_FONT_PREFERENCES, DEFAULT_MONO_FONT_PREFERENCES):
            self.assertEqual(len(set(table)), len(table), "不得有重复项")
            self.assertTrue(all(item.strip() == item and item for item in table))

    def test_mono_table_keeps_bundled_cjk_mono_first(self) -> None:
        """编辑器等宽字体也以自带 Noto Sans Mono CJK SC 优先。"""
        self.assertEqual(DEFAULT_MONO_FONT_PREFERENCES[0], "Noto Sans Mono CJK SC")
        self.assertIn("monospace", DEFAULT_MONO_FONT_PREFERENCES)


class SettingsAndEnvOverride(unittest.TestCase):
    def test_defaults_expose_preferences(self) -> None:
        settings = Settings()
        self.assertEqual(settings.ui_font_preferences, DEFAULT_UI_FONT_PREFERENCES)
        self.assertEqual(settings.mono_font_preferences, DEFAULT_MONO_FONT_PREFERENCES)

    def test_env_override_replaces_ui_preferences(self) -> None:
        settings = load_settings(env={ENV_UI_FONT: "Noto Sans CJK SC, YaHei"})
        self.assertEqual(settings.ui_font_preferences, ("Noto Sans CJK SC", "YaHei"))

    def test_blank_env_keeps_defaults(self) -> None:
        settings = load_settings(env={ENV_UI_FONT: "   "})
        self.assertEqual(settings.ui_font_preferences, DEFAULT_UI_FONT_PREFERENCES)

    def test_other_settings_unaffected_by_font_env(self) -> None:
        settings = load_settings(env={ENV_UI_FONT: "YaHei", "MESA_IDE_VIDEO_FPS": "5"})
        self.assertEqual(settings.video_fps, 5)
        self.assertEqual(settings.log_level, "INFO")


if __name__ == "__main__":
    unittest.main()

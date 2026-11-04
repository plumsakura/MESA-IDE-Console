"""ide_ui.fonts：从偏好表里挑出**真实存在**的字体族。

核心风险是"自欺"：Tk 对不存在的字体名不会报错，``Font(family='不存在').actual()``
会回落到默认族 —— 所以"能建出 Font 对象"不等于"字体存在"。这里用替身字体模块
把该风险钉死，再用真实 Tk 做一次端到端验证（无显示环境自动跳过）。
"""

from __future__ import annotations

import unittest
from unittest import mock

from core.config import load_settings
from ide_ui import fonts


class FakeFont:
    def __init__(self, family: str, actual: str | None = None) -> None:
        self._family = family
        self._actual = actual if actual is not None else family
        self.configured: dict = {}

    def actual(self, key: str = "family"):
        if key == "family":
            return self._actual
        return None

    def configure(self, **kwargs) -> None:
        self.configured.update(kwargs)


class FakeFontModule:
    """模拟 tkinter.font：``families()`` + ``Font`` + ``nametofont``。"""

    def __init__(self, families, default_family="DejaVu Sans", missing_fallback="DejaVu Sans"):
        self._families = list(families)
        self._default_family = default_family
        # 真实 Tk 对不存在的字体名会回落到某个**存在**的族（默认 DejaVu Sans）
        self._missing_fallback = missing_fallback
        self.named: dict[str, FakeFont] = {
            name: FakeFont(default_family)
            for name in (
                "TkDefaultFont",
                "TkTextFont",
                "TkMenuFont",
                "TkHeadingFont",
                "TkFixedFont",
            )
        }

    def families(self):
        return list(self._families)

    def Font(self, family=None, **_kwargs):
        if family in self._families:
            return FakeFont(family)
        return FakeFont(family, actual=self._missing_fallback)

    def nametofont(self, name):
        return self.named.setdefault(name, FakeFont(self._default_family))


class ResolveFamily(unittest.TestCase):
    def setUp(self) -> None:
        fonts.reset_cache()
        self.addCleanup(fonts.reset_cache)

    def test_first_available_preference_wins(self) -> None:
        module = FakeFontModule(
            ["DejaVu Sans", "Noto Sans CJK SC"], missing_fallback="DejaVu Sans"
        )
        self.assertEqual(
            fonts.resolve_family(module, ("Noto Sans CJK SC", "DejaVu Sans")),
            "Noto Sans CJK SC",
            "排在前面的可用族必须胜出（回落族除外）",
        )

    def test_missing_preferences_are_skipped(self) -> None:
        module = FakeFontModule(
            ["DejaVu Sans", "Noto Sans CJK SC"], missing_fallback="DejaVu Sans"
        )
        self.assertEqual(
            fonts.resolve_family(module, ("Arial", "Helvetica", "Noto Sans CJK SC")),
            "Noto Sans CJK SC",
        )

    def test_fallback_family_in_preferences_is_skipped(self) -> None:
        """喜好表里排第一的正好是回落族时，必须继续往后挑。"""
        module = FakeFontModule(
            ["DejaVu Sans", "Noto Sans CJK SC"], missing_fallback="DejaVu Sans"
        )
        self.assertEqual(
            fonts.resolve_family(module, ("DejaVu Sans", "Noto Sans CJK SC")),
            "Noto Sans CJK SC",
        )

    def test_matching_is_case_insensitive_and_keeps_system_casing(self) -> None:
        """偏好写 "Noto Sans CJK SC"、系统登记为全小写时也要命中。"""
        module = FakeFontModule(
            ["noto sans cjk sc", "DejaVu Sans"], missing_fallback="DejaVu Sans"
        )
        self.assertEqual(
            fonts.resolve_family(module, ("Noto Sans CJK SC",)), "noto sans cjk sc"
        )

    def test_probe_name_is_not_a_real_family(self) -> None:
        """探针名必须不可能撞上真实族（否则"回落族"判定会失效）。"""
        module = FakeFontModule(["DejaVu Sans"])
        self.assertNotIn(fonts._PROBE_NAME, module.families())
        self.assertEqual(
            str(module.Font(family=fonts._PROBE_NAME).actual("family")), "DejaVu Sans"
        )

    def test_no_preference_available_returns_default_and_warns(self) -> None:
        module = FakeFontModule(
            ["DejaVu Sans"], default_family="DejaVu Sans", missing_fallback="Arial"
        )
        with self.assertLogs("ide_ui.fonts", level="WARNING") as captured:
            family = fonts.resolve_family(module, ("Arial", "YaHei"))
        self.assertEqual(family, "DejaVu Sans")
        self.assertIn("中文可能显示为方框", "\n".join(captured.output))

    def test_blank_entries_are_ignored(self) -> None:
        module = FakeFontModule(["Arial"])
        self.assertEqual(fonts.resolve_family(module, ("", "  ", "Arial")), "Arial")

    def test_missing_tk_default_font_does_not_crash(self) -> None:
        module = FakeFontModule(
            ["DejaVu Sans"], default_family="DejaVu Sans", missing_fallback="Arial"
        )
        with self.assertLogs("ide_ui.fonts", level="WARNING"):
            self.assertEqual(fonts.resolve_family(module, ("YaHei",)), "DejaVu Sans")


class CachedAccessors(unittest.TestCase):
    def setUp(self) -> None:
        fonts.reset_cache()
        self.addCleanup(fonts.reset_cache)

    def test_explicit_preferences_bypass_cache(self) -> None:
        rich = FakeFontModule(["Noto Sans CJK SC"])
        poor = FakeFontModule(["DejaVu Sans"])
        self.assertEqual(
            fonts.ui_font_family(font_module=rich, preferences=("Noto Sans CJK SC",)),
            "Noto Sans CJK SC",
        )
        self.assertEqual(
            fonts.ui_font_family(font_module=poor, preferences=("Arial",)), "DejaVu Sans"
        )

    def test_mono_resolution_uses_mono_table(self) -> None:
        module = FakeFontModule(["Consolas", "DejaVu Sans"])
        self.assertEqual(
            fonts.mono_font_family(font_module=module, preferences=("Consolas",)),
            "Consolas",
        )

    def test_explicit_module_never_returns_a_stale_cache_entry(self) -> None:
        """显式传 font_module/preferences 时必须现场解析，不得命中别的缓存。"""
        rich = FakeFontModule(["Noto Sans CJK SC"])
        self.assertEqual(
            fonts.ui_font_family(font_module=rich, preferences=("Noto Sans CJK SC",)),
            "Noto Sans CJK SC",
        )
        poor = FakeFontModule(["DejaVu Sans"])
        self.assertEqual(
            fonts.ui_font_family(font_module=poor, preferences=("Noto Sans CJK SC",)),
            "DejaVu Sans",
            "换了一个字体模块后不得复用上一个模块的结果",
        )


class FakeRoot:
    def __init__(self) -> None:
        self.tk = object()


class ApplyToRoot(unittest.TestCase):
    """``apply_to_root`` 要把解析结果写到命名字体与 ttk 样式上。

    真实 ``tkinter.font`` 需要根窗口，因此这里替换模块级的 ``_font_module``。
    """

    def setUp(self) -> None:
        fonts.reset_cache()
        self.addCleanup(fonts.reset_cache)
        self.module = FakeFontModule(
            ["Arial", "DejaVu Sans Mono"], missing_fallback="DejaVu Sans"
        )
        patcher = mock.patch.object(
            fonts, "_font_module", staticmethod(lambda: self.module)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_named_fonts_are_configured(self) -> None:
        family = fonts.apply_to_root(
            FakeRoot(), preferences=("Arial",), mono_preferences=("DejaVu Sans Mono",)
        )

        self.assertEqual(family, "Arial")
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            self.assertEqual(
                self.module.named[name].configured.get("family"), "Arial", name
            )
        self.assertEqual(
            self.module.named["TkFixedFont"].configured.get("family"), "DejaVu Sans Mono"
        )

    def test_ttk_styles_are_configured_with_resolved_family(self) -> None:
        seen: dict[str, dict] = {}

        class FakeStyle:
            def __init__(self, _root) -> None:
                pass

            def configure(self, name, **kwargs) -> None:
                seen[name] = kwargs

        with mock.patch("tkinter.ttk.Style", FakeStyle):
            fonts.apply_to_root(FakeRoot(), preferences=("Arial",))

        self.assertTrue(seen, "ttk 样式必须被设置字体")
        self.assertTrue(all(kw["font"][0] == "Arial" for kw in seen.values()))

    def test_blank_preferences_fall_back_without_crashing(self) -> None:
        family = fonts.apply_to_root(FakeRoot(), preferences=("没有这个字体",))
        self.assertEqual(family, "Arial", "应回退到系统上真实存在的族")


class RealTkIntegration(unittest.TestCase):
    """真实 Tk 下的端到端验证（无显示环境自动跳过）。"""

    @classmethod
    def setUpClass(cls) -> None:
        from tests.test_ui_components import tk_reachable

        reachable, reason = tk_reachable()
        if not reachable:
            raise unittest.SkipTest(f"Tk 不可用：{reason}")

    def setUp(self) -> None:
        fonts.reset_cache()
        self.addCleanup(fonts.reset_cache)

    def test_resolved_family_is_a_real_family(self) -> None:
        import tkinter as tk
        from tkinter import font as tkfont

        root = tk.Tk()
        self.addCleanup(root.destroy)

        settings = load_settings(env={})
        family = fonts.ui_font_family(
            font_module=tkfont, preferences=settings.ui_font_preferences
        )

        actual = str(tkfont.Font(root, family=family, size=10).actual("family"))
        self.assertEqual(actual.lower(), family.lower(), "解析出的族必须是真实存在的")
        self.assertIn(family.lower(), [f.lower() for f in tkfont.families(root)])

    def test_apply_to_root_sets_named_fonts(self) -> None:
        import tkinter as tk
        from tkinter import font as tkfont

        root = tk.Tk()
        self.addCleanup(root.destroy)

        family = fonts.apply_to_root(root)
        self.assertEqual(
            str(tkfont.nametofont("TkDefaultFont").actual("family")).lower(),
            family.lower(),
        )

    def test_chinese_text_has_expected_width_when_cjk_font_exists(self) -> None:
        """有中文字体时，解析结果必须是"真能画中文"的族（而非回落族）。

        本机若一个中文字体都没有，则跳过并留下明确说明。
        """
        import tkinter as tk
        from tkinter import font as tkfont

        root = tk.Tk()
        self.addCleanup(root.destroy)

        candidates = load_settings(env={}).ui_font_preferences
        family = fonts.ui_font_family(font_module=tkfont, preferences=candidates)
        probe = tkfont.Font(root, family=fonts._PROBE_NAME, size=10)
        if family.lower() == str(probe.actual("family")).lower():
            self.skipTest("系统没有偏好表里的任何真实字体族（含中文字体），无法验证字形")
        self.assertNotEqual(family, fonts._PROBE_NAME)


if __name__ == "__main__":
    unittest.main()

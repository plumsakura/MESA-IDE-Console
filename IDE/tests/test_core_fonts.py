"""core.fonts：自带中文字体 + 系统字体检测 + 安装计划（纯标准库）。

目标：**别人装完软件就能正常显示中文**，两条腿走路：

1. **自带字体（无需管理员权限）**：把仓库里的 Noto Sans SC 子集复制到
   用户字体目录，Linux 上刷新 fontconfig 缓存 —— 之后 Tk/matplotlib 都能用；
2. **系统字体包（需用户同意）**：检测不到任何中文字体时，按平台/包管理器
   给出安装计划（apt/dnf/pacman/brew），征得同意后用 argv 列表执行
   （绝不 shell=True、绝不静默 sudo）。
"""

from __future__ import annotations

import os
import pathlib
import sys
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from core.config import project_root
from core.fonts import (
    BUNDLED_FONT_FAMILY,
    BUNDLED_FONT_FILENAME,
    CJK_FONT_HINTS,
    FontInstallResult,
    FontPackagePlan,
    build_font_plan,
    bundled_font_source,
    detect_cjk_fonts,
    detect_package_manager,
    ensure_bundled_font,
    install_font_package,
    user_fonts_dir,
)


def fake_runner(exit_codes):
    """返回一个 runner：每次调用弹出队首退出码并记录 argv。"""
    calls: list[list[str]] = []
    codes = list(exit_codes)

    def runner(argv, **_kwargs):
        calls.append(list(argv))
        code = codes.pop(0) if codes else 0
        return mock.Mock(returncode=code)

    return runner, calls


class BundledFontAsset(unittest.TestCase):
    def test_asset_exists_and_is_a_real_font_file(self) -> None:
        source = bundled_font_source()
        self.assertTrue(source.is_file(), "自带字体资产缺失，无法离线显示中文")
        self.assertGreater(source.stat().st_size, 100_000, "字体文件异常地小")
        self.assertEqual(source.name, BUNDLED_FONT_FILENAME)
        # 许可证必须与字体放在一起（OFL 要求随字体分发版权声明）
        self.assertTrue((source.parent / "OFL.txt").is_file())

    def test_asset_lives_inside_project(self) -> None:
        root = project_root()
        self.assertTrue(
            str(bundled_font_source()).startswith(str(root)),
            "字体资产必须放在仓库内（可随软件分发）",
        )

    def test_custom_project_root_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fonts_dir = pathlib.Path(tmp) / "IDE" / "assets" / "fonts"
            fonts_dir.mkdir(parents=True)
            (fonts_dir / BUNDLED_FONT_FILENAME).write_bytes(b"x")
            self.assertEqual(
                bundled_font_source(pathlib.Path(tmp) / "IDE"),
                fonts_dir / BUNDLED_FONT_FILENAME,
            )


class UserFontsDir(unittest.TestCase):
    def test_linux_uses_xdg_data_home(self) -> None:
        home = pathlib.Path("/home/u")
        result = user_fonts_dir(
            platform_system="Linux", env={"XDG_DATA_HOME": "/data"}, home=home
        )
        self.assertEqual(result, pathlib.Path("/data/fonts"))

    def test_linux_falls_back_to_local_share(self) -> None:
        result = user_fonts_dir(
            platform_system="Linux", env={}, home=pathlib.Path("/home/u")
        )
        self.assertEqual(result, pathlib.Path("/home/u/.local/share/fonts"))

    def test_macos_uses_library_fonts(self) -> None:
        result = user_fonts_dir(
            platform_system="Darwin", env={}, home=pathlib.Path("/Users/u")
        )
        self.assertEqual(result, pathlib.Path("/Users/u/Library/Fonts"))

    def test_windows_uses_localappdata(self) -> None:
        local = pathlib.Path(r"C:\Users\u\AppData\Local")
        result = user_fonts_dir(
            platform_system="Windows",
            env={"LOCALAPPDATA": str(local)},
            home=pathlib.Path(r"C:\Users\u"),
        )
        self.assertEqual(result, local / "Microsoft" / "Windows" / "Fonts")

    def test_windows_without_localappdata_falls_back(self) -> None:
        home = pathlib.Path(r"C:\Users\u")
        result = user_fonts_dir(platform_system="Windows", env={}, home=home)
        self.assertEqual(result, home / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts")


class EnsureBundledFont(unittest.TestCase):
    def _call(self, *, env=None, home=None, platform_system="Linux",
              exit_codes=(0,), register=None):
        tmp = tempfile.mkdtemp(prefix="mesa-fonts-")
        self.addCleanup(shutil.rmtree, tmp, True)
        base = pathlib.Path(tmp)
        # bundled_font_source(project_root) 期望 <root>/assets/fonts/<font>
        source = base / "assets" / "fonts"
        source.mkdir(parents=True)
        (source / BUNDLED_FONT_FILENAME).write_bytes(b"font-bytes")
        target_home = base / "home"
        target_home.mkdir()
        runner, calls = fake_runner(exit_codes)
        result = ensure_bundled_font(
            project_root=base,
            platform_system=platform_system,
            env=env or {},
            home=home or target_home,
            runner=runner,
            register_windows=register,
        )
        return result, calls, target_home

    def test_copies_into_user_fonts_dir_and_refreshes_cache(self) -> None:
        result, calls, home = self._call()

        self.assertTrue(result.ok)
        self.assertTrue(result.copied)
        self.assertTrue(result.refreshed)
        self.assertEqual(result.family, BUNDLED_FONT_FAMILY)
        target = home / ".local/share/fonts" / BUNDLED_FONT_FILENAME
        self.assertTrue(target.is_file(), "字体必须复制到用户字体目录")
        self.assertEqual(target.read_bytes(), b"font-bytes")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:2], ["fc-cache", "-f"])
        self.assertIn(str(target.parent), calls[0])

    def test_second_call_is_idempotent_and_skips_cache_refresh(self) -> None:
        result1, _, home = self._call()
        self.assertTrue(result1.copied)
        result2, calls2, _ = self._call(env={"HOME": str(home)}, home=home)

        self.assertTrue(result2.ok)
        self.assertFalse(result2.copied, "文件已存在时不应重复复制")
        self.assertFalse(result2.refreshed)
        self.assertEqual(calls2, [])

    def test_missing_asset_reports_failure_instead_of_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            home = base / "home"
            home.mkdir()
            result = ensure_bundled_font(
                project_root=base, env={}, home=home, platform_system="Linux",
                runner=fake_runner(())[0],
            )

        self.assertFalse(result.ok)
        self.assertTrue(result.warnings)
        self.assertFalse(result.copied)

    def test_fc_cache_failure_warns_but_keeps_font_installed(self) -> None:
        result, calls, _ = self._call(exit_codes=(1,))

        self.assertTrue(result.copied)
        self.assertTrue(result.ok, "缓存刷新失败不应推翻已完成的字体复制")
        self.assertTrue(any("fc-cache" in warning for warning in result.warnings))
        self.assertEqual(len(calls), 1)

    def test_macos_copies_without_fc_cache(self) -> None:
        result, calls, home = self._call(platform_system="Darwin", exit_codes=())

        self.assertTrue(result.ok)
        self.assertEqual(calls, [], "macOS 不需要 fc-cache")
        self.assertTrue((home / "Library/Fonts" / BUNDLED_FONT_FILENAME).is_file())

    def test_windows_registers_in_hkcu(self) -> None:
        registered: list = []

        def register(target):
            registered.append(str(target))

        result, calls, home = self._call(
            platform_system="Windows", env={}, exit_codes=(), register=register
        )

        self.assertTrue(result.ok)
        self.assertEqual(calls, [], "Windows 不需要 fc-cache")
        self.assertEqual(len(registered), 1)
        self.assertTrue(registered[0].endswith(BUNDLED_FONT_FILENAME))
        self.assertTrue(
            any("Microsoft" in part for part in pathlib.Path(registered[0]).parts)
        )


class DetectCjkFonts(unittest.TestCase):
    def test_fc_list_output_is_parsed_deduplicated_and_hint_filtered(self) -> None:
        def runner(argv, **_kwargs):
            self.assertEqual(argv, ["fc-list", "--format=%{family}\n"])
            return mock.Mock(
                returncode=0,
                stdout=(
                    "Noto Sans CJK SC\n"
                    "WenQuanYi Micro Hei\n"
                    "Noto Sans CJK SC\n"
                    "DejaVu Sans\n"  # 无 CJK 提示词，必须被过滤掉
                ),
            )

        result = detect_cjk_fonts(fc_list_cmd="fc-list", runner=runner, which=lambda _n: "fc-list")

        self.assertEqual(result, ["Noto Sans CJK SC", "WenQuanYi Micro Hei"])

    def test_fc_list_missing_falls_back_to_scanning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "wqy-microhei.ttc").write_bytes(b"x")
            (root / "Ubuntu-Regular.ttf").write_bytes(b"x")
            nested = root / "sub"
            nested.mkdir()
            (nested / "NotoSansCJK-Regular.otf").write_bytes(b"x")

            result = detect_cjk_fonts(
                fc_list_cmd="fc-list", which=lambda _n: None, scan_roots=[str(root)]
            )

        self.assertEqual(result, ["NotoSansCJK-Regular.otf", "wqy-microhei.ttc"])

    def test_no_fonts_at_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = detect_cjk_fonts(
                fc_list_cmd="fc-list", which=lambda _n: None, scan_roots=[tmp]
            )
        self.assertEqual(result, [])

    def test_fc_list_error_falls_back_to_scanning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "wqy-zenhei.ttc").write_bytes(b"x")

            def runner(_argv, **_kwargs):
                return mock.Mock(returncode=1, stdout="", stderr="boom")

            result = detect_cjk_fonts(
                fc_list_cmd="fc-list", runner=runner,
                which=lambda _n: "fc-list", scan_roots=[str(root)],
            )

        self.assertEqual(result, ["wqy-zenhei.ttc"])


class PackagePlans(unittest.TestCase):
    def test_linux_apt_plan(self) -> None:
        plan = build_font_plan("Linux", "apt")
        self.assertIsInstance(plan, FontPackagePlan)
        self.assertEqual(plan.packages[0], "fonts-noto-cjk")
        self.assertEqual(plan.install_argv[:2], ("sudo", "apt-get"))
        self.assertIn("-y", plan.install_argv)
        self.assertTrue(plan.update_argv, "apt 安装前必须先 update")

    def test_linux_dnf_plan(self) -> None:
        plan = build_font_plan("Linux", "dnf")
        self.assertIn("google-noto-sans-cjk-fonts", plan.packages)
        self.assertEqual(plan.install_argv[:2], ("sudo", "dnf"))

    def test_linux_pacman_plan(self) -> None:
        plan = build_font_plan("Linux", "pacman")
        self.assertIn("noto-fonts-cjk", plan.packages)
        self.assertIn("--noconfirm", plan.install_argv)

    def test_macos_brew_plan_has_no_sudo(self) -> None:
        plan = build_font_plan("Darwin", "brew")
        self.assertEqual(plan.install_argv[0], "brew")
        self.assertNotIn("sudo", plan.install_argv)

    def test_windows_needs_no_package_plan(self) -> None:
        self.assertIsNone(build_font_plan("Windows", "apt"))
        self.assertIsNone(build_font_plan("Windows", None))

    def test_unknown_manager_means_no_plan(self) -> None:
        self.assertIsNone(build_font_plan("Linux", None))
        self.assertIsNone(build_font_plan("FreeBSD", "pkg"))


class DetectPackageManager(unittest.TestCase):
    def test_detection_order(self) -> None:
        def which(name):
            return "/usr/bin/apt-get" if name == "apt-get" else None

        self.assertEqual(detect_package_manager(which=which), "apt")

    def test_returns_none_when_nothing_found(self) -> None:
        self.assertIsNone(detect_package_manager(which=lambda _n: None))


class InstallFontPackage(unittest.TestCase):
    def test_success_on_first_candidate(self) -> None:
        plan = build_font_plan("Linux", "apt")
        runner, calls = fake_runner((0, 0))

        self.assertTrue(install_font_package(plan, runner=runner))

        # update 一次 + 第一个候选包安装成功即停
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][:3], ["sudo", "apt-get", "update"])
        self.assertEqual(calls[1][-1], plan.packages[0])

    def test_falls_back_to_second_candidate(self) -> None:
        plan = build_font_plan("Linux", "apt")
        runner, calls = fake_runner((0, 1, 0))

        self.assertTrue(install_font_package(plan, runner=runner))
        self.assertEqual(calls[2][-1], plan.packages[1])

    def test_all_candidates_fail(self) -> None:
        plan = build_font_plan("Linux", "apt")
        runner, calls = fake_runner((0, 1, 1))

        self.assertFalse(install_font_package(plan, runner=runner))
        self.assertEqual(len(calls), 1 + len(plan.packages))

    def test_runner_exception_is_treated_as_failure(self) -> None:
        plan = build_font_plan("Darwin", "brew")

        def broken(_argv, **_kwargs):
            raise OSError("brew 不存在")

        self.assertFalse(install_font_package(plan, runner=broken))


class SharedConstants(unittest.TestCase):
    def test_family_name_and_filename_agree(self) -> None:
        self.assertEqual(BUNDLED_FONT_FAMILY, "Noto Sans SC")
        self.assertIn("noto", BUNDLED_FONT_FILENAME.lower())

    def test_hints_cover_common_cjk_fonts(self) -> None:
        joined = " ".join(CJK_FONT_HINTS)
        for expected in ("wqy", "notosanscjk", "sourcehansans", "simhei", "msyh"):
            self.assertIn(expected, joined)


class RealFontconfigIntegration(unittest.TestCase):
    """真实验证：装进临时 XDG_DATA_HOME → fc-cache → fontconfig/Tk 看得见。

    这证明"别人装完软件就能显示中文"这条链路成立（无 X11 时只验证 fc-list）。
    """

    def test_fontconfig_sees_bundled_font_after_install(self) -> None:
        if shutil.which("fc-cache") is None or shutil.which("fc-list") is None:
            self.skipTest("fontconfig 未安装，无法做真实验证")

        with tempfile.TemporaryDirectory() as tmp:
            data_home = pathlib.Path(tmp) / "data"
            data_home.mkdir()

            result = ensure_bundled_font(
                env={"XDG_DATA_HOME": str(data_home)},
                home=pathlib.Path(tmp) / "home",
                platform_system="Linux",
            )

            self.assertTrue(result.ok)
            self.assertTrue(result.copied)
            self.assertTrue(result.refreshed)

            completed = subprocess.run(
                ["fc-list", "--format=%{family}\n"],
                capture_output=True, text=True, check=False,
                env={**os.environ, "XDG_DATA_HOME": str(data_home)},
            )
            families = completed.stdout.splitlines()
            self.assertIn(BUNDLED_FONT_FAMILY, families,
                          f"fc-list 应能看到自带字体，实际: {families}")

    def test_tk_sees_bundled_font_after_install(self) -> None:
        from tests.test_ui_components import tk_reachable

        reachable, reason = tk_reachable()
        if not reachable:
            self.skipTest(f"Tk 不可用：{reason}")
        if shutil.which("fc-cache") is None:
            self.skipTest("fontconfig 未安装")

        with tempfile.TemporaryDirectory() as tmp:
            data_home = pathlib.Path(tmp) / "data"
            data_home.mkdir()
            ensure_bundled_font(
                env={"XDG_DATA_HOME": str(data_home)},
                home=pathlib.Path(tmp) / "home",
                platform_system="Linux",
            )
            code = (
                "import tkinter as tk\n"
                "from tkinter import font as tkfont\n"
                "r = tk.Tk(); r.withdraw()\n"
                "print('OK' if any('noto sans sc' == f.lower() for f in tkfont.families(r)) else 'MISSING')\n"
            )
            completed = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True, check=False,
                env={**os.environ, "XDG_DATA_HOME": str(data_home)},
                timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "OK")


if __name__ == "__main__":
    unittest.main()

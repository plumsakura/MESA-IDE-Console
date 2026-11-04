"""CLI 入口点单元测试：`main.py` / `run_mesa.py` / `install.py` 的可测函数。

这些文件里的 ``main()`` 会创建 GUI 或改变进程 CWD，因此只测试其中的
纯函数与生成物；``run_mesa.main()`` / ``main.main()`` 属人工冒烟范围。
"""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import install
import main as main_module
import run_mesa
from core.config import APP_NAME, __version__
from core.env import MesaEnvironment


class MainPanelStatus(unittest.TestCase):
    def test_valid_environment_line(self) -> None:
        detected = MesaEnvironment(mesa_dir="/opt/mesa", source="env:MESA_DIR", is_valid=True)
        self.assertEqual(main_module.mesa_status_text(detected), "MESA: 可用（/opt/mesa）")

    def test_invalid_environment_line(self) -> None:
        detected = MesaEnvironment(
            mesa_dir="/opt/mesa", source="env:MESA_DIR", is_valid=False, missing=("star/defaults",)
        )
        self.assertEqual(main_module.mesa_status_text(detected), "MESA: 不可用（/opt/mesa）")

    def test_missing_environment_line(self) -> None:
        detected = MesaEnvironment(mesa_dir=None, source="not_found", is_valid=False)
        self.assertEqual(main_module.mesa_status_text(detected), "MESA: 未检测到")


class RunMesaHelpers(unittest.TestCase):
    def test_venv_python_paths(self) -> None:
        base = Path("/opt/ide")
        self.assertEqual(run_mesa.venv_python(base, "Linux"), Path("/opt/ide/venv/bin/python"))
        self.assertEqual(
            run_mesa.venv_python(base, "Windows"), Path("/opt/ide/venv/Scripts/python")
        )

    def test_report_environment_prints_summary_and_hint(self) -> None:
        buffer = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            for relative in ("star/defaults", "star/work", "star/test_suite"):
                (Path(tmp) / relative).mkdir(parents=True)
            with contextlib.redirect_stdout(buffer):
                ok = run_mesa.report_mesa_environment(env={"MESA_DIR": tmp})

        output = buffer.getvalue()
        self.assertTrue(ok)
        self.assertIn(tmp, output)
        self.assertIn("可用", output)

    def test_report_environment_gives_hint_when_missing(self) -> None:
        buffer = io.StringIO()
        with mock.patch("core.env._glob_candidates", return_value=[]), \
                contextlib.redirect_stdout(buffer):
            ok = run_mesa.report_mesa_environment(env={})

        output = buffer.getvalue()
        self.assertFalse(ok)
        self.assertIn("MESA_DIR", output)
        self.assertIn("不影响 IDE 启动", output)


class ArchiveDirOption(unittest.TestCase):
    """``--archives``：让安装器直接用 Windows 盘上的归档，不必先复制进家目录。"""

    def test_override_comes_first_and_defaults_are_kept(self) -> None:
        dirs = install.mesa_archive_dirs("/mnt/e/mesa")
        self.assertEqual(dirs[0], "/mnt/e/mesa")
        self.assertIn("~/mesa", dirs, "默认位置仍作为兜底")

    def test_tilde_is_expanded(self) -> None:
        self.assertEqual(install.mesa_archive_dirs("~/mesa2")[0], os.path.expanduser("~/mesa2"))

    def test_blank_override_keeps_defaults_only(self) -> None:
        self.assertEqual(install.mesa_archive_dirs("   "), install.mesa_archive_dirs(None))
        self.assertEqual(install.mesa_archive_dirs(None)[0], "~/mesa")

    def test_cli_parses_archives(self) -> None:
        options = install.parse_install_args(["--archives", "/mnt/e/mesa", "--yes"])
        self.assertEqual(options.archives, "/mnt/e/mesa")
        self.assertTrue(options.yes)


class InstallHelpers(unittest.TestCase):
    def test_python_version_check(self) -> None:
        self.assertFalse(install.check_python_version((3, 7, 9)))
        self.assertTrue(install.check_python_version((3, 8, 0)))
        self.assertTrue(install.check_python_version((3, 14, 4)))

    def test_venv_failure_hint_mentions_apt_on_linux(self) -> None:
        with mock.patch.object(install.platform, "system", return_value="Linux"):
            hint = install.venv_failure_hint((3, 14, 4))
        self.assertIn("apt install python3.14-venv", hint, "对应 problem.txt 记录的真实故障")

    def test_venv_failure_hint_generic_on_other_platforms(self) -> None:
        with mock.patch.object(install.platform, "system", return_value="Windows"):
            hint = install.venv_failure_hint((3, 14, 4))
        self.assertNotIn("apt install", hint)
        self.assertIn("venv", hint)

    def test_run_command_uses_argv_not_shell(self) -> None:
        ok, out, err = install.run_command(["/bin/bash", "-c", "echo hi"], capture_output=True)
        self.assertTrue(ok)
        self.assertEqual(out.strip(), "hi")
        self.assertEqual(err, "")

        # 若被当成 shell 字符串执行，这条就会成功；argv 形式必须失败
        ok, _out, err = install.run_command(["echo hi"], capture_output=True)
        self.assertFalse(ok)
        self.assertTrue(err)

    def test_run_command_reports_nonzero_exit(self) -> None:
        ok, _out, _err = install.run_command(["/bin/bash", "-c", "exit 4"])
        self.assertFalse(ok)

    def test_generated_launcher_is_self_locating(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with mock.patch.object(install.platform, "system", return_value="Linux"):
                script = install.create_launcher_scripts(base)

            content = script.read_text(encoding="utf-8")
            self.assertEqual(script.name, "run_mesa.sh")
            self.assertIn("$(dirname", content, "必须按脚本自身位置定位（P12）")
            self.assertNotIn("MESA-IDE", content.replace("MESA IDE", ""))
            self.assertIn("venv/bin/activate", content)
            self.assertTrue(script.stat().st_mode & 0o111, "启动脚本需可执行")

    def test_generated_windows_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(install.platform, "system", return_value="Windows"):
                script = install.create_launcher_scripts(Path(tmp))
            content = script.read_text(encoding="utf-8")
            self.assertEqual(script.name, "run_mesa.bat")
            self.assertIn('cd /d "%~dp0"', content)

    def test_banner_uses_single_version_source(self) -> None:
        """版本号只在 core.config 中声明（P22）。"""
        source = Path(install.__file__).read_text(encoding="utf-8")
        self.assertIn("from core.config import APP_NAME, __version__", source)
        self.assertNotIn(f'"{__version__}"', source, "安装器不得再硬编码版本号字符串")
        self.assertEqual(APP_NAME, "MESA Control Console")


class FontInstallConsent(unittest.TestCase):
    def _plan(self):
        from core.fonts import FontPackagePlan

        return FontPackagePlan(
            manager="apt",
            description="APT 安装中文字体包",
            packages=("fonts-noto-cjk",),
            install_argv=("sudo", "apt-get", "install", "-y"),
            update_argv=("sudo", "apt-get", "update"),
        )

    def test_non_interactive_defaults_to_no(self) -> None:
        def input_fn(_prompt):
            raise AssertionError("非交互环境不得提问")

        self.assertFalse(install.font_install_consent(self._plan(), interactive=False, input_fn=input_fn))

    def test_interactive_yes(self) -> None:
        self.assertTrue(
            install.font_install_consent(self._plan(), interactive=True, input_fn=lambda _p: "y")
        )
        self.assertTrue(
            install.font_install_consent(self._plan(), interactive=True, input_fn=lambda _p: "YES")
        )
        self.assertTrue(
            install.font_install_consent(self._plan(), interactive=True, input_fn=lambda _p: " 是 ")
        )

    def test_interactive_no(self) -> None:
        for answer in ("n", "no", "", "随便"):
            with self.subTest(answer=answer):
                self.assertFalse(
                    install.font_install_consent(
                        self._plan(), interactive=True, input_fn=lambda _p: answer
                    )
                )

    def test_env_override_wins_without_asking(self) -> None:
        def input_fn(_prompt):
            raise AssertionError("环境变量已给出决定，不得再提问")

        self.assertTrue(
            install.font_install_consent(
                self._plan(), interactive=True, input_fn=input_fn, env={"MESA_IDE_AGREE_FONT_INSTALL": "1"}
            )
        )
        self.assertFalse(
            install.font_install_consent(
                self._plan(), interactive=True, input_fn=input_fn, env={"MESA_IDE_AGREE_FONT_INSTALL": "0"}
            )
        )


class CheckUiFonts(unittest.TestCase):
    """安装器第 5 步：自带字体 → 系统检测 → 征得同意后装包。"""

    def _run(self, *, home, which=lambda _n: None, consent=None, input_fn=lambda _p: "n"):
        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            ok = install.check_ui_fonts(
                env={},
                home=home,
                runner=lambda argv, **_k: mock.Mock(returncode=0),
                which=which,
                interactive=True,
                input_fn=input_fn,
            )
        return ok, buffer.getvalue()

    def test_bundled_font_succeeds_without_any_package_manager(self) -> None:
        from core.fonts import user_fonts_dir

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            ok, output = self._run(home=home, which=lambda _n: None)

            self.assertTrue(ok)
            self.assertIn("自带中文字体", output)
            target = user_fonts_dir(platform_system="Linux", env={}, home=home)
            self.assertTrue((target / "NotoSansSC-Regular.otf").is_file())

    def test_system_cjk_fonts_suffice_when_asset_missing(self) -> None:
        import contextlib
        import io
        import core.fonts as font_support
        from unittest import mock as _mock

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with _mock.patch.object(
                font_support,
                "bundled_font_source",
                return_value=Path(tmp) / "missing.otf",
            ):
                buffer = io.StringIO()
                with contextlib.redirect_stdout(buffer):
                    ok = install.check_ui_fonts(
                        env={},
                        home=home,
                        runner=lambda argv, **_k: _mock.Mock(
                            returncode=0, stdout="WenQuanYi Micro Hei\n"
                        )
                        if argv == ["fc-list", "--format=%{family}\n"]
                        else _mock.Mock(returncode=0),
                        which=lambda n: "fc-list" if n == "fc-list" else None,
                        interactive=True,
                        input_fn=lambda _p: "n",
                    )
            output = buffer.getvalue()

        self.assertTrue(ok)
        self.assertIn("WenQuanYi Micro Hei", output)
        self.assertNotIn("fonts-noto-cjk", output, "已有中文字体时不得提议装包")

    def test_no_font_and_no_consent_skips_package(self) -> None:
        import contextlib
        import io
        from unittest import mock as _mock

        import core.fonts as font_support

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with _mock.patch.object(
                font_support,
                "bundled_font_source",
                return_value=Path(tmp) / "missing.otf",
            ), _mock.patch.object(
                install, "detect_cjk_fonts", return_value=[]
            ):
                buffer = io.StringIO()
                with contextlib.redirect_stdout(buffer):
                    ok = install.check_ui_fonts(
                        env={},
                        home=home,
                        runner=lambda argv, **_k: _mock.Mock(returncode=0),
                        which=lambda n: "apt-get" if n == "apt-get" else None,
                        interactive=True,
                        input_fn=lambda _p: "n",
                    )
            output = buffer.getvalue()

        self.assertFalse(ok)
        self.assertIn("已跳过", output)
        self.assertIn("fonts-noto-cjk", output, "应告知候选包名")

    def test_consent_installs_package(self) -> None:
        from unittest import mock as _mock

        import core.fonts as font_support

        calls: list[list[str]] = []
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with _mock.patch.object(
                font_support,
                "bundled_font_source",
                return_value=Path(tmp) / "missing.otf",
            ), _mock.patch.object(
                install, "detect_cjk_fonts", return_value=[]
            ):
                def runner(argv, **_kwargs):
                    calls.append(list(argv))
                    return _mock.Mock(returncode=0)

                ok = install.check_ui_fonts(
                    env={},
                    home=home,
                    runner=runner,
                    which=lambda n: "apt-get" if n == "apt-get" else None,
                    interactive=True,
                    input_fn=lambda _p: "y",
                )

        self.assertTrue(ok)
        self.assertTrue(any("sudo" in argv and "apt-get" in argv for argv in calls))
        self.assertTrue(
            any(argv[-1] == "fonts-noto-cjk" for argv in calls), "必须真的尝试安装候选包"
        )


class ShippedLauncherMatchesGenerator(unittest.TestCase):
    """仓库中已提交的 run_mesa.sh 必须与安装器生成的内容一致（避免再次漂移）。"""

    def test_committed_run_mesa_sh_matches_template(self) -> None:
        from core.config import project_root

        shipped = (project_root() / "run_mesa.sh").read_text(encoding="utf-8")
        self.assertEqual(shipped, install.RUN_SH_CONTENT)


if __name__ == "__main__":
    unittest.main()

"""install.py 的 MESA 安装/配置步骤（setup_mesa / 同意逻辑）。

用户要求"安装我的软件的过程要完成安装 MESA、配置 MESA"：
这里验证**计划、同意、解压、配置、编译、失败处理**的编排是否正确，
真实编译在长跑会话里单独验证（见开发文档）。
"""

from __future__ import annotations

import os
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

import install
from core.mesa_install import ENV_FILENAME_SH, RC_BEGIN


class MesaInstallConsent(unittest.TestCase):
    def _plan(self):
        from core.mesa_install import MesaArchive, MesaInstallPlan

        return MesaInstallPlan(
            mesa_dir="/home/u/mesa/mesa-24.08.1",
            sdk_root="/home/u/mesasdk",
            sdk_archive=MesaArchive("/home/u/mesa/mesasdk.tar.gz", "tar", "24.7.1"),
            mesa_archive=MesaArchive("/home/u/mesa/mesa-24.08.1.zip", "zip", "24.08.1"),
            needs_sdk_extract=True,
            needs_mesa_extract=True,
            needs_build=True,
            already_installed=False,
            description="需要解压",
        )

    def test_non_interactive_defaults_to_no(self) -> None:
        def input_fn(_prompt):
            raise AssertionError("非交互不得提问")

        self.assertFalse(
            install.mesa_install_consent(self._plan(), interactive=False, input_fn=input_fn)
        )

    def test_interactive_answers(self) -> None:
        for answer, expected in (("y", True), ("YES", True), (" 是 ", True), ("n", False), ("", False)):
            with self.subTest(answer=answer):
                self.assertEqual(
                    install.mesa_install_consent(
                        self._plan(), interactive=True, input_fn=lambda _p, a=answer: a
                    ),
                    expected,
                )

    def test_env_override_short_circuits(self) -> None:
        def input_fn(_prompt):
            raise AssertionError("环境变量已决定，不得提问")

        self.assertTrue(
            install.mesa_install_consent(
                self._plan(),
                interactive=True,
                input_fn=input_fn,
                env={"MESA_IDE_AGREE_MESA_INSTALL": "1"},
            )
        )
        self.assertFalse(
            install.mesa_install_consent(
                self._plan(),
                interactive=True,
                input_fn=input_fn,
                env={"MESA_IDE_AGREE_MESA_INSTALL": "0"},
            )
        )


class SetupMesa(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="mesa-setup-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = pathlib.Path(self.tmp)
        self.archives = self.base / "archives"
        self.archives.mkdir()
        self.project = self.base / "project"
        self.project.mkdir()
        self.rc = self.base / ".bashrc"
        self.sdk_root = self.base / "mesasdk"
        self.mesa_root = self.base / "mesa"
        self.mesa_dir = self.mesa_root / "mesa-24.08.1"
        # 环境隔离：不要让真实 MESA_DIR 影响判定
        self.env = mock.patch.dict(os.environ, {"MESA_DIR": ""}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

    def _call(self, **kwargs):
        params = {
            "env": {"MESA_DIR": ""},
            "archive_dirs": [str(self.archives)],
            "sdk_root": str(self.sdk_root),
            "mesa_root": str(self.mesa_root),
            "project_dir": str(self.project),
            "rc_path": str(self.rc),
            "interactive": False,
        }
        params.update(kwargs)
        return install.setup_mesa(**params)

    def _invalid(self):
        from core.env import MesaEnvironment

        return MesaEnvironment(mesa_dir=None, source="not_found", is_valid=False)

    def _valid(self):
        from core.env import MesaEnvironment

        return MesaEnvironment(
            mesa_dir=str(self.mesa_dir), source="env:MESA_DIR", is_valid=True
        )

    def _write_archives(self) -> None:
        (self.archives / "mesa-24.08.1.zip").write_bytes(b"x")
        (self.archives / "mesasdk-x86_64-linux-24.7.1.tar.gz").write_bytes(b"x")

    def test_no_archives_prints_download_hint_and_fails(self) -> None:
        import contextlib
        import io

        buffer = io.StringIO()
        with mock.patch("core.env._glob_candidates", return_value=[]), \
                contextlib.redirect_stdout(buffer):
            ok = self._call()

        self.assertFalse(ok)
        output = buffer.getvalue()
        self.assertIn("未找到 MESA 源码包", output)
        self.assertIn("mesastar", output, "必须给出官方下载指引")

    def test_consent_declined_does_nothing(self) -> None:
        import contextlib
        import io

        self._write_archives()
        runner = mock.Mock()
        buffer = io.StringIO()
        with mock.patch("core.env._glob_candidates", return_value=[]), \
                contextlib.redirect_stdout(buffer):
            ok = self._call(runner=runner, interactive=False)

        self.assertFalse(ok)
        self.assertIn("已跳过", buffer.getvalue())
        self.assertFalse(self.sdk_root.exists())
        runner.assert_not_called()

    def test_full_install_extracts_configures_and_builds(self) -> None:
        import contextlib
        import io

        self._write_archives()
        extracted: list[str] = []
        built: list[str] = []

        def fake_extract(archive, target_dir, **_kwargs):
            extracted.append(target_dir)
            # 模拟解压产物：MESA 源码目录里要有 install 脚本
            os.makedirs(target_dir, exist_ok=True)
            (pathlib.Path(target_dir) / "install").write_text("#!/bin/bash\n", encoding="utf-8")
            return True

        def fake_build(mesa_dir, sdk_root, **_kwargs):
            built.append(mesa_dir)
            # 模拟编译产物
            lib = pathlib.Path(mesa_dir) / "lib"
            lib.mkdir(parents=True, exist_ok=True)
            (lib / "libstar.a").write_bytes(b"x")
            return True

        with mock.patch.object(install, "extract_into_target", fake_extract), \
                mock.patch.object(install, "mesa_run_build", fake_build), \
                mock.patch.object(install, "detect_mesa") as detect:
            detect.side_effect = [self._invalid(), self._valid()]
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                ok = self._call(interactive=True, input_fn=lambda _p: "y")

        output = buffer.getvalue()
        self.assertTrue(ok, output)
        self.assertEqual(len(extracted), 2, "SDK 与源码都要解压")
        self.assertEqual(extracted[0], str(self.sdk_root), "先解压 SDK")
        self.assertEqual(extracted[1], str(self.mesa_dir), "源码解压到目标目录本身")
        self.assertEqual(built, [str(self.mesa_dir)])
        self.assertTrue((self.project / ENV_FILENAME_SH).is_file(), "必须生成 MESA 环境脚本")
        self.assertIn(RC_BEGIN, self.rc.read_text(encoding="utf-8"))
        self.assertIn("编译 MESA", output)

    def test_build_failure_reports_log_path(self) -> None:
        import contextlib
        import io

        self._write_archives()

        def fake_extract(archive, target_dir, **_kwargs):
            os.makedirs(target_dir, exist_ok=True)
            (pathlib.Path(target_dir) / "install").write_text("#!/bin/bash\n", encoding="utf-8")
            return True

        with mock.patch.object(install, "extract_into_target", fake_extract), \
                mock.patch.object(install, "mesa_run_build", return_value=False), \
                mock.patch("core.env._glob_candidates", return_value=[]):
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                ok = self._call(interactive=True, input_fn=lambda _p: "y")

        self.assertFalse(ok)
        self.assertIn("mesa_install.log", buffer.getvalue())

    def test_already_valid_only_configures(self) -> None:
        import contextlib
        import io

        # 已安装且已编译（lib/libstar.a 存在）+ SDK 就位：只做配置，绝不重新编译
        self.mesa_dir.mkdir(parents=True)
        (self.mesa_dir / "install").write_text("#!/bin/bash\n", encoding="utf-8")
        (self.mesa_dir / "lib").mkdir()
        (self.mesa_dir / "lib" / "libstar.a").write_bytes(b"x")
        (self.sdk_root / "bin").mkdir(parents=True)
        (self.sdk_root / "bin" / "gfortran").write_bytes(b"x")

        runner = mock.Mock()
        with mock.patch.object(install, "detect_mesa") as detect, \
                mock.patch.object(install, "mesa_run_build") as build:
            detect.return_value = self._valid()
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                ok = self._call(runner=runner)

        self.assertTrue(ok)
        build.assert_not_called()
        runner.assert_not_called()
        self.assertTrue((self.project / ENV_FILENAME_SH).is_file())
        self.assertIn(RC_BEGIN, self.rc.read_text(encoding="utf-8"))

    def test_valid_source_but_not_built_still_builds(self) -> None:
        """历史 bug：源码解压后（star/defaults 在）但未编译时，安装器误判
        "已安装"直接跳过编译。现在必须继续编译。"""
        import contextlib
        import io

        self._write_archives()
        # 模拟"MESA_DIR 有效、但没编译"的现场：源码在，libstar.a 不在
        self.mesa_dir.mkdir(parents=True)
        (self.mesa_dir / "install").write_text("#!/bin/bash\n", encoding="utf-8")
        (self.sdk_root / "bin").mkdir(parents=True)
        (self.sdk_root / "bin" / "gfortran").write_bytes(b"x")

        built: list[str] = []

        def fake_build(mesa_dir, sdk_root, **_kwargs):
            built.append(mesa_dir)
            lib = pathlib.Path(mesa_dir) / "lib"
            lib.mkdir(parents=True, exist_ok=True)
            (lib / "libstar.a").write_bytes(b"x")
            return True

        with mock.patch.object(install, "mesa_run_build", fake_build), \
                mock.patch.object(install, "detect_mesa") as detect, \
                mock.patch("core.env._glob_candidates", return_value=[]):
            detect.side_effect = [self._valid(), self._valid()]
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                ok = self._call(interactive=True, input_fn=lambda _p: "y")

        output = buffer.getvalue()
        self.assertTrue(ok, output)
        self.assertEqual(built, [str(self.mesa_dir)], "未编译的源码必须继续编译")
        self.assertIn("编译 MESA", output)

    def test_unwritable_target_prints_fix_command_instead_of_crashing(self) -> None:
        """~/mesa 属主是 root 的真实故障：必须打印 chown 修复命令并返回 False。"""
        import contextlib
        import io

        self._write_archives()

        def deny(_path, _mode):
            return False

        with mock.patch("core.env._glob_candidates", return_value=[]), \
                mock.patch.object(install, "extract_blockers", return_value=("目录不可写: /home/u/mesa",)), \
                mock.patch.object(install, "extract_into_target") as extract:
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                ok = self._call(interactive=True, input_fn=lambda _p: "y")

        output = buffer.getvalue()
        self.assertFalse(ok)
        self.assertIn("无法解压", output)
        self.assertIn("目录不可写", output)
        extract.assert_not_called()

    def test_env_override_allows_unattended_install(self) -> None:
        self._write_archives()

        def fake_extract(archive, target_dir, **_kwargs):
            os.makedirs(target_dir, exist_ok=True)
            (pathlib.Path(target_dir) / "install").write_text("#!/bin/bash\n", encoding="utf-8")
            return True

        with mock.patch.object(install, "extract_into_target", fake_extract), \
                mock.patch.object(install, "mesa_run_build", return_value=True), \
                mock.patch.object(install, "detect_mesa") as detect:
            detect.side_effect = [self._invalid(), self._valid()]
            ok = self._call(
                interactive=False, env={"MESA_DIR": "", "MESA_IDE_AGREE_MESA_INSTALL": "1"}
            )

        self.assertTrue(ok)


class LauncherSourcesMesaEnv(unittest.TestCase):
    def test_sh_template_sources_generated_env(self) -> None:
        self.assertIn("mesa_env.sh", install.RUN_SH_CONTENT)
        self.assertIn('source "$SCRIPT_DIR/mesa_env.sh"', install.RUN_SH_CONTENT)

    def test_bat_template_sources_generated_env(self) -> None:
        self.assertIn("mesa_env.bat", install.RUN_BAT_CONTENT)


if __name__ == "__main__":
    unittest.main()

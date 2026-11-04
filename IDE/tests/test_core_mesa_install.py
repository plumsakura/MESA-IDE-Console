"""core.mesa_install：MESA 的安装与配置（纯标准库、全部副作用可注入）。

对应用户要求"安装我的软件的过程要完成安装 MESA、配置 MESA"：

- 发现本机已下载的 MESA 源码包与 SDK 包（不打网络下载，避免依赖外网）；
- 解压 SDK、解压源码、以 SDK 的编译器构建 MESA（``./install``）；
- 把 ``MESASDK_ROOT`` / ``MESA_DIR`` / ``PATH`` 写进**生成的 env 脚本**
  （供启动器 source）并可选写入 ``~/.bashrc`` 的标记块（幂等、保留用户内容）。

真实构建很慢，因此本层把"要不要做/怎么做"与"真的执行"分开，执行一律经
注入的 ``runner``，测试里零副作用。
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from core.mesa_install import (
    BUILD_MARKER,
    DEFAULT_MESA_ROOT,
    DEFAULT_SDK_ROOT,
    ENV_FILENAME_BAT,
    ENV_FILENAME_SH,
    RC_BEGIN,
    RC_END,
    MesaArchive,
    MesaInstallPlan,
    build_env,
    env_lines,
    extract_argv,
    extract_blockers,
    extract_into_target,
    find_archive,
    mesa_dir_for,
    nested_install_sources,
    parse_version,
    plan_mesa_install,
    repair_nested_installs,
    run_build,
    run_extract,
    update_shell_rc,
    write_env_file,
)


def fake_runner(codes=(0,)):
    calls: list[dict] = []
    queue = list(codes)

    def runner(argv, **kwargs):
        calls.append({"argv": list(argv), **kwargs})
        code = queue.pop(0) if queue else 0
        return mock.Mock(returncode=code)

    return runner, calls


class ParseVersion(unittest.TestCase):
    def test_mesa_zip(self) -> None:
        self.assertEqual(parse_version("mesa-24.08.1.zip"), "24.08.1")

    def test_sdk_tarball(self) -> None:
        self.assertEqual(parse_version("mesasdk-x86_64-linux-24.7.1.tar.gz"), "24.7.1")

    def test_no_version_returns_none(self) -> None:
        self.assertIsNone(parse_version("mesa.zip"))
        self.assertIsNone(parse_version("archive.tar.gz"))


class FindArchive(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="mesa-arch-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = pathlib.Path(self.tmp)

    def test_finds_zip_and_reports_kind(self) -> None:
        (self.base / "mesa-24.08.1.zip").write_bytes(b"x")
        found = find_archive([str(self.base)], ("mesa-*.zip",))
        self.assertEqual(found.kind, "zip")
        self.assertEqual(found.version, "24.08.1")
        self.assertTrue(found.path.endswith("mesa-24.08.1.zip"))

    def test_finds_tarball(self) -> None:
        (self.base / "mesasdk-x86_64-linux-24.7.1.tar.gz").write_bytes(b"x")
        found = find_archive([str(self.base)], ("mesasdk-*.tar.gz",))
        self.assertEqual(found.kind, "tar")

    def test_nothing_found(self) -> None:
        self.assertIsNone(find_archive([str(self.base)], ("mesa-*.zip",)))

    def test_expands_user_and_ignores_missing_dirs(self) -> None:
        self.assertIsNone(find_archive(["~/definitely-not-here"], ("mesa-*.zip",)))

    def test_prefers_first_directory_in_order(self) -> None:
        other = self.base / "other"
        other.mkdir()
        (other / "mesa-24.08.1.zip").write_bytes(b"x")
        (self.base / "mesa-23.01.1.zip").write_bytes(b"x")

        found = find_archive([str(self.base), str(other)], ("mesa-*.zip",))

        self.assertEqual(found.version, "23.01.1", "按目录顺序优先，而不是全部里挑最新")


class MesaDirFor(unittest.TestCase):
    def test_uses_archive_version(self) -> None:
        archive = MesaArchive(path="/tmp/mesa-24.08.1.zip", kind="zip", version="24.08.1")
        self.assertEqual(
            mesa_dir_for("/home/u/mesa", archive), "/home/u/mesa/mesa-24.08.1"
        )

    def test_falls_back_to_plain_name(self) -> None:
        self.assertEqual(
            mesa_dir_for("/home/u/mesa", MesaArchive(path="/tmp/mesa.zip", kind="zip", version=None)),
            "/home/u/mesa/mesa",
        )

    def test_expands_user(self) -> None:
        result = mesa_dir_for("~/mesa", None)
        self.assertTrue(result.startswith(os.path.expanduser("~/mesa")))


class PlanMesaInstall(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="mesa-plan-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = pathlib.Path(self.tmp)
        self.archives = self.base / "archives"
        self.archives.mkdir()
        self.mesa_root = self.base / "mesa"
        self.sdk_root = self.base / "mesasdk"

    def _plan(self):
        return plan_mesa_install(
            archive_dirs=[str(self.archives)],
            sdk_root=str(self.sdk_root),
            mesa_root=str(self.mesa_root),
        )

    def test_no_archives_no_installation(self) -> None:
        plan = self._plan()
        self.assertFalse(plan.already_installed)
        self.assertIsNone(plan.sdk_archive)
        self.assertIsNone(plan.mesa_archive)
        self.assertFalse(plan.needs_sdk_extract)
        self.assertFalse(plan.needs_mesa_extract)
        self.assertFalse(plan.needs_build)
        self.assertIn("未找到", plan.description)

    def test_archives_present_need_everything(self) -> None:
        (self.archives / "mesa-24.08.1.zip").write_bytes(b"x")
        (self.archives / "mesasdk-x86_64-linux-24.7.1.tar.gz").write_bytes(b"x")

        plan = self._plan()

        self.assertTrue(plan.needs_sdk_extract)
        self.assertTrue(plan.needs_mesa_extract)
        self.assertTrue(plan.needs_build)
        self.assertFalse(plan.already_installed)
        self.assertEqual(plan.mesa_dir, str(self.mesa_root / "mesa-24.08.1"))
        self.assertIn("解压", plan.description)

    def test_extracted_but_not_built(self) -> None:
        (self.archives / "mesa-24.08.1.zip").write_bytes(b"x")
        (self.archives / "mesasdk-x86_64-linux-24.7.1.tar.gz").write_bytes(b"x")
        mesa_dir = self.mesa_root / "mesa-24.08.1"
        mesa_dir.mkdir(parents=True)
        (mesa_dir / "install").write_text("#!/bin/bash\n", encoding="utf-8")
        (self.sdk_root / "bin").mkdir(parents=True)
        (self.sdk_root / "bin" / "gfortran").write_bytes(b"x")

        plan = self._plan()

        self.assertFalse(plan.needs_sdk_extract)
        self.assertFalse(plan.needs_mesa_extract)
        self.assertTrue(plan.needs_build)
        self.assertIn("编译", plan.description)

    def test_fully_installed(self) -> None:
        (self.archives / "mesa-24.08.1.zip").write_bytes(b"x")
        mesa_dir = self.mesa_root / "mesa-24.08.1"
        (mesa_dir / BUILD_MARKER).parent.mkdir(parents=True)
        (mesa_dir / BUILD_MARKER).write_bytes(b"x")
        (self.sdk_root / "bin").mkdir(parents=True)
        (self.sdk_root / "bin" / "gfortran").write_bytes(b"x")

        plan = self._plan()

        self.assertTrue(plan.already_installed)
        self.assertFalse(plan.needs_build)
        self.assertIn("已安装", plan.description)


class ExtractCommands(unittest.TestCase):
    def test_zip_uses_unzip_with_overwrite(self) -> None:
        argv = extract_argv(MesaArchive("/a/mesa-24.08.1.zip", "zip", "24.08.1"), "/dest")
        self.assertEqual(argv[0], "unzip")
        self.assertIn("-o", argv)
        self.assertEqual(argv[-2:], ["-d", "/dest"])
        self.assertIn("/a/mesa-24.08.1.zip", argv)

    def test_tar_uses_tar_with_target(self) -> None:
        argv = extract_argv(MesaArchive("/a/sdk.tar.gz", "tar", None), "/dest")
        self.assertEqual(argv[0], "tar")
        self.assertIn("/a/sdk.tar.gz", argv)
        self.assertEqual(argv[-2:], ["-C", "/dest"])

    def test_run_extract_reports_failure(self) -> None:
        runner, calls = fake_runner((2,))
        self.assertFalse(run_extract(["unzip", "x"], runner=runner))
        self.assertEqual(len(calls), 1)

    def test_run_extract_success(self) -> None:
        runner, calls = fake_runner((0,))
        self.assertTrue(run_extract(["tar", "-xzf", "a", "-C", "b"], runner=runner))
        self.assertEqual(calls[0]["argv"][0], "tar")


class ExtractIntoTarget(unittest.TestCase):
    """extract_into_target：修复"带顶层目录的归档解压成双重嵌套"的 bug。"""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="mesa-extract-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = pathlib.Path(self.tmp)

    def _runner_with_tree(self, tree: dict[str, bytes]):
        """构造 runner：把 tree（相对路径 → 内容）写进解压目标目录。"""
        def runner(argv, **kwargs):
            destination = argv[-1]
            for relative, content in tree.items():
                path = pathlib.Path(destination) / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            return mock.Mock(returncode=0)
        return runner

    def test_single_top_level_dir_is_promoted(self) -> None:
        # 归档里只有一个顶层目录 mesa-24.08.1/（真实 MESA zip 的结构）
        runner = self._runner_with_tree(
            {
                "mesa-24.08.1/install": b"#!/bin/bash\n",
                "mesa-24.08.1/star/defaults/controls.defaults": b"x",
            }
        )
        target = self.base / "mesa" / "mesa-24.08.1"
        archive = MesaArchive("/arch/mesa-24.08.1.zip", "zip", "24.08.1")

        ok = extract_into_target(archive, str(target), runner=runner)

        self.assertTrue(ok)
        self.assertTrue((target / "install").is_file(), "install 必须在目标目录顶层")
        self.assertTrue((target / "star" / "defaults").is_dir())
        self.assertFalse((target / "mesa-24.08.1").exists(), "不得出现双重嵌套")

    def test_flat_archive_lands_directly(self) -> None:
        runner = self._runner_with_tree({"install": b"x", "star/defaults/a": b"y"})
        target = self.base / "mesa" / "mesa"
        ok = extract_into_target(MesaArchive("/arch/mesa.zip", "zip", None), str(target), runner=runner)
        self.assertTrue(ok)
        self.assertTrue((target / "install").is_file())

    def test_existing_target_is_backed_up_and_replaced(self) -> None:
        runner = self._runner_with_tree({"mesa-24.08.1/install": b"x"})
        target = self.base / "mesa" / "mesa-24.08.1"
        target.mkdir(parents=True)
        (target / "old.txt").write_text("old", encoding="utf-8")

        ok = extract_into_target(MesaArchive("/arch/mesa-24.08.1.zip", "zip", "24.08.1"), str(target), runner=runner)

        self.assertTrue(ok)
        self.assertTrue((target / "install").is_file())
        self.assertFalse((target / "old.txt").exists(), "旧内容应被替换")
        self.assertFalse(pathlib.Path(str(target) + ".mesa-ide-bak").exists(), "备份应清理")

    def test_extract_failure_keeps_existing_target(self) -> None:
        def failing_runner(argv, **kwargs):
            return mock.Mock(returncode=1)

        target = self.base / "mesa" / "mesa-24.08.1"
        target.mkdir(parents=True)
        (target / "keep.txt").write_text("keep", encoding="utf-8")

        ok = extract_into_target(
            MesaArchive("/arch/mesa-24.08.1.zip", "zip", "24.08.1"),
            str(target),
            runner=failing_runner,
        )
        self.assertFalse(ok)
        self.assertTrue((target / "keep.txt").is_file(), "解压失败不得破坏已有目录")


class ExtractBlockers(unittest.TestCase):
    """解压前预检：目录不可写 / 归档不可读要能被提前发现。"""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="mesa-blockers-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = pathlib.Path(self.tmp)
        self.archive = MesaArchive(str(self.base / "mesa-24.08.1.zip"), "zip", "24.08.1")
        self.archive_path = pathlib.Path(self.archive.path)
        self.archive_path.write_bytes(b"x")

    def test_writable_target_has_no_blockers(self) -> None:
        self.assertEqual(extract_blockers(self.archive, str(self.base / "mesa" / "mesa-24.08.1")), ())

    def test_unwritable_parent_is_reported_with_fix_command(self) -> None:
        def deny(_path, _mode):
            return False

        reasons = extract_blockers(
            self.archive, str(self.base / "mesa" / "mesa-24.08.1"), access=deny
        )
        self.assertTrue(any("目录不可写" in r for r in reasons), reasons)
        self.assertTrue(any("chown -R" in r for r in reasons), "必须给出可复制的修复命令")

    def test_unreadable_archive_is_reported(self) -> None:
        def deny(_path, mode):
            return mode != os.R_OK

        reasons = extract_blockers(self.archive, str(self.base), access=deny)
        self.assertTrue(any("归档不可读" in r for r in reasons), reasons)

    def test_permission_error_returns_false_instead_of_raising(self) -> None:
        """真实故障：~/mesa 属主是 root 时 mkdtemp 抛 PermissionError —— 必须转成 False。"""
        def deny_makedirs(*_a, **_k):
            raise PermissionError(13, "Permission denied")

        ok = extract_into_target(
            self.archive,
            str(self.base / "mesa" / "mesa-24.08.1"),
            runner=lambda *_a, **_k: mock.Mock(returncode=0),
            makedirs=deny_makedirs,
        )
        self.assertFalse(ok)


class RepairNestedInstalls(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="mesa-repair-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = pathlib.Path(self.tmp)

    def test_repairs_double_nested_mesa_and_sdk(self) -> None:
        mesa_dir = self.base / "mesa" / "mesa-24.08.1"
        nested = mesa_dir / "mesa-24.08.1"
        nested.mkdir(parents=True)
        (nested / "install").write_text("x", encoding="utf-8")
        sdk_root = self.base / "mesasdk"
        (sdk_root / "mesasdk" / "bin").mkdir(parents=True)
        (sdk_root / "mesasdk" / "bin" / "gfortran").write_bytes(b"x")

        mesa_source, sdk_source = nested_install_sources(str(mesa_dir), str(sdk_root))
        self.assertEqual(mesa_source, str(nested))
        self.assertEqual(sdk_source, str(sdk_root / "mesasdk"))

        ok, messages = repair_nested_installs(
            str(mesa_dir), str(sdk_root),
            repair_mesa_from=mesa_source, repair_sdk_from=sdk_source,
        )
        self.assertTrue(ok, messages)
        self.assertTrue((mesa_dir / "install").is_file(), "嵌套源码目录应被提升")
        self.assertTrue((sdk_root / "bin" / "gfortran").is_file(), "嵌套 SDK 应被提升")
        self.assertFalse((mesa_dir / "mesa-24.08.1").exists())

    def test_plan_detects_repair_needed(self) -> None:
        archives = self.base / "archives"
        archives.mkdir()
        (archives / "mesa-24.08.1.zip").write_bytes(b"x")
        mesa_dir = self.base / "mesa" / "mesa-24.08.1"
        (mesa_dir / "mesa-24.08.1").mkdir(parents=True)
        (mesa_dir / "mesa-24.08.1" / "install").write_text("x", encoding="utf-8")

        plan = plan_mesa_install(
            archive_dirs=[str(archives)],
            sdk_root=str(self.base / "mesasdk"),
            mesa_root=str(self.base / "mesa"),
        )
        self.assertTrue(plan.needs_repair)
        self.assertEqual(plan.repair_mesa_from, str(mesa_dir / "mesa-24.08.1"))
        self.assertFalse(plan.needs_mesa_extract, "可修复时不需要重新解压")
        self.assertIn("嵌套", plan.description)

    def test_extra_files_block_repair(self) -> None:
        mesa_dir = self.base / "mesa" / "mesa-24.08.1"
        (mesa_dir / "mesa-24.08.1").mkdir(parents=True)
        (mesa_dir / "mesa-24.08.1" / "install").write_text("x", encoding="utf-8")
        (mesa_dir / "stray.txt").write_text("user file", encoding="utf-8")

        ok, messages = repair_nested_installs(
            str(mesa_dir), str(self.base / "mesasdk"),
            repair_mesa_from=str(mesa_dir / "mesa-24.08.1"),
        )
        self.assertFalse(ok)
        self.assertIn("不止嵌套目录", messages[0])
        self.assertTrue((mesa_dir / "stray.txt").is_file(), "用户文件不能被删除")


class BuildEnvironment(unittest.TestCase):
    def test_env_has_sdk_path_and_mesa_dir(self) -> None:
        env = build_env("/opt/mesa/mesa-24.08.1", "/opt/mesasdk", base_env={"HOME": "/home/u"})

        self.assertEqual(env["MESA_DIR"], "/opt/mesa/mesa-24.08.1")
        self.assertEqual(env["MESASDK_ROOT"], "/opt/mesasdk")
        self.assertTrue(env["PATH"].startswith("/opt/mesasdk/bin" + os.pathsep))
        self.assertEqual(env["HOME"], "/home/u", "必须保留原有环境变量")

    def test_nprocs_and_threads_are_configurable(self) -> None:
        env = build_env("/m", "/s", nprocs=6)
        self.assertEqual(env["NPROCS"], "6")
        self.assertIn("OMP_NUM_THREADS", env)

    def test_env_lines_for_posix(self) -> None:
        lines = env_lines("/opt/mesa/mesa-24.08.1", "/opt/mesasdk", platform_system="Linux")
        text = "\n".join(lines)
        self.assertIn('export MESA_DIR="/opt/mesa/mesa-24.08.1"', text)
        self.assertIn('export MESASDK_ROOT="/opt/mesasdk"', text)
        self.assertIn('export PATH="$MESASDK_ROOT/bin:$PATH"', text)

    def test_env_lines_for_windows(self) -> None:
        lines = env_lines(r"C:\mesa\mesa-24.08.1", r"C:\mesasdk", platform_system="Windows")
        text = "\n".join(lines)
        self.assertIn("set MESA_DIR=", text)
        self.assertIn("set MESASDK_ROOT=", text)


class EnvFileAndShellRc(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="mesa-env-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = pathlib.Path(self.tmp)

    def test_write_env_file_posix(self) -> None:
        path = write_env_file(
            str(self.base), "/opt/mesa/mesa-24.08.1", "/opt/mesasdk", platform_system="Linux"
        )
        self.assertEqual(os.path.basename(path), ENV_FILENAME_SH)
        text = pathlib.Path(path).read_text(encoding="utf-8")
        self.assertIn("MESA_DIR", text)
        self.assertTrue(os.access(path, os.X_OK), "env 脚本应可执行（便于 source）")

    def test_write_env_file_windows(self) -> None:
        path = write_env_file(
            str(self.base), r"C:\mesa", r"C:\sdk", platform_system="Windows"
        )
        self.assertEqual(os.path.basename(path), ENV_FILENAME_BAT)
        self.assertIn("set MESA_DIR=", pathlib.Path(path).read_text(encoding="utf-8"))

    def test_write_env_file_is_idempotent(self) -> None:
        first = write_env_file(str(self.base), "/m", "/s")
        second = write_env_file(str(self.base), "/m", "/s")
        self.assertEqual(first, second)

    def test_shell_rc_block_is_added_once(self) -> None:
        rc = self.base / ".bashrc"
        rc.write_text("# 用户自己的配置\nalias ll='ls -l'\n", encoding="utf-8")

        changed = update_shell_rc(str(rc), "/opt/mesa/mesa-24.08.1", "/opt/mesasdk")
        self.assertTrue(changed)
        text = rc.read_text(encoding="utf-8")
        self.assertIn("# 用户自己的配置", text, "必须保留用户原有内容")
        self.assertIn(RC_BEGIN, text)
        self.assertIn(RC_END, text)

        self.assertFalse(update_shell_rc(str(rc), "/opt/mesa/mesa-24.08.1", "/opt/mesasdk"))
        self.assertEqual(rc.read_text(encoding="utf-8").count(RC_BEGIN), 1)

    def test_shell_rc_block_is_replaced_when_paths_change(self) -> None:
        rc = self.base / ".bashrc"
        rc.write_text("", encoding="utf-8")
        update_shell_rc(str(rc), "/old/mesa", "/old/sdk")
        update_shell_rc(str(rc), "/new/mesa", "/new/sdk")

        text = rc.read_text(encoding="utf-8")
        self.assertEqual(text.count(RC_BEGIN), 1)
        self.assertIn("/new/mesa", text)
        self.assertNotIn("/old/mesa", text)

    def test_shell_rc_is_created_when_missing(self) -> None:
        rc = self.base / ".bashrc"
        self.assertTrue(update_shell_rc(str(rc), "/m", "/s"))
        self.assertTrue(rc.is_file())


class RunBuild(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="mesa-build-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = pathlib.Path(self.tmp)
        self.mesa_dir = self.base / "mesa"
        self.mesa_dir.mkdir()
        (self.mesa_dir / "install").write_text("#!/bin/bash\n", encoding="utf-8")

    def test_runs_install_script_with_env_and_log(self) -> None:
        runner, calls = fake_runner((0,))
        log = self.base / "build.log"

        ok = run_build(
            str(self.mesa_dir), "/opt/mesasdk", runner=runner, log_path=str(log), nprocs=4
        )

        self.assertTrue(ok)
        self.assertEqual(calls[0]["argv"], ["./install"])
        self.assertEqual(os.path.realpath(calls[0]["cwd"]), os.path.realpath(self.mesa_dir))
        self.assertEqual(calls[0]["env"]["NPROCS"], "4")
        self.assertEqual(calls[0]["env"]["MESA_DIR"], str(self.mesa_dir))
        self.assertTrue(log.is_file(), "构建输出必须落盘，便于排查失败")

    def test_failure_is_reported_not_raised(self) -> None:
        runner, _ = fake_runner((1,))
        self.assertFalse(run_build(str(self.mesa_dir), "/opt/mesasdk", runner=runner))

    def test_runner_exception_is_reported(self) -> None:
        def broken(*_a, **_k):
            raise OSError("没有 install 脚本")

        self.assertFalse(run_build(str(self.mesa_dir), "/opt/mesasdk", runner=broken))

    def test_keyboard_interrupt_is_reported_not_raised(self) -> None:
        """Ctrl-C 中断编译：返回 False + 友好日志，而不是把堆栈抛给用户。"""
        def interrupted(*_a, **_k):
            raise KeyboardInterrupt()

        with self.assertLogs("core.mesa_install", level="INFO") as captured:
            self.assertFalse(run_build(str(self.mesa_dir), "/opt/mesasdk", runner=interrupted))
        self.assertTrue(
            any("中断" in line for line in captured.output),
            "日志必须说明是用户中断、可重新运行继续",
        )

    def test_missing_install_script_fails_fast(self) -> None:
        empty = self.base / "empty"
        empty.mkdir()
        runner, calls = fake_runner((0,))

        self.assertFalse(run_build(str(empty), "/opt/mesasdk", runner=runner))
        self.assertEqual(calls, [], "没有 install 脚本时不应真的执行")


class DefaultsSanity(unittest.TestCase):
    def test_default_paths(self) -> None:
        self.assertEqual(DEFAULT_SDK_ROOT, "~/mesasdk")
        self.assertEqual(DEFAULT_MESA_ROOT, "~/mesa")
        self.assertTrue(BUILD_MARKER.endswith("libstar.a"))


if __name__ == "__main__":
    unittest.main()

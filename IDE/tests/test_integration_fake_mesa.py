"""假 MESA 项目集成测试：协议层（真实 bash 执行）+ LOGS 数据抽取。

这是**端到端**测试，但**不依赖真实 MESA**：夹具（``tests/fixtures/``）
含 ``inlist``/``mk``/``rn``/``re``/``clean`` 与样例 ``LOGS/history.data``、
``profiles.index``、``profile*.data``，格式复刻 MESA 24.08.1 的真实输出
（依据见 ``tests/fixtures/make_fake_project.py`` 顶部说明）。

覆盖：
1. 夹具自身完整性（协议文件齐全、可执行位、MESA 格式表头）；
2. ``core.mesa.commands`` 构造的命令在真实 bash 下**真的能跑通**
   （``./mk`` → 生成 ``./star``；``./rn`` → 追加模型；``./re`` 快照名是位置
   参数；``./clean`` 清理且保留 LOGS/）；
3. ``core.mesa.reader`` 对样例 LOGS 的数据抽取（HR 图 / Rho-T 剖面）；
4. ``mesa_plotter`` 的读取接线（用替身 viewer 断言它吃的是同一份数据）。
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from core.mesa import (
    ACTION_BUILD,
    ACTION_CLEAN,
    ACTION_RESTART,
    ACTION_RUN,
    ACTION_RUN_ALL,
    build_bash_c_command,
    build_shell_command,
)
from core.mesa.reader import (
    HISTORY_FILENAME,
    MesaLogDir,
    MesaLogError,
    ProfileIndex,
    log_scale,
    parse_table,
    read_history,
    read_index,
)
from tests.helpers import PROJECT_ROOT, SafeDialogTestCase
from tests.fixtures.make_fake_project import FIXTURE_NAME

FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / FIXTURE_NAME

#: 该夹具的初始规模（见 make_fake_project）
INITIAL_MODELS = 40
INITIAL_PROFILES = 3


def _run_bash(command: str, *, cwd: str, artifacts: str, env: dict | None = None):
    """在受控环境里真实执行一条协议命令。"""
    merged = dict(os.environ)
    merged.update(
        {
            "MESA_STUB_ARTIFACTS": artifacts,
            "FAKE_PYTHON": sys.executable,
            "LC_ALL": "C",
        }
    )
    if env:
        merged.update(env)
    return subprocess.run(
        ["bash", "-c", command],
        cwd=cwd,
        env=merged,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _import_optional(name: str):
    """导入可选第三方依赖；缺失时让用例优雅跳过（而不是报错）。"""
    import importlib

    try:
        return importlib.import_module(name)
    except ImportError as exc:  # pragma: no cover - 取决于环境
        raise unittest.SkipTest(f"缺少可选依赖 {name}: {exc}")


def _require_tk() -> None:
    """绘图接线用例需要 Tk 可用（matplotlib 画布建在 Tk 上）。

    与仓库内既有的 Tk 用例一致：headless 环境下优雅跳过而不是失败
    （探测逻辑复用 ``tests/test_ui_components.py::tk_reachable``，
    它带超时子进程探测，不会挂起）。
    """
    from tests.test_ui_components import tk_reachable

    reachable, reason = tk_reachable()
    if not reachable:
        raise unittest.SkipTest(f"Tk 不可用：{reason}")


class FakeProjectTestCase(unittest.TestCase):
    """每个用例都在夹具的**临时副本**上跑，绝不动仓库里的模板。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = pathlib.Path(self.tmp.name) / FIXTURE_NAME
        shutil.copytree(FIXTURE_ROOT, self.project)
        # 保留可执行位（copytree 会保留，这里显式保证）
        for name in ("mk", "rn", "re", "clean"):
            os.chmod(self.project / name, 0o755)
        self.artifacts = pathlib.Path(self.tmp.name) / "artifacts"
        self.artifacts.mkdir()
        self.logs = self.project / "LOGS"

    # ---------- 共用断言 ----------

    def invocations(self) -> list[str]:
        path = self.artifacts / "invocations.log"
        if not path.exists():
            return []
        return [line for line in path.read_text(encoding="utf-8").splitlines() if line]

    def run_action(self, action: str, snapshot: str | None = None, **env):
        command = build_shell_command(str(self.project), action, snapshot)
        return _run_bash(
            command, cwd=str(self.project), artifacts=str(self.artifacts), env=env
        )

    def history_models(self) -> int:
        table = parse_table((self.logs / HISTORY_FILENAME).read_text(encoding="utf-8"))
        return len(table.column("model_number"))


class FixtureIntegrity(FakeProjectTestCase):
    """夹具必须是"像真的一样"的 MESA 工作目录，否则测试没有意义。"""

    def test_protocol_scripts_exist_and_are_executable(self) -> None:
        for name in ("mk", "rn", "re", "clean"):
            path = self.project / name
            self.assertTrue(path.is_file(), f"{name} 缺失")
            self.assertTrue(os.access(path, os.X_OK), f"{name} 没有可执行位")

    def test_core_inlists_exist(self) -> None:
        for name in ("inlist", "inlist_project", "inlist_pgstar"):
            self.assertTrue((self.project / name).is_file(), f"{name} 缺失")

    def test_logs_files_exist(self) -> None:
        self.assertTrue((self.logs / HISTORY_FILENAME).is_file())
        self.assertTrue((self.logs / "profiles.index").is_file())
        for number in range(1, INITIAL_PROFILES + 1):
            self.assertTrue((self.logs / f"profile{number}.data").is_file())

    def test_real_inlist_is_namelist_shaped(self) -> None:
        """真实 MESA 的 inlist 由 ``&group ... /`` 块组成，且首文件转发到 project。"""
        text = (self.project / "inlist").read_text(encoding="utf-8")
        for group in ("star_job", "controls", "pgstar"):
            self.assertIn(f"&{group}", text)
        self.assertIn("extra_star_job_inlist_name(1) = 'inlist_project'", text)
        self.assertIn("extra_pgstar_inlist_name(1) = 'inlist_pgstar'", text)

    def test_history_layout_matches_real_mesa(self) -> None:
        """真实布局（用真实运行样本核对过）：单帧表头 + 数据列序号行。

        MESA 在 ``history.f90`` 里写三帧，但 pass 3 以 ``status='replace'``
        重开文件，最终只有一帧 —— 见 ``tests/fixtures/real_mesa/README.md``。
        """
        lines = (self.logs / HISTORY_FILENAME).read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0].split()[:3], ["1", "2", "3"])
        self.assertIn("version_number", lines[1].split())
        self.assertEqual(len(lines[1].split()), len(lines[2].split()), "名字行与值行等长")
        self.assertEqual(lines[3], "", "第 4 行必须是空行")
        self.assertEqual(lines[4].split()[:3], ["1", "2", "3"])
        self.assertEqual(lines[5].split()[:2], ["model_number", "star_age"])

    def test_numeric_columns_use_mesa_e_exponents(self) -> None:
        """``star_history_dbl_format = '(1pes40.16e3, 1x)'`` → **E** 指数。

        实测真实 MESA 输出是 ``1.0000000000000001E-005`` 这种 E 指数。
        """
        line = (self.logs / HISTORY_FILENAME).read_text(encoding="utf-8").splitlines()[6]
        tokens = line.split()
        self.assertEqual(tokens[0], "10")
        self.assertIn("E+00", tokens[1])
        self.assertTrue(tokens[1].startswith("0.0000000000000000E"))

    def test_profiles_index_has_prose_header_then_rows(self) -> None:
        """真实 profiles.index 首行是说明文字，其后每行三列整数。"""
        lines = (self.logs / "profiles.index").read_text(encoding="utf-8").splitlines()
        self.assertIn("models.", lines[0])
        self.assertNotEqual(len(lines[0].split()), 3)
        self.assertEqual(len(lines), INITIAL_PROFILES + 1)
        for line in lines[1:]:
            self.assertEqual(len(line.split()), 3)


class ProtocolExecutionAgainstFakeProject(FakeProjectTestCase):
    """协议层关键字面量在真实 bash 下必须真的跑通。"""

    def test_mk_builds_star_via_make(self) -> None:
        """真实 ``./mk`` 是 ``cd make; make`` —— 桩脚本必须保留该语义。"""
        completed = self.run_action(ACTION_BUILD)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(self.invocations(), ["mk"])
        self.assertTrue(os.access(self.project / "star", os.X_OK), "mk 未编译出 ./star")

    def test_rn_requires_mk_first_and_appends_model_data(self) -> None:
        completed = self.run_action(ACTION_RUN)

        self.assertNotEqual(completed.returncode, 0, "未编译就 ./rn 应当失败")
        self.assertIn("./star 不存在", completed.stderr)
        self.assertEqual(self.invocations(), ["rn"], "失败的 rn 仍应留下调用记录")

        self.assertEqual(self.run_action(ACTION_BUILD).returncode, 0)
        completed = self.run_action(ACTION_RUN)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(self.invocations(), ["rn", "mk", "rn"])
        # ./rn 语义之一：删除 restart_photo
        self.assertFalse((self.project / "restart_photo").exists())
        # 追加了一个模型与一份剖面
        self.assertEqual(self.history_models(), INITIAL_MODELS + 1)
        self.assertTrue((self.logs / f"profile{INITIAL_PROFILES + 1}.data").is_file())
        index = read_index(str(self.logs / "profiles.index"))
        self.assertEqual(len(index.profile_numbers), INITIAL_PROFILES + 1)

    def test_run_all_builds_then_runs_in_order(self) -> None:
        completed = self.run_action(ACTION_RUN_ALL)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(self.invocations(), ["mk", "rn"])
        self.assertEqual(self.history_models(), INITIAL_MODELS + 1)

    def test_mk_failure_stops_chain(self) -> None:
        """``&&`` 语义：mk 失败时 rn 不得执行（MESA_STUB_FAIL 制造失败）。"""
        completed = self.run_action(ACTION_RUN_ALL, MESA_STUB_FAIL="mk")

        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(self.invocations(), ["mk"])
        self.assertFalse((self.project / "star").exists())

    def test_restart_uses_most_recent_photo_without_argument(self) -> None:
        completed = self.run_action(ACTION_RESTART)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(self.invocations(), ["re"])
        self.assertIn("restart from photo1", completed.stdout)
        self.assertTrue((self.project / "restart_photo").is_file())

    def test_restart_snapshot_name_arrives_as_positional_argument(self) -> None:
        """N4 回归：快照名是 ``./re`` 的位置参数，不是另一条命令。"""
        shutil.copy2(self.project / "photos" / "photo1", self.project / "photos" / "photo2")
        completed = self.run_action(ACTION_RESTART, "photo2")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(self.invocations(), ["re photo2"])
        self.assertIn("restart from photo2", completed.stdout)

    def test_restart_with_missing_snapshot_fails(self) -> None:
        completed = self.run_action(ACTION_RESTART, "does_not_exist")

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("does not exist", completed.stderr)

    def test_clean_keeps_logs_and_removes_build_output(self) -> None:
        self.assertEqual(self.run_action(ACTION_BUILD).returncode, 0)
        self.assertTrue((self.project / "star").exists())

        completed = _run_bash(
            " ".join(build_bash_c_command(str(self.project))),
            cwd=str(self.project),
            artifacts=str(self.artifacts),
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(self.invocations(), ["mk", "clean"])
        self.assertFalse((self.project / "star").exists(), "clean 未清理构建产物")
        self.assertTrue((self.logs / HISTORY_FILENAME).is_file(), "clean 不得删除 LOGS/")


class PlotDataExtraction(FakeProjectTestCase):
    """``core.mesa.reader`` 对样例 LOGS 的抽取（HR 图与 Rho-T 剖面所需列）。"""

    def test_history_exposes_hr_diagram_columns(self) -> None:
        history = read_history(str(self.logs))

        for column in ("model_number", "star_age", "log_Teff", "log_L", "log_R"):
            self.assertEqual(len(history.column(column)), INITIAL_MODELS)

        # 属性式取列是绘图代码的用法
        self.assertIsInstance(history.log_Teff[0], float)
        self.assertLess(history.log_Teff[-1], history.log_Teff[0], "红巨星阶段应更冷")
        self.assertGreater(history.log_L[-1], history.log_L[0], "亮度应增长")
        # 表头（真实 MESA 会写 version_number 等）
        self.assertEqual(history.header_value("version_number"), "''")
        self.assertEqual(history.model_number, INITIAL_MODELS * 10)

    def test_missing_column_raises_mesa_log_error(self) -> None:
        history = read_history(str(self.logs))
        with self.assertRaises(MesaLogError):
            history.column("log_Teff_typo")
        with self.assertRaises(AttributeError):
            history.no_such_column  # noqa: B018 - 属性式取列必须抛 AttributeError

    def test_mesa_log_dir_reads_profiles_and_index(self) -> None:
        logs = MesaLogDir(str(self.logs))

        self.assertEqual(logs.profile_numbers, (1, 2, 3))
        self.assertEqual(logs.model_numbers, (10, 20, 30))
        self.assertEqual(logs.profile_with_model_number(20), 2)
        self.assertEqual(logs.profile_data().model_number, 30, "默认取最后一个剖面")

        profile = logs.profile_data(profile_number=1)
        self.assertEqual(profile.model_number, 10)
        self.assertEqual(int(profile.header_value("num_zones")), 61)
        zone_count = len(profile.logRho)
        for column in ("zone", "mass", "logR", "logT", "logRho", "logP"):
            self.assertEqual(len(profile.column(column)), zone_count, column)
        # 真实 MESA 只写 log*；线性 Rho/T 由 reader 按需求值（与 mesa_reader 一致）
        self.assertNotIn("Rho", profile.columns)
        self.assertTrue(all(value > 0 for value in profile.Rho))
        self.assertTrue(all(value > 0 for value in profile.T))
        self.assertGreater(profile.T[0], profile.T[-1], "中心应比表面热")
        self.assertGreater(profile.Rho[0], profile.Rho[-1], "中心应比表面密")
        for value, logged in zip(profile.T[:5], profile.logT[:5]):
            self.assertAlmostEqual(value, 10.0 ** logged, places=6)
        for value, logged in zip(profile.Rho[:5], profile.logRho[:5]):
            self.assertAlmostEqual(value, 10.0 ** logged, places=6)

    def test_profile_memoized_and_by_model_number(self) -> None:
        logs = MesaLogDir(str(self.logs))

        first = logs.profile_data(model_number=10)
        self.assertIs(logs.profile_data(profile_number=1), first, "同一剖面应记忆化")
        with self.assertRaises(MesaLogError):
            logs.profile_data(model_number=999)

    def test_log_scale_matches_log_columns(self) -> None:
        logs = MesaLogDir(str(self.logs))
        profile = logs.profile_data(profile_number=2)

        self.assertAlmostEqual(log_scale(profile.T)[0], profile.logT[0], places=6)
        self.assertAlmostEqual(log_scale(profile.Rho)[3], profile.logRho[3], places=6)
        scaled = log_scale((0.0, -1.0, 10.0))
        self.assertTrue(all(value != value for value in scaled[:2]), "非正值应为 nan")
        self.assertEqual(scaled[2], 1.0)

    def test_index_parser_rejects_junk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "profiles.index"
            path.write_text("1 2\n", encoding="utf-8")
            with self.assertRaises(MesaLogError):
                read_index(str(path))
            path.write_text("", encoding="utf-8")
            with self.assertRaises(MesaLogError):
                read_index(str(path))

    def test_reader_errors_are_typed(self) -> None:
        with self.assertRaises(MesaLogError):
            MesaLogDir(str(self.project / "does_not_exist"))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(MesaLogError):
                MesaLogDir(tmp)  # 缺 history.data
            self.assertEqual(
                ProfileIndex((10, 20), (0, 0), (1, 2)).profile_with_model_number(20), 2
            )

    def test_numeric_equivalence_with_real_mesa_reader(self) -> None:
        """与真实 ``mesa_reader`` 数值对照（夹具已是真实布局，无需任何转换）。

        说明（更正早前记录）：早期夹具用"三帧表头 + D 指数"，导致误判
        mesa_reader 读不了真实 MESA 输出；真实文件是"单帧表头 + E 指数"，
        mesa_reader 0.4.0 完全可用（见 ``tests/test_core_reader_real_data.py``
        与 ``tests/fixtures/real_mesa/``）。
        """
        mesa_reader = _import_optional("mesa_reader")
        logs = MesaLogDir(str(self.logs))

        history = mesa_reader.MesaData(str(self.logs / HISTORY_FILENAME))
        ours = read_history(str(self.logs))
        self.assertEqual(tuple(ours.columns), tuple(history.bulk_names))
        for column in ("model_number", "log_Teff", "log_L"):
            self.assertEqual(
                [round(value, 9) for value in ours.column(column)],
                [round(float(value), 9) for value in history.data(column)],
                column,
            )

        reference = mesa_reader.MesaData(str(self.logs / "profile1.data"))
        profile = logs.profile_data(profile_number=1)
        self.assertEqual(profile.model_number, int(reference.model_number))
        for column in ("logRho", "logT", "logP", "Rho", "T"):
            theirs = (
                [float(value) for value in reference.data(column)]
                if column.startswith("log")
                else [float(value) for value in getattr(reference, column)]
            )
            for ours_value, their_value in zip(profile.column(column), theirs):
                # 大数量级（如 T~2e6）用相对容差，避免把浮点末位噪声当不一致
                self.assertAlmostEqual(
                    ours_value,
                    their_value,
                    delta=max(abs(their_value) * 1e-12, 1e-12),
                    msg=f"列 {column} 与 mesa_reader 不一致",
                )


class PlotterWiring(SafeDialogTestCase, FakeProjectTestCase):
    """``mesa_plotter`` 必须读同一份 LOGS 数据（用替身 viewer，不开真实窗口）。

    ``SafeDialogTestCase`` 把 messagebox 全部替换为记录型替身，因此绘图失败
    路径不会弹出真实模态框（那会永久阻塞）。
    """

    def test_plotter_reads_fixture_history_and_profile(self) -> None:
        _require_tk()
        from unittest import mock

        plotter = _import_optional("mesa_plotter")
        calls: list[tuple[str, object]] = []

        class FakeViewer:
            def __init__(self, title, figure):
                calls.append((title, figure))

        with mock.patch.object(plotter, "MesaPlotViewer", FakeViewer):
            plotter.plot_hr_diagram(str(self.project))
            plotter.plot_rho_t_profile(str(self.project))

        self.assert_no_dialogs()
        self.assertEqual(len(calls), 2, "两个绘图入口都应画出图并交给查看器")
        self.assertIn("HR", calls[0][0])
        self.assertIn("内部结构", calls[1][0])
        for _title, figure in calls:
            self.assertGreaterEqual(len(figure.axes), 1)
            figure.clear()

    def test_plotter_reports_missing_history_without_raising(self) -> None:
        _require_tk()
        plotter = _import_optional("mesa_plotter")

        plotter.plot_hr_diagram(str(self.project / "does_not_exist"))

        self.assertEqual([kind for kind, _a, _k in self.dialog_calls], ["showwarning"])

    def test_plotter_reports_corrupt_logs_without_raising(self) -> None:
        _require_tk()
        plotter = _import_optional("mesa_plotter")
        logs = self.logs
        shutil.rmtree(logs)

        plotter.plot_rho_t_profile(str(self.project))

        self.assertEqual([kind for kind, _a, _k in self.dialog_calls], ["showerror"])


if __name__ == "__main__":
    unittest.main()

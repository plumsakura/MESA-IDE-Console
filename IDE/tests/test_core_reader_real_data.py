"""用**真实 MESA 输出样本**锁定 LOGS 解析（回归夹具见 tests/fixtures/real_mesa/）。

背景：项目早期的假 MESA 夹具是"三帧表头"的合成近似，而真实 MESA 在 pass 3 会
重开并重写文件，最终只有**一帧**表头 + 一段"序号行/列名行"；`profiles.index`
首行还是说明文字。真实运行把这三处差异全暴露了出来，因此这里用原样文件钉死。
"""

from __future__ import annotations

import math
import unittest

from core.mesa.reader import (
    MesaLogDir,
    MesaLogError,
    parse_table,
    read_history,
    read_index,
)
from tests.helpers import PROJECT_ROOT

REAL_DIR = PROJECT_ROOT / "tests" / "fixtures" / "real_mesa"


class RealHistoryData(unittest.TestCase):
    def setUp(self) -> None:
        self.path = REAL_DIR / "history.data"

    def test_sample_exists_and_looks_real(self) -> None:
        self.assertTrue(self.path.is_file(), "缺少真实样本夹具")
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("version_number", text)
        self.assertTrue(text.splitlines()[0].split()[:3] == ["1", "2", "3"])

    def test_header_has_single_frame(self) -> None:
        """真实文件只有一帧表头：序号行/名字行/值行 + 空行。"""
        lines = self.path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0].split()[:3], ["1", "2", "3"])
        self.assertIn("version_number", lines[1].split())
        self.assertEqual(lines[3], "", "第 4 行必须是空行")
        self.assertIn("model_number", lines[5].split(), "第 6 行是数据列名行")

    def test_parse_header_and_columns(self) -> None:
        table = parse_table(self.path.read_text(encoding="utf-8"))

        self.assertEqual(table.header_value("version_number"), '"r24.08.1"')
        self.assertEqual(table.header_value("compiler"), '"gfortran"')
        self.assertIn("model_number", table.columns)
        self.assertIn("star_age", table.columns)
        self.assertIn("log_Teff", table.columns)
        self.assertIn("log_L", table.columns)

    def test_parse_values_match_the_real_rows(self) -> None:
        table = read_history(str(REAL_DIR))

        self.assertEqual(
            [int(value) for value in table.column("model_number")], [1, 5, 10, 15, 20]
        )
        self.assertEqual(int(table.column("num_zones")[0]), 701)
        self.assertAlmostEqual(table.column("star_age")[0], 1.0e-5, places=12)
        # 真实 1 M☉ 前主序开端：Teff/L 都在 4382 K / 1.08 L☉ 附近（不做单调性假设，
        # 真实曲线在该阶段是平的甚至微降）
        self.assertTrue(all(3.5 < value < 3.8 for value in table.log_Teff))
        self.assertTrue(all(abs(value) < 0.2 for value in table.log_L))
        # log_L 与 10**log_L 自洽（真实值 ~1.08 L☉）
        self.assertAlmostEqual(table.column("log_L")[0], math.log10(10.0 ** table.column("log_L")[0]), places=12)

    def test_history_has_many_columns_like_real_mesa(self) -> None:
        table = read_history(str(REAL_DIR))
        self.assertGreater(len(table.columns), 40, "真实 history 列数远多于几十")

    def test_model_number_property_uses_last_row(self) -> None:
        self.assertEqual(read_history(str(REAL_DIR)).model_number, 20)


class RealProfileAndIndex(unittest.TestCase):
    def test_profiles_index_skips_leading_prose_line(self) -> None:
        index = read_index(str(REAL_DIR / "profiles.index"))

        self.assertEqual(index.model_numbers, (1, 20))
        self.assertEqual(index.profile_numbers, (1, 2))
        self.assertEqual(index.priorities, (2, 3))
        self.assertEqual(index.profile_with_model_number(20), 2)

    def test_profile_header_and_columns(self) -> None:
        """真实 profile：``version_number`` 在**表头**，数据列是 logRho/logT 等。"""
        table = parse_table((REAL_DIR / "profile2.data").read_text(encoding="utf-8"))

        self.assertEqual(table.header_value("version_number"), '"r24.08.1"')
        self.assertEqual(int(table.header_value("num_zones")), 700)
        self.assertEqual(table.model_number, 20)
        self.assertEqual(
            tuple(table.columns),
            ("zone", "mass", "logR", "logT", "logRho", "logP",
             "x_mass_fraction_H", "y_mass_fraction_He", "z_mass_fraction_metals",
             "pp", "cno", "tri_alpha"),
        )
        with self.assertRaises(MesaLogError):
            table.column("definitely_missing")

    def test_derived_linear_columns_match_mesa_reader_behaviour(self) -> None:
        """MESA 只写 logRho/logT，绘图要 Rho/T —— 与 mesa_reader 一样按需求值。"""
        table = parse_table((REAL_DIR / "profile2.data").read_text(encoding="utf-8"))

        self.assertAlmostEqual(table.Rho[0], 10.0 ** table.logRho[0], places=12)
        self.assertAlmostEqual(table.T[0], 10.0 ** table.logT[0], places=12)
        self.assertGreater(table.T[0], 4000.0)  # 表面温度量级
        self.assertEqual(table.column("Rho"), table.Rho)
        # 反向：log_<X> ← X
        self.assertAlmostEqual(table.log_Rho[0], table.logRho[0], places=12)
        # 取对数对非正值给 nan 而不是抛异常
        self.assertNotEqual(table._safe_log10((0.0,))[0], table._safe_log10((0.0,))[0])

    def test_mesa_log_dir_reads_real_sample(self) -> None:
        logs = MesaLogDir(str(REAL_DIR))

        self.assertEqual(logs.profile_numbers, (1, 2))
        self.assertEqual(logs.model_numbers, (1, 20))
        profile = logs.profile_data()  # 默认最后一个剖面（模型 20）
        self.assertEqual(profile.model_number, 20)
        # MESA 的 zone 1 是**表面**；样本被截断到前 5 个区，故只能断言"向内变热变密"
        self.assertGreater(profile.T[-1], profile.T[0])
        self.assertGreater(profile.Rho[-1], profile.Rho[0])
        self.assertEqual(profile.zone[0], 1.0)

    def test_plot_ready_columns_exist_on_real_profile(self) -> None:
        """绘图（HR 图/剖面图）实际用到的列必须在真实样本里存在且为正数。"""
        profile = MesaLogDir(str(REAL_DIR)).profile_data()
        zones = len(profile.Rho)

        for column in ("Rho", "T", "logRho", "logT"):
            self.assertEqual(len(profile.column(column)), zones, column)
        self.assertTrue(all(value > 0 for value in profile.Rho))
        self.assertTrue(all(value > 0 for value in profile.T))

    def test_mesa_reader_agrees_on_real_history(self) -> None:
        """与真实 mesa_reader 交叉核对（**更正早前记录**）。

        早前基于"三帧表头 + D 指数"的**合成夹具**，曾误判 mesa_reader 读不了真实
        MESA 输出；用真实样本实测：mesa_reader 0.4.0 **能**正常解析
        （真实文件是单帧表头 + E 指数）。这里锁定"两套读取器结果一致"。
        """
        try:
            import mesa_reader
        except ImportError:  # pragma: no cover
            self.skipTest("环境里没有 mesa_reader")

        ours = read_history(str(REAL_DIR))
        theirs = mesa_reader.MesaData(str(REAL_DIR / "history.data"))

        self.assertEqual(
            [int(value) for value in ours.column("model_number")],
            [int(value) for value in theirs.data("model_number")],
        )
        self.assertEqual(tuple(ours.columns), tuple(theirs.bulk_names))
        for column in ("log_Teff", "log_L", "star_age"):
            self.assertEqual(
                [round(value, 9) for value in ours.column(column)],
                [round(float(value), 9) for value in theirs.data(column)],
                column,
            )
        self.assertEqual(ours.header_value("version_number").strip('"'),
                         str(theirs.header("version_number")))

    def test_mesa_reader_agrees_on_real_profile(self) -> None:
        try:
            import mesa_reader
        except ImportError:  # pragma: no cover
            self.skipTest("环境里没有 mesa_reader")

        ours = MesaLogDir(str(REAL_DIR)).profile_data()
        theirs = mesa_reader.MesaData(str(REAL_DIR / "profile2.data"))

        self.assertEqual(ours.model_number, int(theirs.model_number))
        for column in ("zone", "mass", "logRho", "logT", "logP", "pp"):
            self.assertEqual(
                [round(value, 9) for value in ours.column(column)],
                [round(float(value), 9) for value in theirs.data(column)],
                column,
            )
        # 派生列也必须一致
        for column in ("Rho", "T"):
            self.assertEqual(
                [round(value, 9) for value in ours.column(column)],
                [round(float(value), 9) for value in getattr(theirs, column)],
                column,
            )


if __name__ == "__main__":
    unittest.main()

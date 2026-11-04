"""阶段 1 快照测试：锁定 MESALinter 的现状判定结果。

这些用例同时是**已知缺陷的活文档**：数组型赋值误报、ignored_blocks 漏检、
默认数据库路径依赖 CWD。阶段 2 把 linting 抽到 core/linting/ 时，
缺陷修复必须逐条以"期望值变更 + 提交信息声明"的方式显式进行。
"""

from __future__ import annotations

import os
import tempfile
import unittest

from mesa_linter import MESALinter
from tests.helpers import DB_PATH, PROJECT_ROOT, SAMPLE_VALID_INLIST


class LinterSnapshot(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DB_PATH.exists():
            raise unittest.SkipTest(f"缺少数据库文件: {DB_PATH}")
        cls.linter = MESALinter(db_path=str(DB_PATH))

    def test_database_is_loaded(self) -> None:
        self.assertEqual(len(self.linter.valid_params), 4147)
        self.assertIn("initial_mass", self.linter.valid_params)
        self.assertNotIn("definitely_not_a_param", self.linter.valid_params)

    def test_valid_inlist_produces_no_issues(self) -> None:
        self.assertEqual(self.linter.check_file(SAMPLE_VALID_INLIST), [])

    def test_typo_parameter_is_reported_with_suggestion(self) -> None:
        """**行为变更（阶段 5）**：未知参数改为"拼写纠错式"报告。

        原因：参数库覆盖率有限（实测 ``xa_central_lower_limit*``、
        ``use_Type2_opacities``、``read_extra_*_inlist`` 等**真实参数都不在库中**），
        白名单式报错会把 MESA 官方 inlist 全报成错误（真实项目上曾一次报出 14 个
        error）。现在只有库里存在高度相近的名字时才报错，并给出建议。
        """
        issues = self.linter.check_file("&controls\n   initial_mas = 1.0d0\n/\n")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["line"], 2)
        self.assertEqual(issues[0]["type"], "参数校验")
        self.assertEqual(issues[0]["level"], "error")
        self.assertIn("initial_mas", issues[0]["message"])
        self.assertIn("initial_mass", issues[0]["message"])

    def test_unknown_parameter_without_close_match_is_not_reported(self) -> None:
        """库里没有相近名字 → 视为"数据库未收录"，不报错（避免误报）。"""
        issues = self.linter.check_file(
            "&controls\n   definitely_not_a_param = 1.0d0\n/\n"
        )
        self.assertEqual(issues, [])

    def test_uncovered_namelist_group_is_not_parameter_checked(self) -> None:
        """``&kap``/``&eos`` 等组不在参数库里 → 不做参数名校验。"""
        issues = self.linter.check_file(
            "&kap\n   use_Type2_opacities = .true.\n   Zbase = 0.02d0\n/\n"
        )
        self.assertEqual(issues, [], "MESA 官方 kap 参数不得被报成未知参数")

    def test_extra_inlist_mechanism_parameters_are_accepted(self) -> None:
        """标准 inlist 都会写的机制参数（不在库里）不得报错。"""
        issues = self.linter.check_file(
            "&star_job\n"
            "   read_extra_star_job_inlist(1) = .true.\n"
            "   extra_star_job_inlist_name(1) = 'inlist_project'\n"
            "/\n"
        )
        self.assertEqual(issues, [])

    def test_array_element_assignment_no_longer_false_positives(self) -> None:
        """**行为变更（阶段 5，P21a 修复）**：数组型参数按基名查库。

        基线把 ``xa_central_lower_limit_species(1)`` 整个拿去查库 → 必然查不到 →
        误报；真实 MESA inlist 里这种写法到处都是（真实项目实测报错）。
        现在先去掉下标再查，并配合拼写纠错策略。
        """
        issues = self.linter.check_file(
            "&controls\n   xa_central_lower_limit_species(1) = 'h1'\n/\n"
        )
        self.assertEqual(issues, [])

    def test_array_element_typo_is_still_reported(self) -> None:
        """去下标后与库中参数高度相近时，仍要报错并给建议。"""
        issues = self.linter.check_file("&controls\n   initial_masss(1) = 1.0d0\n/\n")
        self.assertEqual(len(issues), 1)
        self.assertIn("initial_mass", issues[0]["message"])

    def test_numeric_variable_name_is_reported(self) -> None:
        issues = self.linter.check_file("&controls\n   214=53\n/\n")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["line"], 2)
        self.assertIn("不符合变量命名规范", issues[0]["message"])

    def test_hash_comment_is_reported(self) -> None:
        issues = self.linter.check_file(
            "&controls\n   # 这是非法注释\n   initial_mass = 1.0d0\n/\n"
        )
        self.assertEqual([i["line"] for i in issues], [2])
        self.assertEqual(issues[0]["message"], "检测到非法注释符 '#'。")

    def test_d0_multidigit_fraction_no_longer_false_positives(self) -> None:
        """**行为变更（阶段 5，P21d 修复）**：已带 d0 后缀的数字不再被误报。

        基线正则 ``(?!\\s*[dD][+-]?\\d+)`` 未锚定数字结尾，``\\d+`` 回退一位，
        于是 ``initial_z = 0.02d0`` 被报成"数字 '0.0' 建议添加 d0"；真实 MESA
        官方 inlist 里的 ``0.99d0`` 也中招（实测）。现在整token匹配后再判断。
        """
        for value in ("0.02d0", "0.99d0", "1.0D0", "1.5d-3"):
            with self.subTest(value=value):
                issues = self.linter.check_file(
                    f"&controls\n   initial_z = {value}\n/\n"
                )
                self.assertEqual(issues, [], f"{value} 已带指数后缀，不应报精度建议")

    def test_float_without_d0_gets_precision_hint(self) -> None:
        issues = self.linter.check_file("&controls\n   initial_mass = 1.5\n/\n")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["level"], "warning")
        self.assertEqual(issues[0]["type"], "精度建议")
        self.assertEqual(issues[0]["message"], "数字 '1.5' 建议添加 'd0' 后缀。")

    def test_ignored_block_names_bypass_parameter_check(self) -> None:
        """基线缺陷：变量名若恰好等于 ignored_blocks 中的块名，则跳过参数校验，
        即便数据库中并不存在名为 net 的参数。"""
        self.assertNotIn("net", self.linter.valid_params)
        self.assertEqual(self.linter.check_file("&controls\n   net = 99\n/\n"), [])

    def test_missing_database_degrades_silently(self) -> None:
        """基线行为：数据库缺失时静默降级为"不校验参数"。"""
        linter = MESALinter(db_path=str(PROJECT_ROOT / "不存在的库.db"))
        self.assertEqual(linter.valid_params, set())
        self.assertEqual(
            linter.check_file("&controls\n   totally_unknown_param = 1.0d0\n/\n"), []
        )

    def test_default_db_path_is_cwd_independent(self) -> None:
        """【阶段 2 声明变更】默认库路径不再依赖进程 CWD（修复 P21c）。

        阶段 1 基线行为：默认 ``db_path="mesa_data.db"`` 相对 CWD，
        从其他目录启动时参数校验会静默失效。
        现行为：由 ``core.db.default_db_path()`` 定位（先 CWD、再项目根）。
        本用例的期望值变化属于**有意修复**，已在提交信息中声明。
        """
        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                linter = MESALinter()
                self.assertEqual(len(linter.valid_params), 4147)
            finally:
                os.chdir(old_cwd)

    def test_explicit_db_path_is_still_honoured(self) -> None:
        linter = MESALinter(db_path=str(PROJECT_ROOT / "不存在的库.db"))
        self.assertEqual(linter.valid_params, set())


if __name__ == "__main__":
    unittest.main()

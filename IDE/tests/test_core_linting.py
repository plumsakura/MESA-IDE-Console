"""core.linting 单元测试：规则搬移后的核心层行为。

与 ``tests/test_linter_snapshot.py``（测兼容层 ``mesa_linter.MESALinter``）
形成对照：这里测的是结构化 ``Issue`` API 与无 UI 依赖的核心实现。
"""

from __future__ import annotations

import os
import tempfile
import unittest

from core.db import ParamDatabase
from core.linting import IGNORED_BLOCKS, Issue, InlistLinter
from tests.helpers import DB_PATH, PROJECT_ROOT, SAMPLE_VALID_INLIST


class CoreLinterRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DB_PATH.exists():
            raise unittest.SkipTest(f"缺少数据库文件: {DB_PATH}")
        cls.db = ParamDatabase(DB_PATH)
        cls.linter = InlistLinter(db=cls.db)

    def test_issue_is_frozen_dataclass_with_dict_view(self) -> None:
        # **行为变更（阶段 5）**：未知参数改为拼写纠错式 —— 用"库里相近的名字"触发
        issues = self.linter.check_file("&controls\n   initial_mas = 1.0d0\n/\n")
        self.assertEqual(len(issues), 1)
        issue = issues[0]
        self.assertIsInstance(issue, Issue)
        self.assertEqual(
            issue.as_dict(),
            {
                "line": 2,
                "type": "参数校验",
                "level": "error",
                "message": "未知参数 'initial_mas' 不存在于数据库中"
                "（是否想写 'initial_mass'？）。",
            },
        )
        with self.assertRaises(Exception):
            issue.line = 99  # type: ignore[misc]  # frozen dataclass

    def test_valid_inlist_has_no_issues(self) -> None:
        self.assertEqual(self.linter.check_file(SAMPLE_VALID_INLIST), [])

    def test_rules_match_baseline_in_order(self) -> None:
        """同一份输入必须产出与基线完全相同的顺序与内容。"""
        content = (
            "&controls\n"
            "   # 非法注释\n"
            "   214=53\n"
            "   initial_zz = 1.5\n"
            "   initial_mass = 1.0d0\n"
            "/\n"
        )
        issues = self.linter.check_file(content)
        self.assertEqual([i.line for i in issues], [2, 3, 4, 4])
        self.assertEqual([i.type for i in issues], ["语法错误", "语法错误", "参数校验", "精度建议"])
        self.assertEqual(issues[0].message, "检测到非法注释符 '#'。")
        self.assertIn("不符合变量命名规范", issues[1].message)
        self.assertIn("initial_zz", issues[2].message)
        self.assertEqual(issues[3].message, "数字 '1.5' 建议添加 'd0' 后缀。")

    def test_array_assignment_is_checked_by_base_name(self) -> None:
        """**P21a 已修**：数组型参数不再误报（真实 MESA inlist 大量使用）。"""
        self.assertEqual(
            self.linter.check_file(
                "&controls\n   xa_central_lower_limit_species(1) = 'h1'\n/\n"
            ),
            [],
        )

    def test_d0_suffix_is_not_falsely_reported(self) -> None:
        """**P21d 已修**：已带 d0 的数字不再被误报（真实 ``0.99d0`` 已复现）。"""
        self.assertEqual(
            self.linter.check_file("&controls\n   initial_z = 0.02d0\n/\n"), []
        )

    def test_ignored_blocks_bypass_is_preserved(self) -> None:
        self.assertIn("net", IGNORED_BLOCKS)
        self.assertEqual(self.linter.check_file("&controls\n   net = 99\n/\n"), [])

    def test_ignored_blocks_matches_baseline_set(self) -> None:
        self.assertEqual(
            set(IGNORED_BLOCKS),
            {"controls", "star_job", "pgstar", "binary_controls",
             "mesa_runner", "eos", "kap", "rates", "net"},
        )

    def test_profile_values_do_not_trigger_unknown_param(self) -> None:
        """等号右侧的值不参与参数校验（只检查左侧变量名）。"""
        self.assertEqual(
            self.linter.check_file("&controls\n   initial_mass = 1.0d0\n/\n"), []
        )

    def test_missing_database_reports_syntax_but_skips_params(self) -> None:
        linter = InlistLinter(db_path=str(PROJECT_ROOT / "不存在的库.db"))
        self.assertEqual(linter.valid_params, frozenset())
        content = "&controls\n   totally_unknown_param = 1.0d0\n   214=53\n/\n"
        issues = linter.check_file(content)
        self.assertEqual([i.line for i in issues], [3], "无数据库时参数校验应跳过，但语法规则仍生效")


class CoreLinterDatabaseBinding(unittest.TestCase):
    def test_default_path_is_cwd_independent(self) -> None:
        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                linter = InlistLinter()
                self.assertEqual(len(linter.valid_params), 4147)
            finally:
                os.chdir(old_cwd)

    def test_explicit_db_object_is_reused(self) -> None:
        db = ParamDatabase(DB_PATH)
        self.addCleanup(db.close)
        linter = InlistLinter(db=db)
        self.assertIs(linter.db, db)
        self.assertEqual(len(linter.valid_params), 4147)


if __name__ == "__main__":
    unittest.main()

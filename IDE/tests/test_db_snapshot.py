"""阶段 1 快照测试：锁定 mesa_data.db 的数据契约。

这些断言记录重构**之前**的数据库结构与查询语义。阶段 2 把
mesa_linter / mesa_search 中的数据访问抽到 core/db.py 时，
这些测试必须原样继续通过（数据契约不变）。
"""

from __future__ import annotations

import sqlite3
import unittest

from tests.helpers import DB_PATH

# mesa_search.MesaSearchComponent.perform_search 使用的 SQL（原样抄录）
FTS_SQL = """
SELECT p.name, p.default_value, p.namelist_group, p.description
FROM parameters p
         JOIN param_search s ON p.id = s.rowid
WHERE param_search MATCH ? LIMIT 20
"""


class DatabaseContractSnapshot(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DB_PATH.exists():
            raise unittest.SkipTest(f"缺少数据库文件: {DB_PATH}")
        cls.conn = sqlite3.connect(str(DB_PATH))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def test_required_tables_exist(self) -> None:
        names = {row[0] for row in
                 self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"parameters", "parameter_examples", "param_search"}.issubset(names),
                        f"实际表: {sorted(names)}")

    def test_parameters_schema_locked(self) -> None:
        cols = [row[1] for row in self.conn.execute("PRAGMA table_info(parameters)")]
        self.assertEqual(
            cols,
            ["id", "name", "namelist_group", "default_value", "description", "source_file"],
        )

    def test_row_counts_locked(self) -> None:
        counts = {
            t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("parameters", "parameter_examples", "param_search")
        }
        self.assertEqual(counts["parameters"], 4147)
        self.assertEqual(counts["parameter_examples"], 10704)
        self.assertEqual(counts["param_search"], 4147)

    def test_fts_prefix_search_contract(self) -> None:
        rows = self.conn.execute(FTS_SQL, ("initial_mass*",)).fetchall()
        self.assertEqual(len(rows), 5, f"实际返回: {rows}")
        names = {row[0] for row in rows}
        self.assertIn("initial_mass", names)
        for row in rows:
            self.assertEqual(len(row), 4, "每行必须是 (name, default_value, namelist_group, description)")

    def test_fts_quotes_are_stripped_by_caller(self) -> None:
        """mesa_search 会先做 query.replace('"','')，这里锁定去引号后的可用性。"""
        dirty = '"initial_mass"'
        clean = dirty.replace('"', '')
        rows = self.conn.execute(FTS_SQL, (f"{clean}*",)).fetchall()
        self.assertEqual(len(rows), 5)

    def test_fts_join_alignment_assumption(self) -> None:
        """锁定 p.id = s.rowid 的对齐假设（FTS 与参数表逐行对应）。"""
        orphan = self.conn.execute(
            """SELECT COUNT(*) FROM parameters p
               LEFT JOIN param_search s ON p.id = s.rowid
               WHERE s.rowid IS NULL"""
        ).fetchone()[0]
        self.assertEqual(orphan, 0, "存在无法通过 rowid 关联到 FTS 索引的参数行")

    def test_known_absent_parameters_documented(self) -> None:
        """记录两处基线缺陷的证据（阶段 2 修复 linting 时参考）。"""
        # 1) 不存在数组型参数 → linter 对 xa_xxx(1) = ... 会误报"未知参数"
        rows = self.conn.execute(
            "SELECT name FROM parameters WHERE name LIKE '%central_lower_limit%'"
        ).fetchall()
        self.assertEqual(rows, [])
        # 2) 不存在名为 net/eos/kap/rates 的参数 → linter 的 ignored_blocks 会放过它们
        rows = self.conn.execute(
            "SELECT name FROM parameters WHERE name IN ('net','eos','kap','rates')"
        ).fetchall()
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()

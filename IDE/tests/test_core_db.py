"""core.db 单元测试：参数数据库访问层。

断言值与 ``tests/test_db_snapshot.py`` 保持一致（同一数据契约），
区别在于这里测的是**新的 core 层 API**，而非原 mesa_linter/mesa_search 的内联逻辑。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from core.db import ParameterRow, ParamDatabase, default_db_path
from tests.helpers import DB_PATH, PROJECT_ROOT


class ParamDatabaseReadOnly(unittest.TestCase):
    """只读访问：绝不写入 mesa_data.db。"""

    @classmethod
    def setUpClass(cls) -> None:
        if not DB_PATH.exists():
            raise unittest.SkipTest(f"缺少数据库文件: {DB_PATH}")

    def setUp(self) -> None:
        self.db = ParamDatabase(DB_PATH)
        self.addCleanup(self.db.close)

    def test_available_and_count(self) -> None:
        self.assertTrue(self.db.available)
        self.assertEqual(self.db.count(), 4147)

    def test_valid_param_names_are_lowercased_frozenset(self) -> None:
        names = self.db.valid_param_names
        self.assertIsInstance(names, frozenset)
        self.assertEqual(len(names), 4147)
        self.assertIn("initial_mass", names)
        self.assertNotIn("definitely_not_a_param", names)
        self.assertTrue(all(name == name.lower() for name in names))

    def test_search_returns_parameter_rows(self) -> None:
        rows = self.db.search("initial_mass")
        self.assertEqual(len(rows), 5)
        self.assertIsInstance(rows[0], ParameterRow)
        self.assertIn("initial_mass", {row.name for row in rows})
        first = rows[0]
        self.assertIsInstance(first.namelist_group, (str, type(None)))
        self.assertIsInstance(first.description, (str, type(None)))

    def test_search_strips_quotes(self) -> None:
        self.assertEqual(len(self.db.search('"initial_mass"')), 5)

    def test_search_limit_is_respected(self) -> None:
        self.assertEqual(len(self.db.search("initial_mass", limit=1)), 1)
        self.assertEqual(len(self.db.search("initial_mass", limit=3)), 3)

    def test_search_empty_query_returns_empty(self) -> None:
        self.assertEqual(self.db.search(""), [])
        self.assertEqual(self.db.search('  "" '), [])

    def test_search_invalid_fts_syntax_degrades(self) -> None:
        """基线行为：FTS 语法错误被吞掉并返回空列表（现改为 logging 记录）。"""
        self.assertEqual(self.db.search("("), [])

    def test_missing_database_degrades_without_raising(self) -> None:
        db = ParamDatabase(PROJECT_ROOT / "不存在的库.db")
        self.addCleanup(db.close)
        self.assertFalse(db.available)
        self.assertEqual(db.valid_param_names, frozenset())
        self.assertEqual(db.search("initial_mass"), [])
        self.assertEqual(db.count(), 0)

    def test_context_manager_closes(self) -> None:
        with ParamDatabase(DB_PATH) as db:
            self.assertEqual(db.count(), 4147)
        self.assertIsNone(db._conn)


class DefaultDbPathResolution(unittest.TestCase):
    """修复基线缺陷：默认路径不再只认 CWD。"""

    def test_falls_back_to_project_root_when_cwd_lacks_db(self) -> None:
        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                resolved = Path(default_db_path()).resolve()
            finally:
                os.chdir(old_cwd)
        self.assertEqual(resolved, DB_PATH.resolve())

    def test_prefers_cwd_when_db_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "mesa_data.db"
            local.write_bytes(b"")
            self.assertEqual(Path(default_db_path(tmp)).resolve(), local.resolve())

    def test_packaged_db_is_used_when_nothing_else_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(Path(default_db_path(tmp)).resolve(), DB_PATH.resolve())


if __name__ == "__main__":
    unittest.main()

"""MESA 参数数据库（``mesa_data.db``）访问层（core，仅标准库）。

对外行为（由 ``tests/test_db_snapshot.py`` 与 ``tests/test_core_db.py`` 锁定）：

- 参数名集合统一按**小写**比较（原 ``mesa_linter._load_params_from_db`` 行为）；
- 搜索走 FTS5 前缀查询：去掉引号 + 追加 ``*``，最多返回 ``limit`` 行
  （原 ``mesa_search.perform_search`` 行为）；
- 数据库缺失或查询失败时**降级为空结果且不抛异常**（保持原行为），
  但改为经 ``logging`` 记录（原实现是 print / 静默）。

修复的基线缺陷：``default_db_path()`` 先看 CWD，再回退到项目根目录，
不再像原实现那样"只认 CWD，从其他目录启动就静默失效"。
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DB_FILENAME = "mesa_data.db"

# 与 mesa_search.perform_search 中的 SQL 等价（仅把 LIMIT 参数化）
_SEARCH_SQL = """
SELECT p.name, p.default_value, p.namelist_group, p.description
FROM parameters p
         JOIN param_search s ON p.id = s.rowid
WHERE param_search MATCH ? LIMIT ?
"""


@dataclass(frozen=True)
class ParameterRow:
    """一条参数搜索结果（列顺序与 SQL 一致，便于移植时逐个字段翻译）。"""

    name: str
    default_value: str | None
    namelist_group: str | None
    description: str | None


def default_db_path(cwd: str | os.PathLike[str] | None = None) -> Path:
    """定位 ``mesa_data.db``：优先给定/CWD，其次 core 包所在项目根目录。"""
    base = Path(cwd) if cwd is not None else Path.cwd()
    candidate = base / DB_FILENAME
    if candidate.is_file():
        return candidate
    packaged = Path(__file__).resolve().parent.parent / DB_FILENAME
    if packaged.is_file():
        return packaged
    return candidate


class ParamDatabase:
    """``mesa_data.db`` 的读取封装（只读，永不写入）。"""

    def __init__(self, db_path: str | os.PathLike[str] | None = None) -> None:
        self.db_path: Path = Path(db_path) if db_path is not None else default_db_path()
        self._conn: sqlite3.Connection | None = None
        self._names: frozenset[str] | None = None

    # ---------------- 生命周期 ----------------

    @property
    def available(self) -> bool:
        return self.db_path.is_file()

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __del__(self) -> None:  # pragma: no cover - 依赖 GC 时机
        """兜底关闭连接（GUI 长驻进程中避免泄漏 sqlite 句柄）。"""
        try:
            self.close()
        except Exception:  # noqa: BLE001 - 析构期不得抛出异常
            pass

    def __enter__(self) -> "ParamDatabase":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ---------------- 参数名白名单 ----------------

    @property
    def valid_param_names(self) -> frozenset[str]:
        """全部合法参数名（小写）。加载失败时为空集合（保持原降级行为）。"""
        if self._names is None:
            self._names = self._load_names()
        return self._names

    def _load_names(self) -> frozenset[str]:
        if not self.available:
            logger.warning("[ParamDatabase] 找不到数据库: %s，已跳过参数校验。", self.db_path)
            return frozenset()
        try:
            rows = self._connection().execute("SELECT name FROM parameters").fetchall()
        except sqlite3.Error as exc:
            logger.error("[ParamDatabase] 读取数据库失败: %s", exc)
            return frozenset()
        return frozenset(str(row[0]).lower() for row in rows if row[0])

    def count(self) -> int:
        """``parameters`` 表行数；数据库不可用时返回 0。"""
        if not self.available:
            return 0
        try:
            row = self._connection().execute("SELECT COUNT(*) FROM parameters").fetchone()
        except sqlite3.Error as exc:
            logger.error("[ParamDatabase] 统计失败: %s", exc)
            return 0
        return int(row[0]) if row else 0

    # ---------------- FTS 搜索 ----------------

    def search(self, query: str, limit: int = 20) -> list[ParameterRow]:
        """FTS5 前缀搜索；无结果/失败返回空列表（不抛异常）。"""
        if not self.available:
            return []
        clean = (query or "").replace('"', "").strip()
        if not clean:
            return []
        try:
            rows = self._connection().execute(_SEARCH_SQL, (f"{clean}*", limit)).fetchall()
        except sqlite3.Error as exc:
            logger.warning("[ParamDatabase] 搜索失败 query=%r: %s", query, exc)
            return []
        return [ParameterRow(row[0], row[1], row[2], row[3]) for row in rows]

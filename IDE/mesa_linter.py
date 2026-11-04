"""兼容层（薄代理）：``MESALinter`` 旧接口。

实现已迁移到 :mod:`core.linting`；本文件只做接口转发，保证
``IDE.py:11`` 的 ``from mesa_linter import MESALinter`` 行为不变。

**阶段 3 目标**：``IDE.py`` / ``ide_ui`` 直接使用 ``core.linting.InlistLinter``，
届时本文件应被删除（当前保留是为了让单模块迁移可回滚）。

声明的行为变更（相对阶段 1 基线快照）：

- 默认数据库路径不再相对进程 CWD，而由 ``core.db.default_db_path()`` 定位
  （先 CWD、再项目根目录）—— 修复基线缺陷 P21c（从其他目录启动时
  参数校验会静默失效）。显式传入 ``db_path`` 时行为不变。
"""

from __future__ import annotations

from core.linting import InlistLinter, Issue


class MESALinter:
    """旧接口包装：``check_file`` 返回 dict 列表（与原实现返回类型一致）。"""

    def __init__(self, db_path: str | None = None) -> None:
        self._linter = InlistLinter(db_path=db_path)
        # 兼容旧属性（tests/test_linter_snapshot.py 与可能的第三方脚本会访问）
        self.valid_params = self._linter.valid_params
        self.ignored_blocks = self._linter.ignored_blocks
        self.db = self._linter.db
        self.re_bad_comment = self._linter.re_bad_comment
        self.re_float_needs_d0 = self._linter.re_float_needs_d0
        self.re_namelist_start = self._linter.re_namelist_start
        self.re_namelist_end = self._linter.re_namelist_end
        self.re_assignment = self._linter.re_assignment

    def check_file(self, content: str) -> list[dict[str, object]]:
        return [issue.as_dict() for issue in self._linter.check_file(content)]


__all__ = ["MESALinter", "Issue"]

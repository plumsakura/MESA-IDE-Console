"""ide_ui：Tk 视图层。

分层规则（由 ``tests/test_architecture_guards.py`` 守卫）：

- 本包**可以**依赖 ``tkinter``；
- 本包**不得**直接 ``import sqlite3``（数据访问一律经 ``core``）；
- 业务逻辑与协议一律放 ``core``，本包只做渲染与事件转发。

``IDE.py`` 现为本包的兼容门面。
"""

from .app import MESA_IDE, start_ide

__all__ = ["MESA_IDE", "start_ide"]

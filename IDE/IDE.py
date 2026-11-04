"""兼容门面：MESA IDE 编辑器窗口。

实现已迁移到 :mod:`ide_ui`（阶段 3）。本文件只保留旧导入路径：

    from IDE import start_ide

``create_new_program.py`` / ``open_old_program.py`` 仍通过该路径启动编辑器，
保持其不变即可；新代码请直接 ``from ide_ui import MESA_IDE, start_ide``。

相对基线（386 行、9 处重复方法定义、占位注释 P1/P2）的修复清单见
``ide_ui/app.py`` 模块 docstring 与《重构进度》阶段 3。
"""

from ide_ui import MESA_IDE, start_ide

__all__ = ["MESA_IDE", "start_ide"]

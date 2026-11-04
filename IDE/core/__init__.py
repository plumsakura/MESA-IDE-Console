"""core：与 UI 无关的业务逻辑与协议层（**可移植规格层**）。

硬性约束（由 tests/test_architecture_guards.py 守卫）：

- 不得 import ``tkinter`` / ``matplotlib``；
- 命令构造不得依赖 shell（禁止 ``shell=True``、禁止拼接命令字符串）；
- 任何将来移植到其他语言时必须逐字保留的行为，都必须有对应快照测试。

本包只依赖标准库（``sqlite3`` / ``os`` / ``subprocess`` 等），
以便用系统 python3 直接运行其单元测试。
"""

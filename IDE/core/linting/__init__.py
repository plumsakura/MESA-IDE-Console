"""inlist / namelist 校验（core 层，仅标准库）。

本包是 ``mesa_linter.MESALinter`` 规则的逐条搬移，**行为完全一致**，
包括三处已知缺陷（由 ``tests/test_linter_snapshot.py`` 固定为基线行为）：

1. 数组型参数 ``xa_xxx(1) = ...`` 被判为"未知参数"（参数库中没有数组名）；
2. ``IGNORED_BLOCKS`` 中的块名（net/eos/kap/rates…）被当作变量名时跳过参数校验；
3. ``RE_FLOAT_NEEDS_D0`` 未锚定数字结尾，``0.02d0`` 这类多位小数被误报缺少 d0。

修复上述任一项都必须作为"声明变更"单独提交：同步修改快照期望值，
并在提交信息中写明原因。
"""

from .inlist import IGNORED_BLOCKS, Issue, InlistLinter

__all__ = ["InlistLinter", "Issue", "IGNORED_BLOCKS"]

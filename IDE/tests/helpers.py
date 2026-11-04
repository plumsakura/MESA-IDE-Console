"""测试公共装置：路径解析、数据库定位、样例 inlist、防挂基线类。

设计原则：测试全部使用标准库 unittest，不引入 pytest 等第三方依赖，
以便将来把项目移植到其他语言时，这些测试可以直接当作"行为规格"逐条翻译。
"""

from __future__ import annotations

import pathlib
import unittest
from tkinter import messagebox as _messagebox
from tkinter import simpledialog as _simpledialog
from unittest import mock

# tests/ 的上一级即项目根目录（IDE/）
PROJECT_ROOT: pathlib.Path = pathlib.Path(__file__).resolve().parent.parent
DB_PATH: pathlib.Path = PROJECT_ROOT / "mesa_data.db"

# 真实存在于 mesa_data.db 的参数名（用于"合法参数不应报错"用例）
VALID_PARAM_CONTROLS = "initial_mass"      # namelist_group = controls
VALID_PARAM_STAR_JOB = "mesa_dir"          # namelist_group = star_job
VALID_PARAM_PGSTAR = "pgstar_interval"     # namelist_group = pgstar

# mesa_data.db 中确实不存在的参数名（用于未知参数用例）
UNKNOWN_PARAM = "definitely_not_a_param"

# 一份合法 inlist 片段：当前实现应产出零告警。
# 注意：小数位多于 1 位且带 d0 后缀（如 0.02d0）会触发已知误报，
# 见 tests/test_linter_snapshot.py::test_d0_multidigit_fraction_false_positive。
SAMPLE_VALID_INLIST = f"""&controls
   {VALID_PARAM_CONTROLS} = 1.0d0
   initial_z = 0.2d0
/

&star_job
   {VALID_PARAM_STAR_JOB} = '../../..'
/
"""


class SafeDialogTestCase(unittest.TestCase):
    """禁止任何**真实** Tk 弹窗的基线测试类。

    模态对话框（messagebox/simpledialog）会阻塞并等待用户点击，导致测试
    永久挂起 —— 本类把全部弹窗入口替换为记录型替身，从机制上杜绝挂起。
    被替换的调用会记录在 ``self.dialog_calls`` 中，便于断言。

    注意：子测试仍可自行 `mock.patch.object(...)`，内层 patch 会优先，
    退出后本类的替身自动恢复。
    """

    def setUp(self) -> None:
        super().setUp()
        self.dialog_calls: list[tuple[str, tuple, dict]] = []
        self._dialog_patchers: list[mock._patch] = []

        for name in (
            "showerror", "showwarning", "showinfo",
            "askyesno", "askokcancel", "askretrycancel", "askquestion",
        ):
            self._dialog_patchers.append(
                mock.patch.object(_messagebox, name, self._recorder(name))
            )
        for name in ("askstring", "askinteger", "askfloat"):
            self._dialog_patchers.append(
                mock.patch.object(_simpledialog, name, self._recorder(name))
            )

        for patcher in self._dialog_patchers:
            patcher.start()
        self.addCleanup(self._stop_dialog_patchers)

    def _recorder(self, kind: str):
        def record(*args, **kwargs):
            self.dialog_calls.append((kind, args, kwargs))
            return None

        return record

    def _stop_dialog_patchers(self) -> None:
        for patcher in reversed(self._dialog_patchers):
            patcher.stop()

    def assert_no_dialogs(self) -> None:
        self.assertEqual(self.dialog_calls, [], f"出现了未预期的弹窗调用: {self.dialog_calls}")

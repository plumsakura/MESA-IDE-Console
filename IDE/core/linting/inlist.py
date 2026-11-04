"""namelist（inlist）语法与参数校验规则。

移植说明：本模块只输出结构化 ``Issue`` 对象，不做任何 UI 或字符串格式化，
因此可被其他语言逐条翻译（正则与判定顺序必须保持一致）。
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass

from core.db import ParamDatabase

logger = logging.getLogger(__name__)

# 变量名若恰好是这些 namelist 块名，则跳过参数校验（原 mesa_linter.py:21-22 行为）
IGNORED_BLOCKS: frozenset[str] = frozenset(
    {
        "controls",
        "star_job",
        "pgstar",
        "binary_controls",
        "mesa_runner",
        "eos",
        "kap",
        "rates",
        "net",
    }
)

#: 参数库实际覆盖的 namelist 组（``mesa_data.db`` 只有这些组的数据）。
#: 其它组（``&kap``/``&eos``/``&net``…）**不做参数名校验**，否则会把 MESA 官方
#: 示例里的合法参数（如 ``use_Type2_opacities``、``Zbase``）全报成"未知参数"。
DB_COVERED_GROUPS: frozenset[str] = frozenset(
    {"controls", "star_job", "pgstar", "controls_dev", "star_job_dev"}
)

#: 参数库覆盖率有限（实测：``xa_central_lower_limit*``、``use_Type2_opacities``、
#: ``read_extra_*_inlist`` 等**真实参数都不在库中**），因此"未知参数"不再按
#: 白名单一刀切报错，而是做**拼写纠错**：只有当库里存在高度相近的参数名时才报错
#: （例如 ``initial_mas`` → 提示 ``initial_mass``），否则视为"数据库未收录"。
TYPO_CUTOFF = 0.85

#: MESA 的 "extra inlist" 机制参数：任何标准 inlist 都会用到，且不在参数库里
RE_MECHANISM_PARAM = re.compile(
    r"^(?:read_extra_\w+_inlist|extra_\w+_inlist_name)$", re.IGNORECASE
)

#: 数组型参数写法 ``name(1)``（真实 MESA inlist 里非常常见）
RE_ARRAY_INDEX = re.compile(r"\([^()]*\)$")

# 预编译正则（与原 mesa_linter.py:12-18 完全一致）
RE_BAD_COMMENT = re.compile(r"(?<!\w)#")
#: 精度建议：**整体吃掉数值 token**（含可选 d0 指数）再判断是否缺后缀。
#: 原正则 ``(?!\s*[dD][+-]?\d+)`` 未锚定数字结尾，``\d+`` 会回退一位，
#: 导致 ``0.02d0`` 被误报成"数字 '0.0' 建议添加 d0"（P21d，真实文件里已复现）。
RE_FLOAT_NEEDS_D0 = re.compile(r"=\s*([-+]?\d*\.\d+)([dD][+-]?\d+)?")
RE_NAMELIST_START = re.compile(r"^\s*&(\w+)")
RE_NAMELIST_END = re.compile(r"^\s*/")
# 说明：原实现编译了 RE_ASSIGNMENT 但从未使用（原 mesa_linter.py:18），
# 此处原样保留以便对照与移植审查。
RE_ASSIGNMENT = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=", re.IGNORECASE)
# 匹配任意等号左侧 token（原实现是在 check_file 内每次重新编译，此处移到模块级：
# 输出完全等价，同时消除每次调用重新编译与实例状态被改写的问题）
RE_POTENTIAL_ASSIGNMENT = re.compile(r"^\s*([^!=\s]+)\s*=")
RE_STARTS_WITH_LETTER = re.compile(r"^[a-zA-Z_]")

LEVEL_ERROR = "error"
LEVEL_WARNING = "warning"
TYPE_SYNTAX = "语法错误"
TYPE_PARAM = "参数校验"
TYPE_PRECISION = "精度建议"


@dataclass(frozen=True)
class Issue:
    """一条校验结果（结构化，便于移植与测试断言）。"""

    line: int
    type: str
    level: str
    message: str

    def as_dict(self) -> dict[str, object]:
        """转换回旧版 ``mesa_linter`` 的 dict 表示（兼容层使用）。"""
        return {
            "line": self.line,
            "type": self.type,
            "level": self.level,
            "message": self.message,
        }


class InlistLinter:
    """对 inlist 文本做语法与参数校验。

    :param db: 已构造的 :class:`core.db.ParamDatabase`（优先使用）
    :param db_path: 数据库路径；为 ``None`` 时由 ``core.db.default_db_path()``
        定位（不再依赖进程 CWD —— 这是对基线缺陷 P21c 的有意修复）
    """

    def __init__(
        self,
        db: ParamDatabase | None = None,
        db_path: str | None = None,
    ) -> None:
        self.db = db if db is not None else ParamDatabase(db_path)
        self.valid_params: frozenset[str] = self.db.valid_param_names
        self.ignored_blocks = IGNORED_BLOCKS
        # 以只读属性形式保留正则，便于外部对照与迁移审查
        self.re_bad_comment = RE_BAD_COMMENT
        self.re_float_needs_d0 = RE_FLOAT_NEEDS_D0
        self.re_namelist_start = RE_NAMELIST_START
        self.re_namelist_end = RE_NAMELIST_END
        self.re_assignment = RE_ASSIGNMENT
        if self.valid_params:
            logger.info("[MESA Linter] 已加载 %d 个参数到校验库。", len(self.valid_params))
        else:
            logger.warning("[MESA Linter] 参数库为空，参数校验将跳过（数据库: %s）。", self.db.db_path)

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def check_file(self, content: str) -> list[Issue]:
        """扫描文本内容，按行返回问题列表（判定顺序与原实现逐条一致）。"""
        issues: list[Issue] = []
        lines = content.splitlines()
        namelist_stack: list[str] = []

        for index, line in enumerate(lines, 1):
            stripped = line.strip()

            # 1. 忽略空行与 Fortran 注释
            if not stripped or stripped.startswith("!"):
                continue

            # 2. 非法注释符（#）
            if RE_BAD_COMMENT.search(line) and "!" not in line.split("#")[0]:
                issues.append(
                    Issue(index, TYPE_SYNTAX, LEVEL_ERROR, "检测到非法注释符 '#'。")
                )

            # 3. namelist 块边界（块开始/结束行本身不参与参数校验）
            block_match = RE_NAMELIST_START.match(stripped)
            if block_match:
                namelist_stack.append(block_match.group(1).lower())
                continue
            if RE_NAMELIST_END.match(stripped):
                if namelist_stack:
                    namelist_stack.pop()
                continue

            # 4. 赋值行
            match_assign = RE_POTENTIAL_ASSIGNMENT.match(stripped)
            if match_assign:
                potential_name = match_assign.group(1)

                # 情况 A：不符合变量命名规范（如 214=53）
                if not RE_STARTS_WITH_LETTER.match(potential_name):
                    issues.append(
                        Issue(
                            index,
                            TYPE_SYNTAX,
                            LEVEL_ERROR,
                            f"Syntax Error: 这一行 '{potential_name}=' 开头不符合变量命名规范（应以字母开头）。",
                        )
                    )
                # 情况 B：命名规范但不在参数库中
                elif self.valid_params and potential_name.lower() not in self.ignored_blocks:
                    # 数组型参数按**基名**查库（``xa_central_lower_limit_species(1)``
                    # 在库里是 ``xa_central_lower_limit_species``）
                    base_name = RE_ARRAY_INDEX.sub("", potential_name)
                    current_block = namelist_stack[-1] if namelist_stack else ""
                    covered = current_block in DB_COVERED_GROUPS
                    if (
                        covered
                        and not RE_MECHANISM_PARAM.match(base_name)
                        and base_name.lower() not in self.valid_params
                    ):
                        suggestion = difflib.get_close_matches(
                            base_name.lower(), self.valid_params, n=1, cutoff=TYPO_CUTOFF
                        )
                        if suggestion:
                            issues.append(
                                Issue(
                                    index,
                                    TYPE_PARAM,
                                    LEVEL_ERROR,
                                    f"未知参数 '{potential_name}' 不存在于数据库中"
                                    f"（是否想写 '{suggestion[0]}'？）。",
                                )
                            )
                        else:
                            # 数据库未收录（覆盖率有限）：不报错，仅记录调试日志
                            logger.debug(
                                "参数库未收录 %s（%s 块），跳过报告", potential_name, current_block
                            )

            # 5. 精度建议（缺少 d0 后缀）
            float_match = RE_FLOAT_NEEDS_D0.search(stripped)
            if float_match and float_match.group(2) is None:
                lowered = stripped.lower()
                if ".true." not in lowered and ".false." not in lowered:
                    value = float_match.group(1)
                    issues.append(
                        Issue(
                            index,
                            TYPE_PRECISION,
                            LEVEL_WARNING,
                            f"数字 '{value}' 建议添加 'd0' 后缀。",
                        )
                    )

        return issues

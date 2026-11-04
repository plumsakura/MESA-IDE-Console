"""MESA ``LOGS/`` 数据读取（core 层，仅标准库）。

把绘图链路需要的**数据抽取**从 matplotlib/Tk 中剥离出来，使其成为可移植规格
（其他语言按本文件逐条翻译即可，无需 mesa_reader/numpy/matplotlib）。

覆盖面（与真实 MESA 输出同构，见 ``tests/fixtures/make_fake_project.py``）::

    LOGS/history.data     表头 2 行 + 空行 + 列名行 + 数据行
    LOGS/profile<N>.data  同构；表头含 model_number / num_zones
    LOGS/profiles.index   无表头，每行 "模型号 优先级 剖面号"

数值一律接受 Fortran ``D`` 指数（``1.0d6`` / ``1.0D-06``）。

**已知边界（需人工确认，勿擅自"修好"）**：项目 venv 内的 ``mesa_reader``
0.4.0 走 pandas ``read_csv``，不解析任意列的 ``D`` 指数（仅当该列没有 D 时
才得到数值）—— 集成测试对此有显式断言。本模块按 MESA 真实输出解析，
因此是绘图链路在 D 指数数据上的**可用实现**。
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from typing import Sequence

HISTORY_FILENAME = "history.data"
INDEX_FILENAME = "profiles.index"
PROFILE_PREFIX = "profile"
PROFILE_SUFFIX = "data"


class MesaLogError(ValueError):
    """LOGS 数据缺失或格式不符。"""


@dataclass(frozen=True)
class MesaTable:
    """一张 MESA 数据表：表头键值 + 按列名索引的列。

    ``columns`` 放数值列（float），``text_columns`` 放字符串列（例如用户把
    ``version_number`` 加进 ``profile_columns.list`` 时）。绘图只用到数值列。
    """

    header: dict[str, str]
    columns: dict[str, tuple[float, ...]]
    text_columns: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def column(self, name: str) -> tuple[float, ...]:
        """取数值列；``logX`` 缺失时按需取幂/取对数（与 mesa_reader 行为一致）。"""
        if name in self.columns:
            return self.columns[name]
        derived = self._derived(name)
        if derived is not None:
            return derived
        if name in self.text_columns:
            raise MesaLogError(f"列 {name} 是字符串列，不是数值列")
        raise MesaLogError(f"缺少数据列: {name}")

    def _derived(self, name: str) -> tuple[float, ...] | None:
        """派生列：``Rho`` ← ``logRho``（10**x）；``log_Rho`` ← ``Rho``（log10）。

        MESA 的 profile 只写 ``logRho``/``logT``，而绘图代码用 ``Rho``/``T``；
        mesa_reader 也是这么按需求值的，这里与之对齐。
        """
        def source_values(source: str) -> tuple[float, ...] | None:
            if source in self.columns:
                return self.columns[source]
            return None

        for source in ("log" + name, "log_" + name):
            values = source_values(source)
            if values is not None:
                return tuple(10.0 ** value for value in values)
        if name.startswith("log_"):
            base = name[4:]
            values = source_values(base)
            if values is None and base:  # 允许"派生列再取对数"（如 log_Rho ← Rho ← logRho）
                values = self._derived(base)
            if values is not None:
                return self._safe_log10(values)
        return None

    @staticmethod
    def _safe_log10(values: Sequence[float]) -> tuple[float, ...]:
        return tuple(math.log10(value) if value > 0 else math.nan for value in values)

    def text_column(self, name: str) -> tuple[str, ...]:
        try:
            return self.text_columns[name]
        except KeyError:
            raise MesaLogError(f"缺少字符串列: {name}") from None

    def header_value(self, name: str, default: str = "") -> str:
        return self.header.get(name, default)

    def __getattr__(self, name: str) -> tuple[float, ...]:
        """属性式取列（``table.log_Teff`` / ``profile.Rho``），与 mesa_reader 一致。"""
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self.columns:
            return self.columns[name]
        if name in self.text_columns:
            raise AttributeError(name)
        derived = self._derived(name)
        if derived is None:
            raise AttributeError(name)
        return derived

    @property
    def model_number(self) -> int:
        """模型号：优先取数据列（history），否则取表头（profile）。"""
        if "model_number" in self.columns:
            return int(round(self.columns["model_number"][-1]))
        raw = self.header.get("model_number")
        if raw is None:
            raise MesaLogError("缺少 model_number（既不在数据列也不在表头）")
        return int(round(float(raw)))


@dataclass(frozen=True)
class ProfileIndex:
    """``LOGS/profiles.index`` 的对照表。"""

    model_numbers: tuple[int, ...]
    priorities: tuple[int, ...]
    profile_numbers: tuple[int, ...]

    def profile_with_model_number(self, model_number: int) -> int:
        try:
            position = self.model_numbers.index(int(model_number))
        except ValueError:
            raise MesaLogError(f"索引中没有模型号 {model_number}") from None
        return self.profile_numbers[position]


def _to_float(token: str) -> float:
    """把 MESA/Fortran 数值 token 转成 float（``d``/``D`` 指数 → ``e``）。

    只转换真正的 Fortran 指数（数字 + ``d``/``D`` + 可选符号），不能无差别
    ``token.replace("d", "e")`` —— 那会把 ``model_number`` 变成
    ``moeel_number``，从而把列名行误判为数据行。
    """
    return float(re.sub(r"(?<=\d)[dD](?=[+-]?\d)", "e", token))


def _index_line(tokens: Sequence[str]) -> bool:
    """是否是 MESA 表头的"序号行"（``1 2 3 ... N``，N 为表头项数）。"""
    if len(tokens) < 2:
        return False
    try:
        numbers = [int(token) for token in tokens]
    except ValueError:
        return False
    return numbers == list(range(1, len(numbers) + 1))


def _columns_position(rows: Sequence[str], header_index: int) -> int | None:
    """找到"数据列名行"的位置（真实文件的第 6 行那种）。

    真实 MESA 文件（``history.f90`` 在 pass 3 以 ``status='replace'`` 重写）是::

        序号行 / 表头名字行 / 表头值行 / 空行 / 序号行 / 数据列名行 / 数据行...

    因此优先取"表头之后的第二条序号行"的下一行；老式/简化文件（没有第二个
    序号行）则退回"表头值行之后第一条非纯数值行"。
    """
    for position in range(header_index + 3, len(rows)):
        if _index_line(rows[position].split()):
            return position + 1 if position + 1 < len(rows) else None
    for position in range(header_index + 3, len(rows)):
        tokens = rows[position].split()
        if tokens and not _is_value_line(tokens):
            return position
    return None


def parse_table(text: str) -> MesaTable:
    """解析一张 MESA 数据表（history 或 profile）。

    真实文件结构（用真实运行样本核对过，见 ``tests/fixtures/real_mesa/``）::

        第 1 行  序号行（表头项数 N）
        第 2 行  表头名字行
        第 3 行  表头值行        （字符串带双引号；浮点是 E 指数）
        第 4 行  空行
        第 5 行  序号行（数据列数 M）
        第 6 行  数据列名行
        第 7 行起 数据行

    ``history.f90`` 虽然写三帧表头，但 pass 3 会重开并重写文件，所以**最终
    只有一帧**。表头项数 N 与数据列数 M 通常不等。
    """
    lines = text.splitlines()
    rows = [line for line in lines if line.strip()]
    if len(rows) < 3:
        raise MesaLogError("文件至少需要序号行、名字行与值行")

    header_index = next(
        (position for position, line in enumerate(rows) if _index_line(line.split())),
        None,
    )
    if header_index is None:
        raise MesaLogError("找不到表头的序号行（1 2 3 ...）")
    if header_index + 2 >= len(rows):
        raise MesaLogError("表头不完整（缺名字行或值行）")

    names = rows[header_index + 1].split()
    values = rows[header_index + 2].split()
    header = dict(zip(names, values)) if len(names) == len(values) else {}

    columns_index = _columns_position(rows, header_index)
    if columns_index is None or columns_index >= len(rows):
        raise MesaLogError("找不到数据列名行")

    columns = rows[columns_index].split()
    if not columns:
        raise MesaLogError("列名行是空的")
    raw_rows = [line.split() for line in rows[columns_index + 1:]]
    if not raw_rows:
        raise MesaLogError("没有数据行")
    for row in raw_rows:
        if len(row) != len(columns):
            raise MesaLogError(
                f"数据行列数不符: 期望 {len(columns)}，实际 {len(row)}"
            )

    numeric: dict[str, tuple[float, ...]] = {}
    text_columns: dict[str, tuple[str, ...]] = {}
    for position, name in enumerate(columns):
        tokens = [row[position] for row in raw_rows]
        try:
            numeric[name] = tuple(_to_float(token) for token in tokens)
        except ValueError:
            text_columns[name] = tuple(tokens)
    return MesaTable(header=header, columns=numeric, text_columns=text_columns)


def read_file(path: str) -> MesaTable:
    """按 UTF-8 读取并解析一个 MESA 数据文件。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return parse_table(handle.read())
    except OSError as exc:
        raise MesaLogError(f"无法读取 {path}: {exc}") from None


def read_index(path: str) -> ProfileIndex:
    """读取 ``profiles.index``（真实文件首行是说明文字，其后每行三列整数）。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            lines = [line.split() for line in handle if line.strip()]
    except OSError as exc:
        raise MesaLogError(f"无法读取 {path}: {exc}") from None

    rows: list[tuple[int, int, int]] = []
    for tokens in lines:
        if len(tokens) != 3:
            continue  # 说明文字 / 空行
        try:
            rows.append(tuple(int(token) for token in tokens))  # type: ignore[arg-type]
        except ValueError:
            raise MesaLogError(f"profiles.index 出现非整数行: {tokens}") from None
    if not rows:
        raise MesaLogError(f"{path} 里没有有效的索引行")
    rows.sort(key=lambda row: row[0])  # 按模型号排序（与 mesa_reader 一致）
    return ProfileIndex(
        model_numbers=tuple(row[0] for row in rows),
        priorities=tuple(row[1] for row in rows),
        profile_numbers=tuple(row[2] for row in rows),
    )


def read_history(logs_dir: str) -> MesaTable:
    """读取 ``<logs_dir>/history.data``。"""
    return read_file(os.path.join(logs_dir, HISTORY_FILENAME))


def read_profile(logs_dir: str, profile_number: int) -> MesaTable:
    """读取 ``<logs_dir>/profile<N>.data``。"""
    name = f"{PROFILE_PREFIX}{int(profile_number)}.{PROFILE_SUFFIX}"
    return read_file(os.path.join(logs_dir, name))


class MesaLogDir:
    """一个 MESA ``LOGS/`` 目录（`history` + `profiles.index` + 剖面）。

    用法与 ``mesa_reader.MesaLogDir`` 对齐（``profile_data()`` 默认取最后一个
    剖面），但实现只依赖标准库，且能解析 ``D`` 指数。
    """

    def __init__(self, log_path: str) -> None:
        if not os.path.isdir(log_path):
            raise MesaLogError(f"{log_path} 不是目录")
        self.log_path = log_path
        history_path = os.path.join(log_path, HISTORY_FILENAME)
        index_path = os.path.join(log_path, INDEX_FILENAME)
        if not os.path.isfile(history_path):
            raise MesaLogError(f"{HISTORY_FILENAME} 不存在于 {log_path}")
        if not os.path.isfile(index_path):
            raise MesaLogError(f"{INDEX_FILENAME} 不存在于 {log_path}")
        self.history = read_file(history_path)
        self.profiles = read_index(index_path)
        self.profile_numbers = self.profiles.profile_numbers
        self.model_numbers = self.profiles.model_numbers
        self._memo: dict[int, MesaTable] = {}

    def profile_with_model_number(self, model_number: int) -> int:
        return self.profiles.profile_with_model_number(model_number)

    def profile_data(
        self, model_number: int | None = None, profile_number: int | None = None
    ) -> MesaTable:
        """取一份剖面数据（默认最后一个剖面，与 mesa_reader 相同）。"""
        if model_number is not None and int(model_number) != -1:
            number = self.profile_with_model_number(int(model_number))
        elif profile_number is not None and int(profile_number) != -1:
            number = int(profile_number)
        else:
            number = int(self.profile_numbers[-1])
        if number not in self._memo:
            self._memo[number] = read_profile(self.log_path, number)
        return self._memo[number]


def log_scale(values: Sequence[float]) -> tuple[float, ...]:
    """取十进制对数（供 loglog 绘图；非正值返回 ``nan``）。"""
    return tuple(math.log10(value) if value > 0 else math.nan for value in values)

"""按 MESA 手册解析项目的输出约定（core 层，仅标准库）。

**手册依据**（源码自带文档 ``docs/source/using_mesa/*.rst`` 与 ``star/defaults``）：

======================  =========================  ==============================
控制项                   默认值                      说明
======================  =========================  ==============================
``log_directory``        ``'LOGS'``                  history/profile 输出目录
``star_history_name``    ``'history.data'``          history 文件名
``photo_directory``      ``'photos'``                快照目录（``./re xNNN`` 用）
``profile_interval``     ``50``                      剖面写出间隔
``photo_interval``       ``50``                      快照间隔
``HR_file_dir``          ``'png'``                   pgstar 图片目录
``HR_file_prefix``       ``'hr_'``                   pgstar 图片前缀
``HR_file_flag``         ``.false.``                 是否**真的写文件**（默认只画窗口）
``HR_file_interval``     ``5``                       写文件间隔
======================  =========================  ==============================

这些**用户都能改**，而 IDE 原先把 ``LOGS``/``photos``/``hr`` 写死在多处 —— 用户改一个
名字，绘图/视频/重启就静默失效。本模块把"项目目录 → 实际输出路径"收拢成一处，
供绘图、视频、重启与 UI 共用。

解析方式是纯文本扫描：读 ``inlist``，顺着 ``extra_*_inlist_name`` 再读被引用的
文件，收集 ``name = value``（忽略注释、去引号、键名小写）。**不做完整 Fortran
namelist 解析**——对"读取几个控制项"这个用途足够，且无法解析时一律退回手册默认值。
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

logger = logging.getLogger(__name__)

#: 手册默认值
DEFAULT_LOG_DIR = "LOGS"
DEFAULT_HISTORY_NAME = "history.data"
DEFAULT_INDEX_NAME = "profiles.index"
DEFAULT_PROFILE_PREFIX = "profile"
DEFAULT_PHOTO_DIR = "photos"
DEFAULT_PNG_DIR = "png"
DEFAULT_PGSTAR_PREFIX = "hr"

#: 入口 inlist 与「转发其它 inlist」的键
ENTRY_INLIST = "inlist"
EXTRA_INLIST_KEYS = (
    "extra_star_job_inlist_name",
    "extra_controls_inlist_name",
    "extra_pgstar_inlist_name",
    "extra_eos_inlist_name",
    "extra_kap_inlist_name",
)

_ASSIGNMENT = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*(?:\([^)]*\))?)\s*=\s*([^!]*)")


def parse_namelist_values(text: str) -> dict[str, str]:
    """把 inlist 文本里的 ``name = value`` 收集成字典（键小写、值去引号/空白）。"""
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("!"):
            continue
        match = _ASSIGNMENT.match(line)
        if match is None:
            continue
        name = match.group(1).lower()
        raw = match.group(2).strip()
        # 复用同一行的注释：'myLOGS' ! 输出目录 → 只取引号内或空白前的内容
        if raw.startswith(("'", '"')):
            quote = raw[0]
            end = raw.find(quote, 1)
            value = raw[1:end] if end > 0 else raw.strip(quote)
        else:
            value = raw.split()[0] if raw.split() else ""
        values[name] = value
    return values


def _read_inlist_chain(project_dir: Path) -> dict[str, str]:
    """读取 ``inlist`` 及其 ``extra_*_inlist_name`` 引用到的文件（去重、防环）。"""
    values: dict[str, str] = {}
    pending = [ENTRY_INLIST]
    seen: set[str] = set()
    while pending:
        name = pending.pop(0)
        if name in seen or not name:
            continue
        seen.add(name)
        path = project_dir / name
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        parsed = parse_namelist_values(text)
        # 入口文件的值优先级最低：先收集，后面被引用的文件覆盖
        for key, value in parsed.items():
            values.setdefault(key, value)
        for key, value in parsed.items():
            if key.startswith(EXTRA_INLIST_KEYS):
                pending.append(value)
    return values


def _clean(value: str | None, default: str = "") -> str:
    """去空白与成对引号（调用方可能直接传 inlist 原文，如 ``'LOGS'``）。"""
    raw = str(value if value is not None else default).strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        raw = raw[1:-1].strip()
    return raw or default


def _as_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _as_bool(value: str | None) -> bool:
    return _clean(value).strip(".").lower() in {"true", "t", "yes", "1"}


def _resolve(project_dir: str, value: str | None, default: str) -> str:
    raw = _clean(value, default)
    return raw if os.path.isabs(raw) else os.path.join(project_dir, raw)


@dataclass(frozen=True)
class MesaOutputs:
    """一个 MESA 项目的实际输出路径约定。"""

    log_dir: str
    history_path: str
    index_path: str
    photo_dir: str
    png_dir: str
    pgstar_prefix: str
    profile_prefix: str
    pgstar_files_enabled: bool
    pgstar_file_interval: int | None
    photo_interval: int | None
    profile_interval: int | None = None
    values: Mapping[str, str] = field(default_factory=dict)

    def history_exists(self) -> bool:
        return os.path.isfile(self.history_path)

    def existing_photos(self) -> list[str]:
        """``photos/`` 里已有的快照名（排序后返回，便于 UI 列给用户挑）。"""
        try:
            names = [entry.name for entry in Path(self.photo_dir).iterdir() if entry.is_file()]
        except OSError:
            return []
        return sorted(names)


def resolve_outputs(
    project_dir: str | os.PathLike[str],
    *,
    values: Mapping[str, str] | None = None,
) -> MesaOutputs:
    """解析项目的输出约定；``values`` 为空时从项目 inlist 链里读。

    任何无法解析的项都退回 MESA 手册默认值（绝不抛异常）。
    """
    base = str(project_dir)
    if values is None:
        values = _read_inlist_chain(Path(base))
    values = {str(key).lower(): str(value) for key, value in values.items()}

    pgstar_prefix = _clean(values.get("hr_file_prefix"), DEFAULT_PGSTAR_PREFIX).rstrip("_")
    pgstar_prefix = pgstar_prefix or DEFAULT_PGSTAR_PREFIX

    return MesaOutputs(
        log_dir=_resolve(base, values.get("log_directory"), DEFAULT_LOG_DIR),
        history_path=os.path.join(
            _resolve(base, values.get("log_directory"), DEFAULT_LOG_DIR),
            _clean(values.get("star_history_name"), DEFAULT_HISTORY_NAME),
        ),
        index_path=os.path.join(
            _resolve(base, values.get("log_directory"), DEFAULT_LOG_DIR), DEFAULT_INDEX_NAME
        ),
        photo_dir=_resolve(base, values.get("photo_directory"), DEFAULT_PHOTO_DIR),
        png_dir=_resolve(base, values.get("hr_file_dir"), DEFAULT_PNG_DIR),
        pgstar_prefix=pgstar_prefix,
        profile_prefix=DEFAULT_PROFILE_PREFIX,
        pgstar_files_enabled=_as_bool(values.get("hr_file_flag")),
        pgstar_file_interval=_as_int(values.get("hr_file_interval")),
        photo_interval=_as_int(values.get("photo_interval")),
        profile_interval=_as_int(values.get("profile_interval")),
        values=dict(values),
    )


def inlist_files(project_dir: str | os.PathLike[str]) -> list[str]:
    """项目 inlist 链里的文件路径（供 UI 打开/检查，按阅读顺序）。"""
    base = Path(project_dir)
    found: list[str] = []
    for name in (ENTRY_INLIST, *EXTRA_INLIST_KEYS):
        candidate = base / name
        if name == ENTRY_INLIST and candidate.is_file():
            found.append(str(candidate))
    values = _read_inlist_chain(base)
    for key, value in values.items():
        if key.startswith(EXTRA_INLIST_KEYS):
            candidate = base / value
            if candidate.is_file() and str(candidate) not in found:
                found.append(str(candidate))
    return found


def pgstar_setup_hint(outputs: MesaOutputs) -> str | None:
    """pgstar 没开启"写文件"时给出的说明（手册要求的三个设置）。

    返回 ``None`` 表示已开启。文案直接告诉用户该往 ``inlist_pgstar`` 写什么。
    """
    if outputs.pgstar_files_enabled:
        return None
    return (
        "pgstar 目前没有写出图片文件（默认只画窗口）。\n"
        "请在 inlist_pgstar 的 &pgstar 里加入：\n"
        "    file_device = 'png'\n"
        "    HR_file_flag = .true.\n"
        "    HR_file_interval = 1     ! 数值越小帧越多\n"
        "（若在无显示环境运行，建议同时把 HR_win_flag 设为 .false.）"
    )


#: pgstar 实时绘图窗口对应的官方控制项（``star/defaults/pgstar.defaults``）。
#: 模板 inlist_pgstar 里已打开这两个窗口；本表用于"编译运行前询问"时统一开/关。
LIVE_WIN_KEYS: tuple[str, ...] = ("HR_win_flag", "TRho_Profile_win_flag")

_LIVE_ASSIGNMENT = re.compile(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*=\s*)([^!]*)")


def set_pgstar_live_windows(
    project_dir: str | os.PathLike[str],
    enable: bool,
    *,
    values: Mapping[str, str] | None = None,
) -> tuple[bool, str]:
    """开关 pgstar **实时绘图窗口**（官方指令：两个 ``*_win_flag`` 控制项）。

    MESA 官方方式：``pgstar_flag = .true.`` 且 inlist_pgstar 的 ``&pgstar`` 里
    ``HR_win_flag`` / ``TRho_Profile_win_flag`` 为 ``.true.`` 时，``./rn`` 会
    弹出 HR 图与内部剖面两个窗口，随计算逐步刷新；设为 ``.false.`` 则只运行
    不弹窗。本函数只改这两个官方控制项（存在则改值、缺失则补在 ``/`` 结束行
    之前），幂等：值已符合目标时不重写文件。

    返回 ``(是否成功, 说明)``；任何读取/写入问题都返回 False 与原因，不抛异常。
    """
    base = Path(project_dir)
    try:
        chain = values if values is not None else _read_inlist_chain(base)
        pgstar_name = _clean(chain.get("extra_pgstar_inlist_name"), "inlist_pgstar")
        path = base / pgstar_name
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return False, f"读取 pgstar inlist 失败: {exc}"
    if not path.is_file():
        return False, f"未找到 pgstar inlist: {path.name}（需要 extra_pgstar_inlist_name 指向的文件）"

    want = ".true." if enable else ".false."
    by_lower = {key.lower(): key for key in LIVE_WIN_KEYS}
    lines = text.rstrip("\n").splitlines()
    seen: set[str] = set()
    changed = False
    for index, line in enumerate(lines):
        match = _LIVE_ASSIGNMENT.match(line)
        if match and match.group(2).lower() in by_lower:
            seen.add(match.group(2).lower())
            if match.group(4).strip() != want:
                lines[index] = (
                    f"{match.group(1)}{match.group(2)}{match.group(3)}{want}"
                )
                changed = True

    missing = [name for key, name in by_lower.items() if key not in seen]
    if missing:
        block = [f"    {name} = {want}" for name in missing]
        end_index = next(
            (i for i, line in enumerate(lines) if line.lstrip().startswith("/")), None
        )
        lines = (
            lines[:end_index] + block + lines[end_index:]
            if end_index is not None
            else lines + block
        )
        changed = True

    if not changed:
        return True, f"{path.name} 实时绘图窗口已{'开启' if enable else '关闭'}（无需修改）"

    try:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as exc:
        return False, f"写入 {path.name} 失败: {exc}"
    return True, f"{path.name}：实时绘图窗口已{'开启' if enable else '关闭'}（HR 图 + 内部剖面）"

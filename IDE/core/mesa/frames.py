"""pgstar 图片帧序列的发现与校验（core 层，仅标准库）。

**手册依据**（MESA 26.4.1《Using PGSTAR》）：每个绘图各有
``*_file_dir`` / ``*_file_prefix`` / ``*_file_flag`` / ``*_file_interval``，默认
``file_device = 'png'``、``file_digits = 5``（文件名里模型号的位数），落盘为
``<dir>/<prefix>_<模型号>.png``，且该目录必须**事先存在**，否则 MESA 不写文件。

本模块只回答"目录里到底有哪些帧"，供 :mod:`core.video` 在启动 ffmpeg **之前**
校验；筛选规则与 ``-pattern_type glob`` 一致（``<prefix>_*<suffix>`` 按字典序），
所以"本模块找到几帧"就是"ffmpeg 会读到几帧"。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

DEFAULT_SUFFIX = ".png"

_NUMBERED = re.compile(r"^(?P<prefix>.*)_(?P<number>\d+)$")


def frame_pattern(prefix: str, suffix: str | None = DEFAULT_SUFFIX) -> str:
    """ffmpeg glob 与本模块共用的匹配式；``suffix=None`` 表示不限扩展名。"""
    return f"{prefix}_*{suffix or ''}"


def frame_number(name: str, prefix: str = "", suffix: str | None = DEFAULT_SUFFIX) -> int | None:
    """从文件名解析模型号；不是 ``<prefix>_<数字><suffix>`` 时返回 ``None``。"""
    if suffix and not name.endswith(suffix):
        return None
    stem = name[: len(name) - len(suffix)] if suffix else name
    match = _NUMBERED.match(stem)
    if match is None or (prefix and match.group("prefix") != prefix):
        return None
    return int(match.group("number"))


def _match_names(names: Iterable[str], prefix: str, suffix: str | None) -> tuple[str, ...]:
    """按 glob 语义挑帧名并按字典序排序（= ffmpeg 消费顺序）。"""
    head, tail = f"{prefix}_", suffix or ""
    return tuple(sorted(n for n in names if n.startswith(head) and n.endswith(tail)))


@dataclass(frozen=True)
class FrameSet:
    """一个目录里的帧序列（不可变，便于测试与跨语言移植）。"""

    directory: str
    prefix: str
    suffix: str | None = DEFAULT_SUFFIX
    files: tuple[str, ...] = ()

    @property
    def count(self) -> int:
        return len(self.files)

    @property
    def pattern(self) -> str:
        return frame_pattern(self.prefix, self.suffix)

    @property
    def numbers(self) -> tuple[int, ...]:
        """能解析出模型号的那些帧的模型号（与 ``files`` 同序）。"""
        parsed = (frame_number(name, self.prefix, self.suffix) for name in self.files)
        return tuple(number for number in parsed if number is not None)

    @property
    def order_matches_numbers(self) -> bool:
        """字典序是否与模型号顺序一致（不一致 → ffmpeg glob 会合成错序视频）。"""
        numbers = self.numbers
        return numbers == tuple(sorted(numbers))

    def describe(self) -> str:
        """给用户看的一句话（帧数 + 匹配式 + 模型号范围）。"""
        if not self.files:
            return f"未找到匹配 '{self.pattern}' 的图片"
        numbers = self.numbers
        if not numbers:
            return f"{self.count} 帧（{self.pattern}）"
        return f"{self.count} 帧（{self.pattern}，模型号 {numbers[0]}→{numbers[-1]}）"


def scan_frames(
    directory: str,
    prefix: str,
    suffix: str | None = DEFAULT_SUFFIX,
    *,
    listdir: Callable[[str], Sequence[str]] = os.listdir,
) -> FrameSet:
    """扫描目录里的帧；目录不存在/无权限时返回空集，**绝不抛异常**。"""
    try:
        names = listdir(directory)
    except OSError:
        return FrameSet(directory, prefix, suffix, ())
    return FrameSet(directory, prefix, suffix, _match_names(names, prefix, suffix))

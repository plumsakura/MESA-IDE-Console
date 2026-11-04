"""MESA 安装检测（core 层，仅标准库）。

对应用户要求"修改后的项目可以直接安装 MESA 项目（如果已安装就检查）"：

- 明确区分"环境变量已设置"与"该路径确实是一个可用的 MESA 安装"；
- **不做静默回退**：任何回退/失败原因都记录到 ``warnings`` 与 ``source``，
  由 UI 明确展示（原实现 `create_new_program.py:9-21` 会静默回退到 ~/mesa）；
- 通过注入 ``exists`` / ``env`` / ``fallbacks`` 实现零副作用测试。

需人工确认：``VERSION_FILES`` 中的版本文件名来自常见布局推测，
尚未在真实 MESA 安装上验证。
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping

# 判定"这是一个可用的 MESA 安装"的最小充分条件（相对 MESA_DIR）
REQUIRED_SUBDIRS: tuple[str, ...] = ("star/defaults",)

# 本 IDE 会用到、但缺失时只算警告的目录
EXPECTED_SUBDIRS: tuple[str, ...] = ("star/work", "star/test_suite")

# 候选安装位置（按优先级）。~ 会被展开。
FALLBACK_DIRS: tuple[str, ...] = ("~/mesa", "/opt/mesa")

#: 环境变量指向的路径无效时，额外扫描这些 glob 模式（~ 会被展开）。
#: 覆盖"MESA_DIR 过期/写错"的情形：安装器按 `~/mesa/mesa-<版本>` 布局，
#: 项目模板与参考项目（star/work、star/test_suite）都应该从这里定位。
GLOB_FALLBACK_PATTERNS: tuple[str, ...] = (
    "~/mesa/mesa-*",
    "~/mesa/*/mesa-*",  # 历史 bug 造成的双重嵌套布局
    "/opt/mesa/mesa-*",
)

ENV_VAR = "MESA_DIR"

SOURCE_ENV = f"env:{ENV_VAR}"
SOURCE_DEFAULT = "default"
SOURCE_GLOB = "auto"
SOURCE_NOT_FOUND = "not_found"

# 尽力读取版本号时尝试的相对路径（需人工确认）
VERSION_FILES: tuple[str, ...] = (
    "data/version_number",
    "version_number",
    "star/version_number",
)


@dataclass(frozen=True)
class MesaEnvironment:
    """一次 MESA 安装检测的结果（不可变，便于跨线程/跨语言传递）。"""

    mesa_dir: str | None
    source: str
    is_valid: bool
    missing: tuple[str, ...] = ()
    warnings: tuple[str, ...] = field(default=())

    def subdir(self, relative: str) -> str | None:
        """返回 MESA_DIR 下的相对子路径（mesa_dir 为空时返回 None）。"""
        if not self.mesa_dir:
            return None
        return os.path.join(self.mesa_dir, relative)

    @property
    def star_defaults(self) -> str | None:
        return self.subdir("star/defaults")

    @property
    def star_work(self) -> str | None:
        return self.subdir("star/work")

    @property
    def star_test_suite(self) -> str | None:
        return self.subdir("star/test_suite")

    def summary(self) -> str:
        """一行人类可读状态，供 UI 直接显示。"""
        if self.mesa_dir and self.is_valid:
            text = f"MESA 安装可用: {self.mesa_dir}（来源: {self.source}）"
        elif self.mesa_dir:
            text = f"MESA 安装不可用: {self.mesa_dir}（来源: {self.source}）"
        else:
            text = "未检测到 MESA 安装"
        if self.missing:
            text += f"；缺少目录: {', '.join(self.missing)}"
        return text


def validate_mesa_dir(
    mesa_dir: str,
    exists: Callable[[str], bool] = os.path.exists,
) -> tuple[bool, tuple[str, ...], tuple[str, ...]]:
    """校验某个路径是否是可用安装。

    返回 ``(is_valid, missing_required, missing_expected)``。
    """
    if not mesa_dir or not exists(mesa_dir):
        return False, tuple(REQUIRED_SUBDIRS), tuple(EXPECTED_SUBDIRS)

    missing_required = tuple(
        rel for rel in REQUIRED_SUBDIRS if not exists(os.path.join(mesa_dir, rel))
    )
    missing_expected = tuple(
        rel for rel in EXPECTED_SUBDIRS if not exists(os.path.join(mesa_dir, rel))
    )
    return (not missing_required), missing_required, missing_expected


def _glob_candidates(patterns: Iterable[str] | None = None) -> list[tuple[str, str]]:
    """按 glob 模式扫描磁盘上的 MESA 安装目录（真实文件系统）。"""
    selected = GLOB_FALLBACK_PATTERNS if patterns is None else patterns
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for pattern in selected:
        for path in sorted(glob.glob(os.path.expanduser(pattern))):
            if not os.path.isdir(path) or path.endswith(".mesa-ide-bak"):
                continue
            absolute = os.path.abspath(path)
            if absolute not in seen:
                seen.add(absolute)
                result.append((SOURCE_GLOB, absolute))
    return result


def candidates(
    env: Mapping[str, str] | None = None,
    fallbacks: Iterable[str] | None = None,
    glob_patterns: Iterable[str] | None = None,
) -> list[tuple[str, str]]:
    """返回候选 ``(source, path)`` 列表，顺序即优先级。

    顺序：环境变量 → 常规候选目录（``~/mesa``、``/opt/mesa``）→ 磁盘 glob
    扫描（``~/mesa/mesa-*`` 等）。glob 兜底解决"MESA_DIR 过期/写错、
    IDE 找不到参考项目位置"的问题。
    """
    env = os.environ if env is None else env
    fallback_dirs = tuple(FALLBACK_DIRS if fallbacks is None else fallbacks)

    result: list[tuple[str, str]] = []
    raw = (env.get(ENV_VAR) or "").strip()
    if raw:
        result.append((SOURCE_ENV, os.path.expanduser(raw)))
    for path in fallback_dirs:
        expanded = os.path.expanduser(path)
        if all(expanded != existing for _src, existing in result):
            result.append((SOURCE_DEFAULT, expanded))
    for source, path in _glob_candidates(glob_patterns):
        if all(path != existing for _src, existing in result):
            result.append((source, path))
    return result


def detect_mesa(
    env: Mapping[str, str] | None = None,
    exists: Callable[[str], bool] = os.path.exists,
    fallbacks: Iterable[str] | None = None,
    glob_patterns: Iterable[str] | None = None,
) -> MesaEnvironment:
    """按优先级探测 MESA 安装并给出结构化诊断（不静默回退）。"""
    env = os.environ if env is None else env
    tried = candidates(env, fallbacks, glob_patterns)
    warnings: list[str] = []

    for source, path in tried:
        is_valid, missing_required, _missing_expected = validate_mesa_dir(path, exists)
        if is_valid:
            _, _, missing_expected = validate_mesa_dir(path, exists)
            if missing_expected:
                warnings.append(f"MESA 安装缺少可选目录: {', '.join(missing_expected)}")
            return MesaEnvironment(
                mesa_dir=path,
                source=source,
                is_valid=True,
                missing=missing_expected,
                warnings=tuple(warnings),
            )
        if source == SOURCE_ENV:
            reason = "路径不存在" if not exists(path) else f"缺少 {', '.join(missing_required)}"
            warnings.append(f"{ENV_VAR} 指向的路径不是可用的 MESA 安装: {path}（{reason}）")
        elif exists(path):
            warnings.append(f"候选 MESA 安装不完整: {path}（缺少 {', '.join(missing_required)}）")

    if not warnings:
        warnings.append(f"未找到可用的 MESA 安装（已尝试: {', '.join(p for _s, p in tried)}）")

    fallback_path = tried[0][1] if tried else None
    fallback_source = tried[0][0] if tried else SOURCE_NOT_FOUND
    is_valid, missing_required, _ = validate_mesa_dir(fallback_path or "", exists)
    return MesaEnvironment(
        mesa_dir=fallback_path,
        source=fallback_source,
        is_valid=False,
        missing=missing_required,
        warnings=tuple(warnings),
    )


def read_version(mesa_dir: str | None, opener: Callable[..., object] | None = None) -> str | None:
    """尽力读取 MESA 版本号；读不到返回 None（不抛异常）。

    ``opener`` 默认为内置 ``open``，在调用时解析（便于测试替换）。

    需人工确认：``VERSION_FILES`` 的文件名未经真实安装验证。
    """
    if not mesa_dir:
        return None
    reader = open if opener is None else opener
    for relative in VERSION_FILES:
        path = os.path.join(mesa_dir, relative)
        try:
            with reader(path, "r", encoding="utf-8", errors="replace") as handle:  # type: ignore[union-attr]
                text = handle.read().strip()  # type: ignore[union-attr]
        except OSError:
            continue
        if text:
            return text.splitlines()[0].strip()
    return None

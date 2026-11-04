"""MESA 项目定位与模板复制（core 层，仅标准库）。

合并原实现中两份重复且返回键不一致的 ``get_mesa_paths``（P8）：

- ``create_new_program.py:9-21`` —— 5 个键（含 defaults/work）
- ``open_old_program.py:8-19``  —— 3 个键

并修复两处缺陷：

- **P21b**：``MESA_DIR`` 指向无效路径时不再静默回退（改由
  :func:`core.env.detect_mesa` 记录 ``warnings`` 并保留最佳猜测路径）；
- **路径穿越**：项目名原先直接 ``os.path.join(user_programs, name)``，
  形如 ``../../`` 的名字可写到用户项目目录之外。新增
  :func:`validate_project_name` 拒绝路径分隔符与 ``..``。
"""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from core.env import detect_mesa

logger = logging.getLogger(__name__)

#: 默认用户项目目录（可用环境变量覆盖）
DEFAULT_USER_PROGRAMS = "~/MESA_program"
USER_PROGRAMS_ENV = "MESA_PROGRAMS_DIR"

#: 从 star/defaults 补拷的列定义文件
DEFAULT_TEMPLATE_FILES: tuple[str, ...] = ("history_columns.list", "profile_columns.list")

#: IDE 启动时会尝试打开的核心 inlist 文件（原硬编码于 IDE.py:236,266,325）
CORE_INLIST_FILES: tuple[str, ...] = ("inlist", "inlist_pgstar", "inlist_project")

PNG_DIRNAME = "png"

_FORBIDDEN_NAMES = frozenset({".", ".."})


@dataclass(frozen=True)
class ProjectPaths:
    """一次路径解析结果（统一了原先两份实现的键集合）。"""

    mesa_dir: str | None
    defaults: str | None
    test_suite: str | None
    work: str | None
    user_programs: str
    source: str = "unknown"
    is_valid: bool = False
    warnings: tuple[str, ...] = field(default=())

    def as_legacy_dict(self) -> dict[str, str | None]:
        """旧接口兼容：返回原 ``create_new_program.get_mesa_paths()`` 的 5 个键。"""
        return {
            "mesa_dir": self.mesa_dir,
            "defaults": self.defaults,
            "test_suite": self.test_suite,
            "work": self.work,
            "user_programs": self.user_programs,
        }


def user_programs_dir(env: Mapping[str, str] | None = None) -> str:
    """用户项目根目录（``MESA_PROGRAMS_DIR`` 可覆盖，默认 ``~/MESA_program``）。"""
    source = os.environ if env is None else env
    raw = (source.get(USER_PROGRAMS_ENV) or "").strip() or DEFAULT_USER_PROGRAMS
    return os.path.expanduser(raw)


def project_paths(
    env: Mapping[str, str] | None = None,
    fallbacks: Iterable[str] | None = None,
    glob_patterns: Iterable[str] | None = None,
    exists: Callable[[str], bool] = os.path.exists,
) -> ProjectPaths:
    """统一的路径解析入口（MESA 安装 + 用户项目目录）。"""
    mesa = detect_mesa(env=env, exists=exists, fallbacks=fallbacks, glob_patterns=glob_patterns)
    return ProjectPaths(
        mesa_dir=mesa.mesa_dir,
        defaults=mesa.star_defaults,
        test_suite=mesa.star_test_suite,
        work=mesa.star_work,
        user_programs=user_programs_dir(env),
        source=mesa.source,
        is_valid=mesa.is_valid,
        warnings=mesa.warnings,
    )


def validate_project_name(name: str) -> str:
    """校验并返回规范化的项目名；非法时抛 :class:`ValueError`。"""
    cleaned = (name or "").strip()
    if not cleaned:
        raise ValueError("项目名不能为空")
    if cleaned in _FORBIDDEN_NAMES:
        raise ValueError(f"项目名不能是 {cleaned!r}")
    if "\x00" in cleaned:
        raise ValueError("项目名不能包含空字符")
    separators = {os.sep, os.altsep, "/", "\\"} - {None}
    if any(sep in cleaned for sep in separators):
        raise ValueError("项目名不能包含路径分隔符")
    return cleaned


def project_dir(user_programs: str, name: str) -> str:
    """返回 ``<用户项目目录>/<项目名>``（会先校验项目名）。"""
    return os.path.join(user_programs, validate_project_name(name))


# ---------------------------------------------------------------------------
# 模板复制
# ---------------------------------------------------------------------------

def copy_template_tree(
    source_dir: str,
    target_dir: str,
    *,
    exists: Callable[[str], bool] = os.path.exists,
    listdir: Callable[[str], list[str]] = os.listdir,
) -> list[str]:
    """把模板目录内容复制进目标目录（子目录合并、同名文件覆盖）。"""
    copied: list[str] = []
    if not exists(source_dir):
        logger.warning("模板目录不存在，跳过复制: %s", source_dir)
        return copied
    for item in listdir(source_dir):
        src = os.path.join(source_dir, item)
        dst = os.path.join(target_dir, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
        copied.append(item)
    return copied


def copy_default_columns(
    defaults_dir: str | None,
    target_dir: str,
    names: Sequence[str] = DEFAULT_TEMPLATE_FILES,
    *,
    exists: Callable[[str], bool] = os.path.exists,
) -> list[str]:
    """从 ``star/defaults`` 补拷列定义文件（**已存在的不覆盖**）。"""
    copied: list[str] = []
    if not defaults_dir:
        return copied
    for fname in names:
        src = os.path.join(defaults_dir, fname)
        dst = os.path.join(target_dir, fname)
        if exists(src) and not exists(dst):
            shutil.copy2(src, dst)
            copied.append(fname)
    return copied


def ensure_png_dir(
    target_dir: str,
    *,
    makedirs: Callable[..., None] = os.makedirs,
) -> str:
    """确保 ``png/`` 存在（MESA pgstar 输出目录），返回其路径。"""
    path = os.path.join(target_dir, PNG_DIRNAME)
    makedirs(path, exist_ok=True)
    return path


def create_project(
    name: str,
    template_dir: str,
    user_programs: str,
    defaults_dir: str | None = None,
    *,
    exists: Callable[[str], bool] = os.path.exists,
    makedirs: Callable[..., None] = os.makedirs,
) -> str:
    """完整创建流程：建目录 → 复制模板 → 补列定义 → 建 ``png/``。

    返回创建出的项目目录（绝对/展开后的路径）。
    """
    target = project_dir(user_programs, name)
    makedirs(target, exist_ok=True)
    copy_template_tree(template_dir, target, exists=exists)
    copy_default_columns(defaults_dir, target, exists=exists)
    ensure_png_dir(target, makedirs=makedirs)
    logger.info("已创建 MESA 项目: %s", target)
    return target


# ---------------------------------------------------------------------------
# 项目识别
# ---------------------------------------------------------------------------

def missing_core_inlists(
    directory: str,
    *,
    exists: Callable[[str], bool] = os.path.exists,
) -> tuple[str, ...]:
    """返回该目录缺失的核心 inlist 文件（用于打开项目时提示）。"""
    return tuple(name for name in CORE_INLIST_FILES if not exists(os.path.join(directory, name)))


def looks_like_mesa_project(
    directory: str,
    *,
    exists: Callable[[str], bool] = os.path.exists,
) -> bool:
    """是否像标准 MESA 项目（存在 ``inlist``）。"""
    return exists(os.path.join(directory, CORE_INLIST_FILES[0]))

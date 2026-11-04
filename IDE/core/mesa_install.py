"""MESA 安装与配置（core 层，仅标准库）。

对应用户要求"**安装我的软件的过程要完成安装 MESA、配置 MESA**"。本模块把
"要不要装/怎么装"（纯计算，可测）与"真的执行"（注入 ``runner``）分开：

- :func:`plan_mesa_install` 扫描本机已下载的 MESA 源码包与 MESA SDK 包，
  推断安装目录，并给出需要做哪几步（解压 SDK / 解压源码 / 编译）；
- :func:`run_extract`、:func:`run_build` 执行解压与 ``./install``，
  构建输出落盘到日志，失败只返回 ``False``（不抛异常）；
- :func:`env_lines`、:func:`write_env_file`、:func:`update_shell_rc`
  负责"配置 MESA"：生成可 source 的 ``mesa_env.sh``/``mesa_env.bat``，
  并（可选）把环境变量写进 ``~/.bashrc`` 的**标记块**（幂等、保留用户内容）。

**不打网络下载**：MESA 源码/SDK 体积很大（数百 MB 到数 GB），且内网环境常
无法访问外站；本模块只使用用户已下载到本机的归档，找不到时给出官方下载指引。
"""

from __future__ import annotations

import glob
import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)

#: 默认归档/安装位置（与原项目 README 的 `~/mesa` 习惯一致）
DEFAULT_ARCHIVE_DIRS: tuple[str, ...] = ("~/mesa", "~/Downloads", "~")
DEFAULT_SDK_ROOT = "~/mesasdk"
DEFAULT_MESA_ROOT = "~/mesa"

#: 归档文件名模式
SDK_ARCHIVE_PATTERNS: tuple[str, ...] = ("mesasdk-*.tar.gz", "mesasdk-*.tar.xz")
MESA_ARCHIVE_PATTERNS: tuple[str, ...] = (
    "mesa-*.zip",
    "mesa-*.tar.gz",
    "mesa-*.tar.xz",
)

#: 编译完成的标志（MESA `./install` 会导出 star 静态库）
BUILD_MARKER = "lib/libstar.a"

#: 生成的 env 脚本名
ENV_FILENAME_SH = "mesa_env.sh"
ENV_FILENAME_BAT = "mesa_env.bat"

#: `~/.bashrc` 标记块（便于幂等更新与人工识别）
RC_BEGIN = "# >>> MESA IDE: MESA environment >>>"
RC_END = "# <<< MESA IDE: MESA environment <<<"

#: 官方下载指引（找不到归档时打印）
DOWNLOAD_HINT = (
    "请先在本机准备好 MESA 源码包与 SDK 包（体积大，建议手动下载）：\n"
    "  MESA 源码: https://docs.mestastar.org/  → Download → mesa-<version>.zip\n"
    "  MESA SDK : https://www.mesastar.org/     → SDK → mesasdk-x86_64-linux-<ver>.tar.gz\n"
    "把两个文件放到 ~/mesa（或 ~/Downloads）后重新运行 install.py"
)


@dataclass(frozen=True)
class MesaArchive:
    """一个本机归档（源码 zip 或 SDK tar）。"""

    path: str
    kind: str  # "zip" | "tar"
    version: str | None = None


@dataclass(frozen=True)
class MesaInstallPlan:
    """一次 MESA 安装/配置计划（不可变，便于展示与测试）。"""

    mesa_dir: str
    sdk_root: str
    sdk_archive: MesaArchive | None
    mesa_archive: MesaArchive | None
    needs_sdk_extract: bool
    needs_mesa_extract: bool
    needs_build: bool
    already_installed: bool
    description: str
    #: 双重嵌套解压（历史 bug：把带顶层目录的归档解压进了目标目录）的修复来源；
    #: 非空表示需要把该目录提升为目标目录本身。
    repair_mesa_from: str | None = None
    repair_sdk_from: str | None = None

    @property
    def needs_extract(self) -> bool:
        return self.needs_sdk_extract or self.needs_mesa_extract

    @property
    def needs_repair(self) -> bool:
        return self.repair_mesa_from is not None or self.repair_sdk_from is not None

    @property
    def can_install(self) -> bool:
        """是否可以自动完成（归档齐全）。"""
        return bool(self.mesa_archive) and not (
            self.needs_sdk_extract and not self.sdk_archive
        )


_VERSION_RE = re.compile(r"\d+\.\d+(?:\.\d+)*")


def parse_version(name: str) -> str | None:
    """从文件名里取版本号（``mesa-24.08.1.zip`` → ``24.08.1``）。"""
    matches = _VERSION_RE.findall(os.path.basename(name))
    return matches[-1] if matches else None


def _archive_kind(path: str) -> str:
    return "zip" if path.lower().endswith(".zip") else "tar"


def find_archive(
    directories: Iterable[str],
    patterns: Sequence[str],
    *,
    exists: Callable[[str], bool] = os.path.exists,
) -> MesaArchive | None:
    """按目录顺序、模式顺序找第一个归档（先匹配到的目录优先）。"""
    for directory in directories:
        base = os.path.expanduser(str(directory))
        if not exists(base):
            continue
        for pattern in patterns:
            matches = sorted(glob.glob(os.path.join(base, pattern)))
            # 文件名里的版本号大者优先（同一目录内有多个版本时）
            matches.sort(key=lambda item: parse_version(item) or "", reverse=True)
            if matches:
                path = matches[0]
                return MesaArchive(path=path, kind=_archive_kind(path), version=parse_version(path))
    return None


def mesa_dir_for(mesa_root: str, archive: MesaArchive | None) -> str:
    """源码解压后的目录（归档内顶层目录名与归档同名）。"""
    base = os.path.expanduser(mesa_root)
    if archive is not None and archive.version:
        return os.path.join(base, f"mesa-{archive.version}")
    return os.path.join(base, "mesa")


def _nested_install_source(
    target_dir: str,
    marker_rel: str,
    *,
    exists: Callable[[str], bool] = os.path.exists,
    listdir: Callable[[str], list[str]] = os.listdir,
    isdir: Callable[[str], bool] = os.path.isdir,
) -> str | None:
    """检测"双重嵌套解压"：目标目录本身没有 ``marker_rel``，但其**唯一子目录**里有。

    旧版安装器把带顶层目录的归档（``mesa-24.08.1/`` / ``mesasdk/``）解压进
    目标目录，结果变成 ``~/mesa/mesa-24.08.1/mesa-24.08.1/...``。本函数找出
    应被"提升"的那个嵌套子目录；不满足条件（无嵌套、目标已有标记、不止一个
    子目录）时返回 ``None``。
    """
    if exists(os.path.join(target_dir, marker_rel)):
        return None
    try:
        entries = [name for name in listdir(target_dir) if name not in (".", "..")]
    except OSError:
        return None
    if len(entries) != 1:
        return None
    child = os.path.join(target_dir, entries[0])
    if isdir(child) and exists(os.path.join(child, marker_rel)):
        return child
    return None


def nested_install_sources(
    mesa_dir: str,
    sdk_root: str,
    *,
    exists: Callable[[str], bool] = os.path.exists,
    listdir: Callable[[str], list[str]] = os.listdir,
    isdir: Callable[[str], bool] = os.path.isdir,
) -> tuple[str | None, str | None]:
    """返回 ``(mesa 嵌套来源, sdk 嵌套来源)``（无嵌套则为 None）。"""
    mesa_source = _nested_install_source(
        mesa_dir, "install", exists=exists, listdir=listdir, isdir=isdir
    )
    sdk_source = _nested_install_source(
        os.path.expanduser(sdk_root),
        os.path.join("bin", "gfortran"),
        exists=exists,
        listdir=listdir,
        isdir=isdir,
    )
    return mesa_source, sdk_source


def plan_mesa_install(
    *,
    archive_dirs: Iterable[str] = DEFAULT_ARCHIVE_DIRS,
    sdk_root: str = DEFAULT_SDK_ROOT,
    mesa_root: str = DEFAULT_MESA_ROOT,
    exists: Callable[[str], bool] = os.path.exists,
    override_mesa_dir: str | None = None,
) -> MesaInstallPlan:
    """扫描本机归档与已有安装，给出安装计划。

    ``override_mesa_dir``：检测到的**有效源码目录**（可能来自 MESA_DIR，
    不在 ``mesa_root`` 下）——存在 ``install`` 脚本时直接作为构建目标，
    这样"源码已解压但尚未编译"的安装不会被误判为完成。
    """
    sdk_root_path = os.path.expanduser(sdk_root)
    sdk_archive = find_archive(archive_dirs, SDK_ARCHIVE_PATTERNS, exists=exists)
    mesa_archive = find_archive(archive_dirs, MESA_ARCHIVE_PATTERNS, exists=exists)
    if override_mesa_dir and exists(os.path.join(override_mesa_dir, "install")):
        mesa_dir = os.path.expanduser(override_mesa_dir)
    else:
        mesa_dir = mesa_dir_for(mesa_root, mesa_archive)

    repair_mesa_from, repair_sdk_from = nested_install_sources(mesa_dir, sdk_root_path, exists=exists)

    sdk_present = exists(os.path.join(sdk_root_path, "bin", "gfortran")) or repair_sdk_from is not None
    mesa_extracted = exists(os.path.join(mesa_dir, "install")) or repair_mesa_from is not None
    built = exists(os.path.join(mesa_dir, BUILD_MARKER))

    # "需要做的一步"= 缺什么 **且** 我们有办法做（归档在手）
    needs_sdk_extract = (not sdk_present) and sdk_archive is not None
    needs_mesa_extract = (not mesa_extracted) and mesa_archive is not None
    have_source = mesa_extracted or mesa_archive is not None
    can_build = have_source and (sdk_present or sdk_archive is not None)
    needs_build = (not built) and can_build
    already_installed = built and sdk_present

    if already_installed:
        description = f"MESA 已安装且已编译: {mesa_dir}"
    elif repair_mesa_from is not None or repair_sdk_from is not None:
        description = f"检测到历史解压目录嵌套，将自动修复（MESA: {mesa_dir}）"
    elif not mesa_archive and not mesa_extracted:
        description = "未找到 MESA 源码包，无法自动安装"
    elif needs_mesa_extract:
        description = f"需要解压 MESA 源码到 {mesa_dir}，然后编译"
    elif needs_build:
        description = f"源码已解压，需要编译 MESA（{mesa_dir}，耗时较长）"
    else:
        description = f"MESA 已就绪: {mesa_dir}"

    return MesaInstallPlan(
        mesa_dir=mesa_dir,
        sdk_root=sdk_root_path,
        sdk_archive=sdk_archive,
        mesa_archive=mesa_archive,
        needs_sdk_extract=needs_sdk_extract,
        needs_mesa_extract=needs_mesa_extract,
        needs_build=needs_build,
        already_installed=already_installed,
        description=description,
        repair_mesa_from=repair_mesa_from,
        repair_sdk_from=repair_sdk_from,
    )


def extract_argv(archive: MesaArchive, target_dir: str) -> list[str]:
    """解压命令（argv 列表，绝不 shell=True）。"""
    if archive.kind == "zip":
        return ["unzip", "-q", "-o", archive.path, "-d", target_dir]
    return ["tar", "-xzf", archive.path, "-C", target_dir]


def build_env(
    mesa_dir: str,
    sdk_root: str,
    *,
    base_env: Mapping[str, str] | None = None,
    nprocs: int | None = None,
) -> dict[str, str]:
    """构造 MESA 编译/运行所需环境变量（保留调用方原有环境）。"""
    env = dict(os.environ if base_env is None else base_env)
    env["MESA_DIR"] = mesa_dir
    env["MESASDK_ROOT"] = sdk_root
    env["PATH"] = os.path.join(sdk_root, "bin") + os.pathsep + env.get("PATH", "")
    env.setdefault("NPROCS", str(nprocs or min(os.cpu_count() or 4, 8)))
    env.setdefault("OMP_NUM_THREADS", "2")
    return env


def env_lines(
    mesa_dir: str, sdk_root: str, *, platform_system: str = "Linux"
) -> tuple[str, ...]:
    """配置 MESA 的环境变量行（Windows 用 ``set``，POSIX 用 ``export``）。"""
    if platform_system == "Windows":
        return (
            f'set MESA_DIR={mesa_dir}',
            f'set MESASDK_ROOT={sdk_root}',
            "set PATH=%MESASDK_ROOT%\\bin;%PATH%",
        )
    return (
        f'export MESA_DIR="{mesa_dir}"',
        f'export MESASDK_ROOT="{sdk_root}"',
        'export PATH="$MESASDK_ROOT/bin:$PATH"',
    )


def write_env_file(
    directory: str | os.PathLike[str],
    mesa_dir: str,
    sdk_root: str,
    *,
    platform_system: str = "Linux",
) -> str:
    """在 ``directory`` 生成 env 脚本（供启动器 source），返回其路径。"""
    base = Path(directory)
    base.mkdir(parents=True, exist_ok=True)
    if platform_system == "Windows":
        path = base / ENV_FILENAME_BAT
        content = (
            "@echo off\r\n"
            "rem 由 MESA IDE 安装器生成：MESA 环境变量\r\n"
            + "\r\n".join(env_lines(mesa_dir, sdk_root, platform_system="Windows"))
            + "\r\n"
        )
    else:
        path = base / ENV_FILENAME_SH
        content = (
            "#!/bin/bash\n"
            "# 由 MESA IDE 安装器生成：MESA 环境变量（可 source，也可被启动脚本引用）\n"
            + "\n".join(env_lines(mesa_dir, sdk_root))
            + "\n"
        )
    path.write_text(content, encoding="utf-8")
    if platform_system != "Windows":
        path.chmod(0o755)
    return str(path)


def update_shell_rc(
    rc_path: str | os.PathLike[str],
    mesa_dir: str,
    sdk_root: str,
    *,
    platform_system: str = "Linux",
) -> bool:
    """把环境变量写进 shell 启动文件的**标记块**；返回内容是否变化。

    幂等：同一份配置重复调用不会追加第二遍；路径变化时替换旧块；
    **不改动用户的其它配置**。
    """
    path = Path(rc_path)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    block = (
        RC_BEGIN
        + "\n"
        + "\n".join(env_lines(mesa_dir, sdk_root, platform_system=platform_system))
        + "\n"
        + RC_END
        + "\n"
    )

    if RC_BEGIN in existing and RC_END in existing:
        start = existing.index(RC_BEGIN)
        end = existing.index(RC_END) + len(RC_END) + 1
        updated = existing[:start] + block + existing[end:]
    else:
        separator = "" if not existing or existing.endswith("\n") else "\n"
        updated = existing + separator + "\n" + block

    if updated == existing:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8")
    return True


def run_extract(
    argv: Sequence[str], *, runner: Callable[..., object] = subprocess.run
) -> bool:
    """执行解压命令，返回是否成功（不抛异常）。"""
    try:
        completed = runner(list(argv), check=False)
    except OSError as exc:
        logger.error("解压失败 %s: %s", argv, exc)
        return False
    code = completed if isinstance(completed, int) else getattr(completed, "returncode", 0)
    if code != 0:
        logger.error("解压命令退出码 %s: %s", code, " ".join(str(part) for part in argv))
    return code == 0


def _remove_backup(
    backup: str, *, rmtree: Callable[[str], None] = shutil.rmtree
) -> None:
    """尽力删除上一次留下的备份目录（删不掉不影响主流程）。"""
    try:
        rmtree(backup)
    except OSError as exc:  # pragma: no cover - 权限不足等
        logger.warning("清理备份目录失败（可手动删除）%s: %s", backup, exc)


def extract_blockers(
    archive: MesaArchive,
    target_dir: str,
    *,
    access: Callable[[str, int], bool] = os.access,
    isdir: Callable[[str], bool] = os.path.isdir,
) -> tuple[str, ...]:
    """解压前预检：返回阻止解压的原因（空元组表示可以解压）。

    最常见的一种：归档是用户用 ``sudo`` / Windows 管理员方式复制进家目录的，
    于是目录属主变成 ``root``，普通用户既不能在其中建临时目录、也不能写入
    解压结果。这里给出**可复制的修复命令**，而不是让 Python 抛栈。
    """
    reasons: list[str] = []
    target_abs = os.path.abspath(target_dir)
    parent = os.path.dirname(target_abs) or "."

    probe = parent
    while probe and not isdir(probe):
        nxt = os.path.dirname(probe)
        if nxt == probe:
            break
        probe = nxt
    if not probe:
        reasons.append(f"找不到可用的上级目录: {parent}")
    elif not (access(probe, os.W_OK) and access(probe, os.X_OK)):
        owner_hint = f'sudo chown -R "$(id -un):$(id -gn)" {probe}'
        reasons.append(f"目录不可写: {probe}（修复: {owner_hint}）")

    if not access(archive.path, os.R_OK):
        reasons.append(
            f"归档不可读: {archive.path}（修复: sudo chmod a+r {archive.path}）"
        )
    return tuple(reasons)


def extract_into_target(
    archive: MesaArchive,
    target_dir: str,
    *,
    runner: Callable[..., object] = subprocess.run,
    staging_root: str | os.PathLike[str] | None = None,
    listdir: Callable[[str], list[str]] = os.listdir,
    isdir: Callable[[str], bool] = os.path.isdir,
    exists: Callable[[str], bool] = os.path.exists,
    move: Callable[[str, str], str] = shutil.move,
    rmtree: Callable[[str], None] = shutil.rmtree,
    makedirs: Callable[[str], None] = os.makedirs,
) -> bool:
    """把归档内容解压进 ``target_dir`` 本身（**修复双重嵌套 bug**）。

    MESA 源码 zip 与 SDK 包的顶层都是一个目录（``mesa-<版本>/`` 与 ``mesasdk/``）。
    直接 ``unzip -d <target_dir>`` 会得到 ``<target_dir>/mesa-<版本>/...`` 的
    双重嵌套，导致 ``star/defaults``、``bin/gfortran`` 都不在预期位置。

    本函数先解压到同盘的临时目录，再规范化：
    - 归档只有一个顶层目录 → 把它直接改名/移动到 ``target_dir``；
    - 归档是"平铺"内容 → 把临时目录整体移到 ``target_dir``。
    同盘移动是 rename，数 GB 内容也不会产生复制开销。目标已存在时先挪到
    ``<target>.mesa-ide-bak``，成功后再删除备份。
    """
    target_abs = os.path.abspath(target_dir)
    parent = os.path.dirname(target_abs)
    staging: str | None = None
    try:
        makedirs(parent, exist_ok=True)
        staging = tempfile.mkdtemp(
            prefix=".mesa-ide-extract-",
            dir=str(staging_root) if staging_root is not None else parent,
        )
        if not run_extract(extract_argv(archive, staging), runner=runner):
            return False
        entries = [name for name in listdir(staging) if name not in (".", "..")]
        if len(entries) == 1 and isdir(os.path.join(staging, entries[0])):
            source = os.path.join(staging, entries[0])
        else:
            source = staging

        backup = target_abs + ".mesa-ide-bak"
        had_target = exists(target_abs)
        if had_target:
            _remove_backup(backup, rmtree=rmtree)
            move(target_abs, backup)
        try:
            move(source, target_abs)
        except OSError:
            # 移动失败：尽量把旧的目录恢复原状
            if had_target and exists(backup) and not exists(target_abs):
                move(backup, target_abs)
            raise
        if had_target:
            _remove_backup(backup, rmtree=rmtree)
        return True
    except OSError as exc:
        # 目标目录不可写（例如归档是用 sudo/管理员复制进来的，属主变成 root）
        # 属于"用户能自己修"的问题：记录日志并给出原因，绝不抛栈。
        logger.error("解压 %s → %s 失败: %s", archive.path, target_abs, exc)
        return False
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def repair_nested_installs(
    mesa_dir: str,
    sdk_root: str,
    *,
    repair_mesa_from: str | None = None,
    repair_sdk_from: str | None = None,
    exists: Callable[[str], bool] = os.path.exists,
    listdir: Callable[[str], list[str]] = os.listdir,
    isdir: Callable[[str], bool] = os.path.isdir,
    move: Callable[[str, str], str] = shutil.move,
    rmtree: Callable[[str], None] = shutil.rmtree,
) -> tuple[bool, list[str]]:
    """修复已存在的双重嵌套解压，返回 ``(全部成功, 说明列表)``。

    只处理"目标目录下**只有**那个嵌套子目录"的安全情形；有其他内容时跳过
    并说明原因，避免误删用户文件。
    """
    repaired: list[str] = []
    results: list[bool] = []

    def _promote(target: str, source: str) -> tuple[bool, str]:
        target_abs = os.path.abspath(target)
        backup = target_abs + ".mesa-ide-bak"
        entries = [name for name in listdir(target_abs) if name not in (".", "..")]
        if len(entries) != 1 or not isdir(source):
            return False, f"{target_abs} 下不止嵌套目录，跳过自动修复（请人工整理）"
        # source 位于 target 内部：先把 target 改名成备份，再按相对路径取回 source
        relative = os.path.relpath(source, target_abs)
        if relative == "." or relative.startswith(".."):
            return False, f"嵌套目录不在目标目录内: {source}"
        if exists(backup):
            rmtree(backup)
        move(target_abs, backup)
        try:
            move(os.path.join(backup, relative), target_abs)
        except OSError:
            if exists(backup) and not exists(target_abs):
                move(backup, target_abs)
            raise
        rmtree(backup)
        return True, f"已将嵌套目录提升为 {target_abs}"

    if repair_mesa_from is not None:
        try:
            ok, message = _promote(mesa_dir, repair_mesa_from)
        except OSError as exc:
            ok, message = False, f"提升失败: {exc}"
        results.append(ok)
        repaired.append(message)
        logger.info("MESA 嵌套修复(%s): %s", ok, message)
    if repair_sdk_from is not None:
        try:
            ok, message = _promote(os.path.expanduser(sdk_root), repair_sdk_from)
        except OSError as exc:
            ok, message = False, f"提升失败: {exc}"
        results.append(ok)
        repaired.append(message)
        logger.info("SDK 嵌套修复(%s): %s", ok, message)
    return all(results) if results else True, repaired


def run_build(
    mesa_dir: str,
    sdk_root: str,
    *,
    runner: Callable[..., object] = subprocess.run,
    log_path: str | os.PathLike[str] | None = None,
    nprocs: int | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> bool:
    """在 ``mesa_dir`` 执行 ``./install``（输出落盘），返回是否成功。

    没有 ``install`` 脚本时直接失败，不调用 runner。
    """
    install_script = os.path.join(mesa_dir, "install")
    if not os.path.isfile(install_script):
        logger.error("找不到 MESA 安装脚本: %s", install_script)
        return False

    env = build_env(mesa_dir, sdk_root, nprocs=nprocs)
    if extra_env:
        env.update(extra_env)

    handle = None
    try:
        if log_path is not None:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            handle = open(log_path, "w", encoding="utf-8", errors="replace")  # noqa: SIM115
            stdout: object = handle
        else:
            stdout = None
        try:
            completed = runner(
                ["./install"],
                cwd=mesa_dir,
                env=env,
                stdout=stdout,
                stderr=subprocess.STDOUT if handle is not None else None,
                check=False,
            )
        except TypeError:
            # 注入的替身可能不接受 stdout/stderr
            completed = runner(["./install"], cwd=mesa_dir, env=env, check=False)
    except OSError as exc:
        logger.error("执行 MESA 编译失败: %s", exc)
        return False
    except KeyboardInterrupt:
        # Ctrl-C 中断编译：不是失败。源码与环境配置都已保留，
        # 重新运行安装器会跳过已完成的步骤，从编译继续。
        logger.info("MESA 编译被用户中断（Ctrl-C）；源码与环境配置已保留，重新运行安装器即可继续。")
        return False
    finally:
        if handle is not None:
            handle.close()

    code = completed if isinstance(completed, int) else getattr(completed, "returncode", 0)
    if code != 0:
        logger.error("MESA 编译失败（退出码 %s），日志: %s", code, log_path)
    return code == 0


def sdk_is_present(sdk_root: str, *, exists: Callable[[str], bool] = os.path.exists) -> bool:
    """SDK 是否已解压（有 gfortran 即可用）。"""
    return exists(os.path.join(os.path.expanduser(sdk_root), "bin", "gfortran"))


def which(program: str) -> str | None:
    """``shutil.which`` 的薄包装（便于注入/测试）。"""
    return shutil.which(program)

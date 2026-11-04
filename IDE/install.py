#!/usr/bin/env python3
"""MESA IDE 安装器：平台自检 → 系统依赖 → 虚拟环境 → Python 依赖 → MESA → 字体 → 数据 → 启动脚本 → 自检。

推荐入口（**空白 WSL2 / Linux** 一行搞定）::

    bash install.sh          # 先补齐 python3 / venv / tk，再调用本脚本
    python3 install.py       # 已经有 Python 环境时直接跑

本次重构（相对上一版）针对"从空白机器装起来"的失败点逐条加固：

- **平台自检**：识别发行版 / 架构 / 是否 WSL2 / 包管理器 / 图形显示，
  开头就把"这台机器是什么"讲清楚，后面的建议都按发行版给；
- **系统依赖**：先体检 Python ``venv``+``ensurepip``、``tkinter``、``unzip``、
  ``ffmpeg``；缺什么打印**本发行版对应的**修复命令，并在用户同意
  （``--yes`` 或 ``MESA_IDE_AGREE_SYSTEM_PACKAGES=1``）时用
  apt/dnf/yum/pacman/zypper/apk 自动补装 —— **绝不静默 sudo**；
- **虚拟环境自愈**：已有的 ``venv/`` 先体检（解释器能否执行、pip 在不在、
  Python 版本够不够）。从别的机器/系统拷来的 venv（软链失效、路径写死、
  Windows venv）会被识别并**重建**，而不是带着坏路径继续装；
- **依赖可离线**：随包带 ``wheels/`` 时 pip 自动 ``--find-links``
  （有网仍可补齐缺失包）；``--offline`` 则严格 ``--no-index`` 只吃本地 wheel；
- **CLI 开关**：``--yes / --no-mesa / --no-fonts / --no-system / --offline /
  --wheels / --check / --dry-run``，便于无人值守、离线与 CI；
- **装完自检**：最后逐条检查 venv 解释器、tkinter、matplotlib+mesa_reader、
  参数数据库、自带字体、启动脚本、MESA 环境、图形显示。

原有纪律保持不变：所有外部命令走 argv 列表（**不 ``shell=True``**）、
版本号只来自 :mod:`core.config`、失败给平台相关提示而不是崩栈、
"MESA 已安装就检查，未安装给指引"。
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from core.config import APP_NAME, __version__
from core.env import detect_mesa
from core.fonts import (
    BUNDLED_FONTS,
    build_font_plan,
    detect_cjk_fonts,
    detect_package_manager,
    ensure_bundled_fonts,
    install_font_package,
)
from core.mesa.terminal import is_wsl as detect_wsl
from core.mesa_install import (
    BUILD_MARKER,
    DEFAULT_ARCHIVE_DIRS,
    DEFAULT_MESA_ROOT,
    DEFAULT_SDK_ROOT,
    DOWNLOAD_HINT,
    build_env as mesa_build_env,
    extract_blockers,
    extract_into_target,
    plan_mesa_install,
    repair_nested_installs,
    run_build as mesa_run_build,
    update_shell_rc,
    write_env_file,
)

MIN_PYTHON = (3, 8)

#: 虚拟环境目录名（与原项目一致）
VENV_DIRNAME = "venv"
#: 依赖清单与随包 wheel 目录名
REQUIREMENTS_FILENAME = "requirements.txt"
WHEELS_DIRNAME = "wheels"
#: pip 输出日志（被打断时仍留证据；打包时按 *.log 排除）
PIP_LOG_FILENAME = "pip_install.log"
#: 参数数据库文件名（辅助自检）
DATABASE_FILENAME = "mesa_data.db"

#: 同意安装系统包的环境变量（与同意装 MESA / 字体包的两个变量风格一致）
ENV_AGREE_SYSTEM_PACKAGES = "MESA_IDE_AGREE_SYSTEM_PACKAGES"
#: 可选：pip 索引镜像（国内网络常用）
ENV_PIP_INDEX_URL = "MESA_IDE_PIP_INDEX_URL"

TRUE_WORDS = frozenset({"1", "y", "yes", "true", "是", "on"})
FALSE_WORDS = frozenset({"0", "n", "no", "false", "否", "off"})

SYM_OK = "✓"
SYM_WARN = "⚠"
SYM_ERR = "×"

RUN_SH_CONTENT = """#!/bin/bash
# MESA IDE 启动脚本（由 install.py 生成；自定位，可随目录移动 —— 不再硬编码安装路径）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 输出编码：C locale 下 Python 打印中文会报错，这里兜底成 UTF-8
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"

if [ ! -f venv/bin/activate ]; then
    echo "× 未找到虚拟环境: $SCRIPT_DIR/venv"
    echo "  请先运行: bash install.sh   或   python3 install.py"
    exit 1
fi

# shellcheck disable=SC1091
source venv/bin/activate

# 安装器生成的 MESA 环境（MESA_DIR / MESASDK_ROOT / PATH）
if [ -f "$SCRIPT_DIR/mesa_env.sh" ]; then
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/mesa_env.sh"
fi

if [ -z "${MESA_DIR:-}" ]; then
    echo ""
    echo "⚠ 警告: MESA_DIR 环境变量未设置"
    echo "  部分功能可能无法正常工作（python3 run_mesa.py 会给出详细诊断）"
    echo ""
fi

if [ "$(uname -s)" = "Linux" ] && [ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    echo "⚠ 未检测到图形显示（DISPLAY / WAYLAND_DISPLAY）"
    echo "  WSL2 需要 WSLg（Windows 11）或自行配置 X server，否则窗口无法显示"
fi

echo "启动 MESA IDE..."
python main.py
status=$?
deactivate || true
exit $status
"""

RUN_BAT_CONTENT = """@echo off
chcp 65001 > nul
cd /d "%~dp0"

if not exist venv\\Scripts\\activate.bat (
    echo × 未找到虚拟环境: %~dp0venv
    echo   请先运行: python install.py
    pause
    exit /b 1
)

call venv\\Scripts\\activate.bat

rem 安装器生成的 MESA 环境（MESA_DIR / MESASDK_ROOT / PATH）
if exist "%~dp0mesa_env.bat" call "%~dp0mesa_env.bat"

if "%MESA_DIR%"=="" (
    echo.
    echo ⚠ 警告: MESA_DIR 环境变量未设置
    echo   部分功能可能无法正常工作（python run_mesa.py 会给出详细诊断）
    echo.
)

echo 启动 MESA IDE...
python main.py
deactivate
pause
"""


# ---------------------------------------------------------------------------
# 输出小工具
# ---------------------------------------------------------------------------


def print_step(step: str, message: str) -> None:
    """打印格式化的步骤信息。"""
    print(f"\n[{step}] {message}")


def print_ok(message: str) -> None:
    print(f"{SYM_OK} {message}")


def print_warn(message: str) -> None:
    print(f"{SYM_WARN} {message}")


def print_error(message: str) -> None:
    print(f"{SYM_ERR} {message}")


def print_info(message: str) -> None:
    print(f"  {message}")


def run_command(argv: list[str], capture_output: bool = False):
    """执行命令（argv 列表，绝不经过 shell）。"""
    try:
        if capture_output:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            return result.returncode == 0, result.stdout, result.stderr
        result = subprocess.run(argv, check=False)
        return result.returncode == 0, "", ""
    except OSError as exc:
        return False, "", str(exc)


def parse_bool(value: str | None) -> bool | None:
    """把环境变量/输入解析成三态布尔（``None`` 表示"没表态"）。"""
    token = (value or "").strip().lower()
    if token in TRUE_WORDS:
        return True
    if token in FALSE_WORDS:
        return False
    return None


def parse_version_tuple(text: str) -> tuple[int, ...]:
    """从 ``"3.14"`` / ``"Python 3.14.4"`` 里取版本号元组。"""
    parts = re.findall(r"\d+", text or "")
    return tuple(int(part) for part in parts[:3])


# ---------------------------------------------------------------------------
# 平台自检
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HostInfo:
    """这台机器是什么（发行版 / 架构 / WSL / 包管理器）。"""

    system: str
    arch: str
    distro_id: str = ""
    distro_version: str = ""
    distro_name: str = ""
    is_wsl: bool = False
    package_manager: str | None = None

    @property
    def is_linux(self) -> bool:
        return self.system == "Linux"

    @property
    def is_windows(self) -> bool:
        return self.system == "Windows"

    def describe(self) -> str:
        parts = [f"{self.system}/{self.arch}"]
        label = self.distro_name or self.distro_id
        if label:
            if self.distro_version:
                label = f"{label} {self.distro_version}"
            parts.append(label)
        if self.is_wsl:
            parts.append("WSL2")
        parts.append(f"包管理器: {self.package_manager or '未识别'}")
        return "；".join(parts)


def read_os_release(path: str | os.PathLike[str] = "/etc/os-release") -> dict[str, str]:
    """读 ``/etc/os-release``（读不到就返回空表，绝不抛异常）。"""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    data: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def detect_host(
    *,
    system: str | None = None,
    arch: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
    os_release: Mapping[str, str] | None = None,
    wsl: bool | None = None,
) -> HostInfo:
    """探测宿主平台（全部依赖可注入，便于离线测试）。"""
    resolved_system = system or platform.system()
    resolved_arch = arch or platform.machine() or "unknown"
    release = dict(read_os_release() if os_release is None else os_release)
    in_wsl = detect_wsl() if wsl is None else bool(wsl)
    return HostInfo(
        system=resolved_system,
        arch=resolved_arch,
        distro_id=release.get("ID", ""),
        distro_version=release.get("VERSION_ID", ""),
        distro_name=release.get("NAME", "") or release.get("ID", ""),
        is_wsl=in_wsl,
        package_manager=detect_package_manager(which=which),
    )


def display_status(
    *,
    system: str | None = None,
    env: Mapping[str, str] | None = None,
    is_wsl: bool = False,
) -> tuple[bool, str]:
    """图形显示是否可用（Linux/WSL 下有 DISPLAY 或 WAYLAND_DISPLAY 才算）。"""
    source = os.environ if env is None else env
    resolved = system or platform.system()
    if resolved in {"Windows", "Darwin"}:
        return True, "桌面系统，图形界面可用"
    display = (source.get("DISPLAY") or "").strip()
    wayland = (source.get("WAYLAND_DISPLAY") or "").strip()
    if display or wayland:
        return True, f"检测到图形显示（{'DISPLAY' if display else 'WAYLAND_DISPLAY'}={display or wayland}）"
    if is_wsl:
        return False, "WSL2 未检测到 DISPLAY：需要 WSLg（Windows 11）或自行配置 X server"
    return False, "未检测到 DISPLAY（无头环境）：装完可用命令行/测试，GUI 需要 X11"


# ---------------------------------------------------------------------------
# Python / 系统依赖体检
# ---------------------------------------------------------------------------

#: 缺了就跑不起图形界面的依赖
REQUIRED_DEPS: tuple[str, ...] = ("venv", "tkinter")
#: 缺了只影响部分能力的依赖
OPTIONAL_DEPS: tuple[str, ...] = ("unzip", "make", "zlib", "ffmpeg")

DEP_TITLES: Mapping[str, str] = {
    "python3": "Python 3 解释器",
    "venv": "Python venv + ensurepip（创建虚拟环境）",
    "tkinter": "tkinter（图形界面）",
    "unzip": "unzip（解压 MESA 源码 zip）",
    "make": "make 与 C 开发环境（编译 MESA 必需；空白系统常见缺失）",
    "zlib": "zlib 开发头文件（编译 MESA forum 库必需）",
    "ffmpeg": "ffmpeg（pgstar 帧合成视频）",
}

#: 各发行版对应的包名（按"依次尝试，成功为止"的顺序）
_PREREQ_TABLE: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "apt": {
        "python3": ("python3",),
        "tkinter": ("python3-tk",),
        "unzip": ("unzip",),
        "make": ("build-essential", "make"),
        "zlib": ("zlib1g-dev",),
        "ffmpeg": ("ffmpeg",),
    },
    "dnf": {
        "python3": ("python3",),
        "venv": ("python3-libs",),
        "tkinter": ("python3-tkinter",),
        "unzip": ("unzip",),
        "make": ("@Development Tools", "make", "glibc-devel"),
        "zlib": ("zlib-devel",),
        "ffmpeg": ("ffmpeg",),
    },
    "yum": {
        "python3": ("python3",),
        "venv": ("python3-libs",),
        "tkinter": ("python3-tkinter",),
        "unzip": ("unzip",),
        "make": ("base-devel", "make"),
        "zlib": ("zlib",),
        "ffmpeg": ("ffmpeg",),
    },
    "pacman": {
        "python3": ("python",),
        "venv": ("python",),
        "tkinter": ("tk",),
        "unzip": ("unzip",),
        "make": ("make",),
        "zlib": ("zlib-devel",),
        "ffmpeg": ("ffmpeg",),
    },
    "zypper": {
        "python3": ("python3",),
        "venv": ("python3",),
        "tkinter": ("python3-tk",),
        "unzip": ("unzip",),
        "make": ("build-base", "make"),
        "zlib": ("zlib-dev",),
        "ffmpeg": ("ffmpeg",),
    },
    "apk": {
        "python3": ("python3",),
        "venv": ("py3-virtualenv", "py3-pip", "python3"),
        "tkinter": ("py3-tkinter",),
        "unzip": ("unzip",),
        "make": ("make",),
        "zlib": ("zlib",),
        "ffmpeg": ("ffmpeg",),
    },
    "brew": {
        "python3": ("python",),
        "venv": ("python",),
        "tkinter": ("python-tk",),
        "unzip": ("unzip",),
        "ffmpeg": ("ffmpeg",),
    },
}

#: 各包管理器的安装/更新 argv（包名追加在末尾）
_PREREQ_INSTALL_ARGV: Mapping[str, tuple[str, ...]] = {
    "apt": ("sudo", "apt-get", "install", "-y"),
    "dnf": ("sudo", "dnf", "install", "-y"),
    "yum": ("sudo", "yum", "install", "-y"),
    "pacman": ("sudo", "pacman", "-S", "--noconfirm"),
    "zypper": ("sudo", "zypper", "install", "-y"),
    "apk": ("sudo", "apk", "add"),
    "brew": ("brew", "install"),
}

_PREREQ_UPDATE_ARGV: Mapping[str, tuple[str, ...]] = {
    "apt": ("sudo", "apt-get", "update"),
    "zypper": ("sudo", "zypper", "refresh"),
    "apk": ("sudo", "apk", "update"),
}


def check_python_version(current: tuple[int, ...] = sys.version_info) -> bool:
    """检查 Python 版本是否满足最低要求。"""
    return tuple(current[:2]) >= MIN_PYTHON


def venv_failure_hint(python_version: tuple[int, ...]) -> str:
    """venv 创建失败时的平台相关提示（Debian/Ubuntu 需额外装 venv 包）。"""
    major, minor = python_version[0], python_version[1]
    system = platform.system()
    if system == "Linux":
        return (
            "  提示: Debian/Ubuntu 需要先安装 venv 支持：\n"
            f"    sudo apt install python{major}.{minor}-venv\n"
            f"  也可以直接用仓库自带的引导脚本（会自动补包）：\n"
            "    bash install.sh\n"
            "  其它发行版: Fedora/RHEL 用 sudo dnf install python3-libs；"
            "Arch 用 sudo pacman -S python；openSUSE 用 sudo zypper install python3\n"
            "  然后重新运行 python3 install.py"
        )
    return "  提示: 请确认 Python 安装包含 venv 模块后重试。"


def module_available(
    module: str,
    *,
    python: str | os.PathLike[str] | None = None,
    runner: Callable[..., object] | None = None,
) -> bool:
    """指定解释器能否 ``import`` 某模块（含 tkinter 这类原生扩展）。"""
    execute = run_command if runner is None else runner
    interpreter = str(python or sys.executable)
    ok, _out, _err = execute([interpreter, "-c", f"import {module}"], capture_output=True)
    return bool(ok)


def check_venv_support(
    python: str | os.PathLike[str] | None = None,
    *,
    runner: Callable[..., object] | None = None,
) -> bool:
    """解释器是否具备建 venv 的能力（``venv`` + ``ensurepip``）。

    Debian/Ubuntu 把 ``ensurepip`` 拆到 ``pythonX.Y-venv`` 包里，缺了就会
    出现原项目 ``problem.txt`` 记录的 "ensurepip is not available"。
    """
    execute = run_command if runner is None else runner
    interpreter = str(python or sys.executable)
    ok, _out, _err = execute(
        [interpreter, "-c", "import venv, ensurepip"], capture_output=True
    )
    return bool(ok)


def zlib_dev_present() -> bool:
    """本机是否有 zlib 开发头文件（编译 MESA forum 库需要 -lz 与 zlib.h）。"""
    for candidate in (
        "/usr/include/zlib.h",
        "/usr/local/include/zlib.h",
        "/opt/homebrew/include/zlib.h",
        "/usr/include/x86_64-linux-gnu/zlib.h",
    ):
        if os.path.exists(candidate):
            return True
    return shutil.which("pkg-config") is not None and run_command(
        ["pkg-config", "--exists", "zlib"], capture_output=True
    )[0]


def detect_missing_deps(
    *,
    python: str | os.PathLike[str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., object] | None = None,
) -> list[str]:
    """返回这台机器上缺失的依赖键（``REQUIRED_DEPS`` + ``OPTIONAL_DEPS`` 的子集）。"""
    interpreter = python or sys.executable
    missing: list[str] = []
    if not check_venv_support(interpreter, runner=runner):
        missing.append("venv")
    if not module_available("tkinter", python=interpreter, runner=runner):
        missing.append("tkinter")
    if which("unzip") is None:
        missing.append("unzip")
    if which("make") is None:
        missing.append("make")
    if not zlib_dev_present():
        missing.append("zlib")
    if which("ffmpeg") is None:
        missing.append("ffmpeg")
    return missing


def describe_missing_deps(missing: Sequence[str]) -> tuple[list[str], list[str]]:
    """把缺失依赖分成 (必需, 推荐) 两组标题。"""
    required = [DEP_TITLES.get(key, key) for key in missing if key in REQUIRED_DEPS]
    optional = [DEP_TITLES.get(key, key) for key in missing if key in OPTIONAL_DEPS]
    return required, optional


@dataclass(frozen=True)
class PrereqGroup:
    """一个待补的系统依赖（同名包可能有多个候选名）。"""

    key: str
    title: str
    candidates: tuple[str, ...]
    required: bool = True


@dataclass(frozen=True)
class PrereqPlan:
    """系统包补装计划（纯数据，可打印、可测试）。"""

    manager: str
    description: str
    groups: tuple[PrereqGroup, ...]
    install_argv: tuple[str, ...]
    update_argv: tuple[str, ...] = ()

    @property
    def packages(self) -> tuple[str, ...]:
        return tuple(candidate for group in self.groups for candidate in group.candidates)


def build_prereq_plan(
    host: HostInfo, missing: Sequence[str], *, python_version: tuple[int, ...] | None = None
) -> PrereqPlan | None:
    """按发行版给出补装计划；无法自动补装时返回 ``None``。"""
    manager = host.package_manager
    if manager is None or manager not in _PREREQ_TABLE:
        return None
    table = _PREREQ_TABLE[manager]
    version = tuple(python_version or sys.version_info)[:2]
    groups: list[PrereqGroup] = []
    for key in missing:
        if key == "venv" and manager == "apt":
            candidates = (f"python{version[0]}.{version[1]}-venv", "python3-venv")
        else:
            candidates = table.get(key, ())
        if not candidates:
            continue
        groups.append(
            PrereqGroup(
                key=key,
                title=DEP_TITLES.get(key, key),
                candidates=tuple(candidates),
                required=key in REQUIRED_DEPS,
            )
        )
    if not groups:
        return None
    requires_root = _PREREQ_INSTALL_ARGV[manager][:1] == ("sudo",)
    return PrereqPlan(
        manager=manager,
        description=(
            f"用 {manager} 安装缺失的系统包"
            + ("（会调用 sudo，需要你输入密码）" if requires_root else "（不需要 sudo）")
        ),
        groups=tuple(groups),
        install_argv=_PREREQ_INSTALL_ARGV[manager],
        update_argv=_PREREQ_UPDATE_ARGV.get(manager, ()),
    )


def system_packages_consent(
    plan: PrereqPlan,
    *,
    interactive: bool | None = None,
    input_fn: Callable[[str], str] = input,
    env: Mapping[str, str] | None = None,
) -> bool:
    """是否执行系统包安装？三档：环境变量 > 交互提问 > 非交互默认否。"""
    source = os.environ if env is None else env
    override = parse_bool(source.get(ENV_AGREE_SYSTEM_PACKAGES))
    if override is not None:
        return override
    if interactive is None:
        interactive = sys.stdin.isatty()
    if not interactive:
        return False
    packages = ", ".join(group.candidates[0] for group in plan.groups)
    answer = input_fn(f"  是否现在安装系统依赖（{plan.manager}: {packages}）？[y/N] ")
    return answer.strip().lower() in {"y", "yes", "是"}


def install_prereq_packages(
    plan: PrereqPlan,
    *,
    runner: Callable[..., object] | None = None,
    recheck: Callable[[str], bool] | None = None,
) -> list[str]:
    """按计划补装系统包，返回**仍未满足**的依赖键。

    候选包名依次尝试；每装成功一个就重新体检一次，避免"装上了但没解决"
    被误判为成功（同一个能力在不同发行版里包名千差万别）。
    """
    execute = subprocess.run if runner is None else runner
    if plan.update_argv:
        print_info(f"更新软件源: {' '.join(plan.update_argv)}")
        try:
            execute(list(plan.update_argv), check=False)
        except OSError as exc:
            print_warn(f"更新软件源失败（继续尝试安装）: {exc}")

    unresolved: list[str] = []
    for group in plan.groups:
        if recheck is not None and recheck(group.key):
            print_info(f"{group.title} 已满足，跳过")
            continue
        satisfied = False
        for package in group.candidates:
            argv = [*plan.install_argv, package]
            print_info(f"尝试: {' '.join(argv)}")
            try:
                completed = execute(argv, check=False)
            except OSError as exc:
                print_warn(f"执行失败: {exc}")
                continue
            code = completed if isinstance(completed, int) else getattr(completed, "returncode", 0)
            if code != 0:
                print_warn(f"{package} 安装失败（退出码 {code}）")
                continue
            if recheck is None or recheck(group.key):
                print_ok(f"{group.title} 已就绪（{package}）")
                satisfied = True
                break
            print_warn(f"{package} 装好了但 {group.key} 仍不可用，继续尝试其它包名")
        if not satisfied:
            unresolved.append(group.key)
    return unresolved


# ---------------------------------------------------------------------------
# 虚拟环境（创建 + 自愈）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VenvStatus:
    """一次虚拟环境体检结果。"""

    exists: bool
    usable: bool
    reason: str
    python: str = ""
    version: tuple[int, ...] = ()

    def describe(self) -> str:
        if not self.exists:
            return "虚拟环境不存在"
        if self.usable:
            version = ".".join(str(part) for part in self.version) or "未知"
            return f"虚拟环境可用（Python {version}）"
        return f"虚拟环境不可用: {self.reason}"


def venv_python_path(venv_dir: str | os.PathLike[str], *, system: str | None = None) -> Path:
    """虚拟环境里的解释器路径（Windows 走 ``Scripts``）。"""
    base = Path(venv_dir)
    if (system or platform.system()) == "Windows":
        return base / "Scripts" / "python.exe"
    return base / "bin" / "python"


def venv_looks_like_venv(venv_dir: str | os.PathLike[str], *, system: str | None = None) -> bool:
    """目录是否"像是"一个虚拟环境（用于决定能否安全重建）。"""
    base = Path(venv_dir)
    if (base / "pyvenv.cfg").is_file():
        return True
    return venv_python_path(base, system=system).exists() and (base / "lib").is_dir()


def inspect_venv(
    venv_dir: str | os.PathLike[str],
    *,
    system: str | None = None,
    runner: Callable[..., object] | None = None,
    minimum: tuple[int, ...] = MIN_PYTHON,
) -> VenvStatus:
    """体检已有虚拟环境：解释器能不能跑、pip 在不在、版本够不够。

    这一步是"打包分发"的关键：把 IDE 目录拷到另一台机器后，``venv/`` 里
    写死的绝对路径会失效（软链指向不存在的解释器），必须能识别出来。
    """
    execute = run_command if runner is None else runner
    base = Path(venv_dir)
    if not base.exists():
        return VenvStatus(exists=False, usable=False, reason="虚拟环境不存在")
    python = venv_python_path(base, system=system)
    if not python.exists():
        return VenvStatus(
            exists=True, usable=False, reason=f"缺少解释器 {python.name}（路径已失效）"
        )
    ok, out, _err = execute(
        [str(python), "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
        capture_output=True,
    )
    if not ok:
        return VenvStatus(
            exists=True, usable=False, reason="解释器无法执行（多见于跨机器/跨系统拷贝来的环境）"
        )
    version = parse_version_tuple(out)
    if version and version < tuple(minimum):
        return VenvStatus(
            exists=True,
            usable=False,
            reason=f"Python {'.'.join(map(str, version))} 低于最低要求 "
            f"{minimum[0]}.{minimum[1]}",
            python=str(python),
            version=version,
        )
    ok_pip, _out, _err = execute([str(python), "-m", "pip", "--version"], capture_output=True)
    if not ok_pip:
        return VenvStatus(
            exists=True, usable=False, reason="venv 里没有可用的 pip", python=str(python)
        )
    return VenvStatus(
        exists=True, usable=True, reason="可用", python=str(python), version=version
    )


def ensure_venv(
    venv_dir: str | os.PathLike[str],
    *,
    system: str | None = None,
    python: str | os.PathLike[str] | None = None,
    runner: Callable[..., object] | None = None,
    dry_run: bool = False,
) -> tuple[bool, str]:
    """确保虚拟环境可用：能用就沿用，坏了就重建，没有就新建。

    返回 ``(是否成功, 说明)``；失败时说明里是给用户看的修复建议。
    """
    base = Path(venv_dir)
    status = inspect_venv(venv_dir, system=system, runner=runner)
    if status.usable:
        return True, status.describe()
    if dry_run:
        if status.exists:
            return True, f"[dry-run] 将重建虚拟环境（原因：{status.reason}）"
        return True, "[dry-run] 将创建虚拟环境"

    if base.exists():
        print_warn(f"已有的虚拟环境不可用：{status.reason}")
        if not venv_looks_like_venv(base, system=system):
            return False, f"{base} 已存在但不像虚拟环境，请先手动移走再安装"
        print_info(f"重建虚拟环境（删除 {base}）")
        try:
            shutil.rmtree(base)
        except OSError as exc:
            return False, f"删除旧虚拟环境失败: {exc}"

    interpreter = str(python or sys.executable)
    print_info(f"用 {interpreter} 创建虚拟环境: {base}")
    ok_create, _out, err = run_command([interpreter, "-m", "venv", str(base)], capture_output=True)
    if not ok_create:
        detail = (err or "").strip() or "未知错误"
        return False, f"创建虚拟环境失败: {detail}"
    status = inspect_venv(venv_dir, system=system, runner=runner)
    if not status.usable:
        return False, f"新建的虚拟环境仍不可用: {status.reason}"
    return True, status.describe()


# ---------------------------------------------------------------------------
# Python 依赖（在线 / 离线 wheels）
# ---------------------------------------------------------------------------


def find_wheels_dir(*candidates: str | os.PathLike[str] | None) -> Path | None:
    """在候选目录里找带 ``*.whl`` 的那个（随包的 wheels/ 或 --wheels 指定）。"""
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_dir() and any(path.glob("*.whl")):
            return path
    return None


def pip_install_commands(
    python: str | os.PathLike[str],
    requirements: str | os.PathLike[str],
    *,
    wheels_dir: str | os.PathLike[str] | None = None,
    offline: bool = False,
    upgrade_pip: bool = True,
    env: Mapping[str, str] | None = None,
) -> list[list[str]]:
    """构造依赖安装命令序列（argv 列表；不拼 shell 字符串）。"""
    source = os.environ if env is None else env
    interpreter = str(python)
    commands: list[list[str]] = []
    if upgrade_pip and not offline:
        commands.append([interpreter, "-m", "pip", "install", "--upgrade", "pip"])

    argv = [interpreter, "-m", "pip", "install"]
    # 弱网/丢包环境下提升容错：更多重试、更长超时、失败后跳过已下载的坏缓存。
    # （真实故障：某次验证中 pip 下载 matplotlib 到 6/16.7 MB 后反复中断，
    #  exit code 3 "incomplete-download"，明确提示与网络相关。）
    argv += ["--retries", "12", "--timeout", "90"]
    if offline:
        argv.append("--no-index")
    if wheels_dir is not None:
        argv += ["--find-links", str(wheels_dir)]
    index_url = (source.get(ENV_PIP_INDEX_URL) or "").strip()
    if index_url and not offline:
        argv += ["--index-url", index_url]
    argv += ["-r", str(requirements)]
    commands.append(argv)
    return commands


def dependencies_importable(
    python: str | os.PathLike[str], *, runner: Callable[..., object] | None = None
) -> bool:
    """依赖是否**真的能导入** —— 这是比 pip 退出码更可信的判据。

    真实世界里见过 pip 把包装完却以非 0 退出的情形（进程被环境信号打断、
    缓冲输出全丢，看着像"未知原因"）。装完能 import 就算成功。
    """
    return module_available("matplotlib, mesa_reader", python=python, runner=runner)


def run_pip_command(
    argv: Sequence[str],
    *,
    log_path: str | os.PathLike[str] | None = None,
    runner: Callable[..., object] | None = None,
) -> tuple[bool, int, str]:
    """执行一条 pip 命令，返回 ``(是否成功, 退出码, 输出尾部)``。

    - 输出**落盘**到 ``log_path``：pip 若被打断/杀掉，证据仍在文件里，
      不会像管道那样"什么都没留下"；
    - ``stdin`` 接 ``/dev/null``：pip 永远不可能卡在等输入上。
    """
    execute = subprocess.run if runner is None else runner
    if log_path is not None:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
    handle = None
    try:
        if log_path is not None:
            handle = open(log_path, "a", encoding="utf-8", errors="replace")  # noqa: SIM115
            handle.write(f"\n$ {' '.join(str(part) for part in argv)}\n")
            handle.flush()
        stdout_target = handle if handle is not None else subprocess.DEVNULL
        try:
            completed = execute(
                list(argv),
                stdin=subprocess.DEVNULL,
                stdout=stdout_target,
                stderr=subprocess.STDOUT,
                check=False,
            )
        except TypeError:
            # 注入的替身可能不接受这些关键字
            completed = execute(list(argv), check=False)
    except OSError as exc:
        return False, -1, str(exc)
    finally:
        if handle is not None:
            handle.close()

    code = completed if isinstance(completed, int) else getattr(completed, "returncode", 0)
    code = int(code)
    tail = ""
    if log_path is not None:
        try:
            lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        tail = "\n".join(part for part in lines[-15:] if part.strip()).strip()
    return code == 0, code, tail


def install_python_dependencies(
    python: str | os.PathLike[str],
    requirements: str | os.PathLike[str],
    *,
    wheels_dir: str | os.PathLike[str] | None = None,
    offline: bool = False,
    runner: Callable[..., object] | None = None,
    dry_run: bool = False,
    log_path: str | os.PathLike[str] | None = None,
) -> tuple[bool, str]:
    """装 ``requirements.txt``；失败时给出网络/镜像/离线包的具体建议。

    失败判据是"**装完能不能 import**"：pip 退出码非 0 但依赖齐全时按成功处理
    （见 :func:`dependencies_importable`）。
    """
    if dry_run:
        return True, "[dry-run] 将安装 requirements.txt 里的依赖"
    if not Path(requirements).is_file():
        return False, f"未找到依赖清单 {requirements}"

    local_wheels = Path(wheels_dir) if wheels_dir is not None else None
    if local_wheels is not None and not local_wheels.is_dir():
        local_wheels = None
    if offline and local_wheels is None:
        return False, "离线模式需要随包的 wheels/ 目录（或用 --wheels 指定）"

    commands = pip_install_commands(
        python, requirements, wheels_dir=local_wheels, offline=offline
    )
    if log_path is not None:
        print_info(f"pip 输出写入: {log_path}（依赖较多，通常 1–3 分钟，请耐心等待）")
    last_error = ""
    for argv in commands:
        is_pip_upgrade = argv[-1] == "pip"
        print_info(f"执行: {' '.join(argv)}")
        ok, code, tail = run_pip_command(argv, log_path=log_path, runner=runner)
        if ok:
            if is_pip_upgrade:
                print_ok("pip 已更新")
            continue
        last_error = tail or f"pip 退出码 {code}，没有留下任何输出"
        if is_pip_upgrade:
            print_warn(f"更新 pip 失败（退出码 {code}，不影响安装，继续）")
            continue
        if dependencies_importable(python, runner=runner):
            print_warn(f"pip 退出码 {code}，但依赖已可导入 —— 按成功处理")
            if log_path is not None:
                print_info(f"pip 日志: {log_path}")
            return True, "依赖已就位（pip 退出码非 0，已用导入检查复核）"
        # 在线装失败但本地有 wheel：退一步用"只吃本地包"再试一次
        if local_wheels is not None and not offline:
            print_warn("在线安装失败，改用本地 wheels/ 重试")
            retry_argv = pip_install_commands(
                python, requirements, wheels_dir=local_wheels, offline=True, upgrade_pip=False
            )[-1]
            print_info(f"执行: {' '.join(retry_argv)}")
            ok_retry, _code_retry, tail_retry = run_pip_command(
                retry_argv, log_path=log_path, runner=runner
            )
            if ok_retry or dependencies_importable(python, runner=runner):
                print_ok("已用本地 wheels/ 装好依赖")
                return True, "依赖安装成功（离线 wheels）"
            last_error = tail_retry or last_error
        return False, last_error

    return True, "依赖安装成功"


def dependency_failure_hint(
    *,
    offline: bool = False,
    wheels_dir: Path | None = None,
    log_path: str | os.PathLike[str] | None = None,
) -> str:
    """依赖装不上时打印的排查建议。"""
    lines = ["  排查建议："]
    if log_path is not None:
        lines.append(f"    0) 先看完整 pip 日志: {log_path}")
    if offline:
        lines.append(f"    离线模式只吃本地 wheel，当前目录: {wheels_dir or '（未找到 wheels/）'}")
        lines.append("    确认 wheels/ 里的轮子与目标 Python 版本匹配，或去掉 --offline 联网安装")
    else:
        lines.append("    1) 确认网络可用（WSL2 内 curl -I https://pypi.org/simple/）")
        lines.append("    2) 国内网络可换镜像后重试：")
        lines.append("       MESA_IDE_PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple python3 install.py")
        lines.append("    3) 使用随包的离线 wheel 目录：python3 install.py --offline --wheels wheels")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MESA 环境（检测 → 配置 → 可选安装/编译）
# ---------------------------------------------------------------------------


def check_mesa_environment() -> bool:
    """检测并打印 MESA 安装状态（"已安装就检查"）。"""
    detected = detect_mesa()
    print(detected.summary())
    for warning in detected.warnings:
        print(f"  {SYM_WARN} {warning}")
    if not detected.is_valid:
        print("  提示: 设置 MESA_DIR 指向 MESA 安装目录，例如:")
        print("    export MESA_DIR=$HOME/mesa        # Linux/macOS")
        print("    set MESA_DIR=C:\\path\\to\\mesa      # Windows")
        print("  未检测到 MESA 不影响本 IDE 安装，但编译/运行项目会失败。")
    return detected.is_valid


ENV_AGREE_MESA_INSTALL = "MESA_IDE_AGREE_MESA_INSTALL"


def mesa_install_consent(
    plan,
    *,
    interactive: bool | None = None,
    input_fn: Callable[[str], str] = input,
    env: Mapping[str, str] | None = None,
) -> bool:
    """是否执行"MESA 解压 + 编译"？三档：环境变量 > 交互提问 > 非交互默认否。

    编译很慢（几分钟到一小时以上）且占数 GB 磁盘，必须显式同意。
    """
    source = os.environ if env is None else env
    override = parse_bool(source.get(ENV_AGREE_MESA_INSTALL))
    if override is not None:
        return override

    if interactive is None:
        interactive = sys.stdin.isatty()
    if not interactive:
        return False

    answer = input_fn(
        "  是否现在安装/编译 MESA？（下载已就绪，编译可能耗时 10–60 分钟）[y/N] "
    )
    return answer.strip().lower() in {"y", "yes", "是"}


def _report_extract_blockers(archive, target_dir: str, label: str) -> bool:
    """解压前预检目标目录可写性 / 归档可读性。

    不满足时打印**可复制的修复命令**并返回 False —— 不抛 Python 栈。
    真实故障：用户用 sudo/管理员把 MESA 归档复制进 ~/mesa，目录属主变成 root，
    普通用户无法在其中创建解压临时目录（PermissionError）。
    """
    blockers = extract_blockers(archive, target_dir)
    if not blockers:
        return True
    print(f"{SYM_ERR} 无法解压 {label}（目标: {target_dir}）:")
    for item in blockers:
        print(f"    {item}")
    print("  常见原因：归档是用 sudo / Windows 管理员方式复制进家目录的，目录属主变成了 root。")
    print("  按上面的「修复」命令处理后再运行安装器即可（已完成的步骤会自动跳过）。")
    return False


def setup_mesa(
    *,
    env: Mapping[str, str] | None = None,
    archive_dirs=DEFAULT_ARCHIVE_DIRS,
    sdk_root: str = DEFAULT_SDK_ROOT,
    mesa_root: str = DEFAULT_MESA_ROOT,
    project_dir: str | os.PathLike[str] | None = None,
    rc_path: str | os.PathLike[str] | None = None,
    interactive: bool | None = None,
    input_fn: Callable[[str], str] = input,
    runner=subprocess.run,
    nprocs: int | None = None,
    exists=os.path.exists,
) -> bool:
    """安装并配置 MESA（返回是否最终可用）。

    流程：检测 → 已装则只"配置"（写 env 文件 + shell 标记块）；
    未装则按归档计划解压 SDK/源码（需同意）→ 配置 → 编译。
    """
    source = os.environ if env is None else env
    directory = Path(project_dir) if project_dir is not None else Path(__file__).parent
    platform_system = platform.system()

    # 已检测到"MESA_DIR 指向的安装"时，让计划以它为构建目标：这样
    # "源码已解压、但还没编译"的安装也会被识别为 needs_build，
    # 而不是被误判为"已安装"直接跳过编译（历史 bug）。
    detected = detect_mesa(env=source)
    plan = plan_mesa_install(
        archive_dirs=archive_dirs,
        sdk_root=sdk_root,
        mesa_root=mesa_root,
        exists=exists,
        override_mesa_dir=detected.mesa_dir if detected.is_valid else None,
    )
    print(f"  {plan.description}")

    # 旧版安装器会把带顶层目录的归档解压成双重嵌套（MESA_DIR 指向的目录缺
    # star/defaults）。检测到就先修复，再重新规划。
    if plan.needs_repair:
        print(f"{SYM_WARN} 检测到历史解压目录嵌套，开始自动修复...")
        repaired, messages = repair_nested_installs(
            plan.mesa_dir,
            plan.sdk_root,
            repair_mesa_from=plan.repair_mesa_from,
            repair_sdk_from=plan.repair_sdk_from,
        )
        for message in messages:
            print(f"  {message}")
        if repaired:
            plan = plan_mesa_install(
                archive_dirs=archive_dirs, sdk_root=sdk_root, mesa_root=mesa_root, exists=exists
            )
            print(f"  修复后: {plan.description}")

    # 已编译完成（无论 SDK 是否在计划内）：只做"配置"
    if exists(os.path.join(plan.mesa_dir, BUILD_MARKER)):
        if detected.is_valid and detected.mesa_dir == plan.mesa_dir:
            print(f"{SYM_OK} {detected.summary()}")
        _configure_mesa(plan.mesa_dir, plan.sdk_root, directory, rc_path, platform_system)
        os.environ.update(mesa_build_env(plan.mesa_dir, plan.sdk_root, base_env=dict(source)))
        return detect_mesa().is_valid

    if not plan.can_install:
        for line in DOWNLOAD_HINT.splitlines():
            print(f"  {line}")
        print("  未安装 MESA 不影响 IDE 启动，但编译/运行项目会失败。")
        return False

    if plan.sdk_archive is not None:
        print(f"  找到 MESA SDK: {plan.sdk_archive.path}")
    if plan.mesa_archive is not None:
        print(f"  找到 MESA 源码: {plan.mesa_archive.path}")
    if not mesa_install_consent(plan, interactive=interactive, input_fn=input_fn, env=source):
        print("  已跳过 MESA 安装/编译；可稍后运行 MESA_IDE_AGREE_MESA_INSTALL=1 install.py")
        return False

    if plan.needs_sdk_extract and plan.sdk_archive is not None:
        if not _report_extract_blockers(plan.sdk_archive, plan.sdk_root, "MESA SDK"):
            return False
        print(f"  解压 MESA SDK → {plan.sdk_root}")
        if not extract_into_target(plan.sdk_archive, plan.sdk_root, runner=runner):
            print(f"{SYM_ERR} SDK 解压失败")
            _report_extract_blockers(plan.sdk_archive, plan.sdk_root, "MESA SDK")
            return False

    if plan.needs_mesa_extract and plan.mesa_archive is not None:
        if not _report_extract_blockers(plan.mesa_archive, plan.mesa_dir, "MESA 源码"):
            return False
        print(f"  解压 MESA 源码 → {plan.mesa_dir}")
        if not extract_into_target(plan.mesa_archive, plan.mesa_dir, runner=runner):
            print(f"{SYM_ERR} MESA 源码解压失败")
            _report_extract_blockers(plan.mesa_archive, plan.mesa_dir, "MESA 源码")
            return False

    _configure_mesa(plan.mesa_dir, plan.sdk_root, directory, rc_path, platform_system)
    os.environ.update(mesa_build_env(plan.mesa_dir, plan.sdk_root, base_env=dict(source)))

    if not exists(os.path.join(plan.mesa_dir, "install")):
        print(f"{SYM_ERR} 未找到 {plan.mesa_dir}/install，无法编译")
        return False

    log_path = directory / "mesa_install.log"
    print(f"  开始编译 MESA（{plan.mesa_dir}）……输出写入 {log_path}")
    print("  提示：可以先按 Ctrl-C 中断安装，MESA 源码与环境配置已保留。")
    if not mesa_run_build(
        plan.mesa_dir, plan.sdk_root, runner=runner, log_path=str(log_path), nprocs=nprocs
    ):
        print(f"{SYM_ERR} MESA 编译未完成（失败或被 Ctrl-C 中断），日志: {log_path}")
        print("  MESA 源码与环境配置已保留；重新运行安装器即可从编译继续（已完成的步骤会自动跳过）。")
        return False

    detected = detect_mesa()
    print(f"{SYM_OK} {detected.summary()}")
    return detected.is_valid


def _configure_mesa(
    mesa_dir: str,
    sdk_root: str,
    directory: Path,
    rc_path: str | os.PathLike[str] | None,
    platform_system: str,
) -> None:
    """写好 env 脚本（供启动器 source）并（可选）写入 shell 启动文件标记块。"""
    env_path = write_env_file(
        directory, mesa_dir, sdk_root, platform_system=platform_system
    )
    print(f"{SYM_OK} 已生成 MESA 环境脚本: {env_path}")
    if rc_path is None:
        rc_path = Path.home() / (".bash_profile" if platform_system == "Darwin" else ".bashrc")
    try:
        changed = update_shell_rc(
            rc_path, mesa_dir, sdk_root, platform_system=platform_system
        )
    except OSError as exc:
        print(f"  {SYM_WARN} 写入 {rc_path} 失败（不影响本次安装）: {exc}")
        return
    if changed:
        print(f"{SYM_OK} 已把 MESA 环境写入 {rc_path}（标记块，可安全删除）")
    else:
        print(f"{SYM_OK} {rc_path} 中的 MESA 环境已是最新")


# ---------------------------------------------------------------------------
# 界面字体（中文显示）
# ---------------------------------------------------------------------------

ENV_AGREE_FONT_INSTALL = "MESA_IDE_AGREE_FONT_INSTALL"


def font_install_consent(
    plan,
    *,
    interactive: bool | None = None,
    input_fn: Callable[[str], str] = input,
    env: Mapping[str, str] | None = None,
) -> bool:
    """是否执行系统字体包安装？三档：环境变量 > 交互式提问 > 非交互默认否。

    绝不静默 sudo：只有用户显式同意（或环境变量明确放行）才安装系统包。
    """
    source = os.environ if env is None else env
    override = parse_bool(source.get(ENV_AGREE_FONT_INSTALL))
    if override is not None:
        return override

    if interactive is None:
        interactive = sys.stdin.isatty()
    if not interactive:
        return False

    answer = input_fn(f"  是否现在安装中文字体包（{plan.manager}，可能需要 sudo 密码）？[y/N] ")
    return answer.strip().lower() in {"y", "yes", "是"}


def check_ui_fonts(
    *,
    env: Mapping[str, str] | None = None,
    home: str | os.PathLike[str] | None = None,
    runner: Callable[..., object] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
    interactive: bool | None = None,
    input_fn: Callable[[str], str] = input,
) -> bool:
    """安装器"界面字体"步骤：先装自带字体（免 sudo），不行再提议系统包。

    返回是否最终有中文显示保障。
    """
    results = ensure_bundled_fonts(env=env, home=home, runner=runner)
    if all(result.ok for result in results):
        for result in results:
            if result.copied:
                print(f"{SYM_OK} 已安装自带中文字体: {result.family}")
                print(f"  （安装到 {result.target}，无需管理员权限）")
            else:
                print(f"{SYM_OK} 自带中文字体已就位: {result.family}")
            for warning in result.warnings:
                print(f"  {SYM_WARN} {warning}")
        return True

    for result in results:
        for warning in result.warnings:
            print(f"  {SYM_WARN} {warning}")

    detected = detect_cjk_fonts(runner=runner, which=which)
    if detected:
        print(f"{SYM_OK} 检测到系统中文字体: {', '.join(detected[:4])}")
        return True

    print(f"{SYM_WARN} 未检测到任何中文字体，界面中文可能显示为方框。")
    manager = detect_package_manager(which=which)
    plan = build_font_plan(platform.system(), manager)
    if plan is None:
        print("  无法自动安装（未识别包管理器），请手动安装一款中文字体。")
        return False
    print(f"  检测到包管理器: {plan.manager}")
    print(f"  {plan.description}；候选包: {', '.join(plan.packages)}")
    if not font_install_consent(plan, interactive=interactive, input_fn=input_fn, env=env):
        print("  已跳过。可稍后手动安装，或运行 MESA_IDE_AGREE_FONT_INSTALL=1 重装。")
        return False
    if install_font_package(plan, runner=runner):
        print(f"{SYM_OK} 系统字体包安装成功（建议重启 MESA IDE 后字体生效）")
        return True
    print(f"{SYM_ERR} 字体包安装失败，请手动安装后再启动。")
    return False


# ---------------------------------------------------------------------------
# 参数数据库
# ---------------------------------------------------------------------------


def check_parameter_db(db_path: str | os.PathLike[str]) -> tuple[bool, str]:
    """确认 ``mesa_data.db`` 存在且能读出参数表（只读打开，不改文件）。"""
    path = Path(db_path)
    if not path.is_file():
        return False, f"未找到 {path.name}（参数校验与搜索会受限）"
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = connection.execute("SELECT COUNT(*) FROM parameters").fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        return False, f"{path.name} 无法读取: {exc}"
    count = row[0] if row else 0
    if not count:
        return False, f"{path.name} 里没有参数记录"
    return True, f"已找到 {path.name}（{count} 个 MESA 参数）"


# ---------------------------------------------------------------------------
# 启动脚本
# ---------------------------------------------------------------------------


def create_launcher_scripts(script_dir: Path) -> Path:
    """生成自定位的启动脚本，返回其路径。"""
    if platform.system() == "Windows":
        run_script = script_dir / "run_mesa.bat"
        run_script.write_text(RUN_BAT_CONTENT, encoding="utf-8")
    else:
        run_script = script_dir / "run_mesa.sh"
        run_script.write_text(RUN_SH_CONTENT, encoding="utf-8")
        run_script.chmod(0o755)
    return run_script


# ---------------------------------------------------------------------------
# 安装后自检
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HealthCheck:
    """一条自检结论。"""

    name: str
    ok: bool
    detail: str
    fatal: bool = True


def build_health_checks(
    script_dir: str | os.PathLike[str],
    *,
    system: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., object] | None = None,
    env: Mapping[str, str] | None = None,
    host: HostInfo | None = None,
) -> list[HealthCheck]:
    """逐条体检安装结果（venv / 依赖 / 数据库 / 字体 / 启动脚本 / MESA / 显示）。"""
    base = Path(script_dir)
    resolved_system = system or platform.system()
    checks: list[HealthCheck] = []

    status = inspect_venv(base / VENV_DIRNAME, system=resolved_system, runner=runner)
    checks.append(HealthCheck("虚拟环境", status.usable, status.describe()))
    interpreter = status.python or str(sys.executable)

    ok_tk = module_available("tkinter", python=interpreter, runner=runner)
    checks.append(HealthCheck("tkinter（图形界面）", ok_tk, "可导入" if ok_tk else "导入失败"))

    ok_plot = module_available("matplotlib, mesa_reader", python=interpreter, runner=runner)
    checks.append(
        HealthCheck(
            "绘图依赖（matplotlib / mesa_reader）",
            ok_plot,
            "可导入" if ok_plot else "导入失败（重跑 python3 install.py）",
        )
    )

    db_ok, db_detail = check_parameter_db(base / DATABASE_FILENAME)
    checks.append(HealthCheck(DATABASE_FILENAME, db_ok, db_detail))

    font_sources = [base / "assets" / "fonts" / name for name, _family in BUNDLED_FONTS]
    missing_fonts = [str(path) for path in font_sources if not path.is_file()]
    checks.append(
        HealthCheck(
            "自带中文字体（界面 + 编辑器）",
            not missing_fonts,
            "随包提供" if not missing_fonts else "缺少 " + ", ".join(missing_fonts),
        )
    )

    launcher = base / ("run_mesa.bat" if resolved_system == "Windows" else "run_mesa.sh")
    checks.append(
        HealthCheck("启动脚本", launcher.is_file(), launcher.name if launcher.is_file() else "未生成")
    )

    detected = detect_mesa(env=env)
    checks.append(
        HealthCheck(
            "MESA 安装",
            detected.is_valid,
            detected.summary(),
            fatal=False,
        )
    )

    info = host or detect_host(system=resolved_system)
    display_ok, display_detail = display_status(
        system=resolved_system, env=env, is_wsl=info.is_wsl
    )
    checks.append(HealthCheck("图形显示", display_ok, display_detail, fatal=False))
    return checks


def run_health_check(
    script_dir: str | os.PathLike[str],
    *,
    system: str | None = None,
    runner: Callable[..., object] | None = None,
    env: Mapping[str, str] | None = None,
    host: HostInfo | None = None,
) -> bool:
    """跑一遍自检并打印结论；返回"必需项是否全过"。"""
    print_step("自检", "安装结果体检…")
    checks = build_health_checks(script_dir, system=system, runner=runner, env=env, host=host)
    failures = 0
    for check in checks:
        if check.ok:
            print(f"  {SYM_OK} {check.name}: {check.detail}")
            continue
        symbol = SYM_ERR if check.fatal else SYM_WARN
        if check.fatal:
            failures += 1
        print(f"  {symbol} {check.name}: {check.detail}")
    if failures:
        print(f"\n{SYM_ERR} 自检发现 {failures} 项必需条件不满足，请按上面的提示处理后重试。")
        return False
    print(f"\n{SYM_OK} 自检通过：可以启动 MESA IDE 了。")
    return True


# ---------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InstallOptions:
    """命令行开关（默认值即"交互式安装"）。"""

    yes: bool = False
    no_mesa: bool = False
    no_fonts: bool = False
    no_system: bool = False
    offline: bool = False
    wheels: str | None = None
    archives: str | None = None
    check_only: bool = False
    dry_run: bool = False

    @property
    def interactive(self) -> bool:
        """--yes 视为非交互；否则看有没有终端。"""
        if self.yes:
            return False
        return sys.stdin.isatty()


def parse_install_args(argv: Sequence[str] | None = None) -> InstallOptions:
    """解析安装器命令行开关（未知参数直接报错退出）。"""
    parser = argparse.ArgumentParser(
        prog="install.py",
        description=f"{APP_NAME} 安装器 v{__version__}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 install.py                 # 交互式安装（缺什么问什么）\n"
            "  python3 install.py --yes           # 无人值守：同意装系统包/MESA/字体\n"
            "  python3 install.py --no-mesa       # 只装 IDE，不动 MESA\n"
            "  python3 install.py --offline       # 只用随包 wheels/ 装依赖\n"
            "  python3 install.py --check         # 只体检，不改任何东西\n"
        ),
    )
    parser.add_argument("--yes", "-y", action="store_true", help="所有提问都回答是")
    parser.add_argument("--no-mesa", action="store_true", help="跳过 MESA 安装与配置")
    parser.add_argument("--no-fonts", action="store_true", help="跳过界面字体步骤")
    parser.add_argument(
        "--no-system",
        "--no-sudo",
        dest="no_system",
        action="store_true",
        help="不安装任何系统包（绝不调用 sudo）",
    )
    parser.add_argument(
        "--archives",
        metavar="DIR",
        help="MESA 归档（mesa-*.zip / mesasdk-*.tar.gz）所在目录；"
        "默认按 ~/mesa、~/Downloads、~ 查找（挂载的 Windows 盘也可，如 /mnt/e/mesa）",
    )
    parser.add_argument("--offline", action="store_true", help="只用本地 wheels/ 装依赖")
    parser.add_argument("--wheels", metavar="DIR", help="指定本地 wheel 目录")
    parser.add_argument("--check", dest="check_only", action="store_true", help="只做环境自检")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要执行的步骤")
    namespace = parser.parse_args(argv)
    return InstallOptions(
        yes=namespace.yes,
        no_mesa=namespace.no_mesa,
        no_fonts=namespace.no_fonts,
        no_system=namespace.no_system,
        offline=namespace.offline,
        wheels=namespace.wheels,
        archives=namespace.archives,
        check_only=namespace.check_only,
        dry_run=namespace.dry_run,
    )


def consent_env(options: InstallOptions, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """把 ``--yes`` 翻译成三个"同意"环境变量（供既有同意逻辑统一读取）。"""
    source = dict(os.environ if base is None else base)
    if options.yes:
        source[ENV_AGREE_SYSTEM_PACKAGES] = "1"
        source[ENV_AGREE_MESA_INSTALL] = "1"
        source[ENV_AGREE_FONT_INSTALL] = "1"
    return source


def mesa_archive_dirs(override: str | None) -> tuple[str, ...]:
    """MESA 归档搜索目录：``--archives`` 指定的目录优先，其后是默认位置。"""
    dirs: list[str] = []
    cleaned = (override or "").strip()
    if cleaned:
        dirs.append(os.path.expanduser(cleaned))
    for item in DEFAULT_ARCHIVE_DIRS:
        if item not in dirs:
            dirs.append(item)
    return tuple(dirs)


def report_missing_deps(host: HostInfo, missing: Sequence[str]) -> None:
    """打印缺失依赖与"复制即用"的修复命令。"""
    required, optional = describe_missing_deps(missing)
    for title in required:
        print(f"  {SYM_ERR} 缺少（必需）: {title}")
    for title in optional:
        print(f"  {SYM_WARN} 缺少（可选）: {title}")
    if not missing:
        return
    plan = build_prereq_plan(host, missing)
    if plan is None:
        print("  未识别包管理器，请手动安装上面缺的组件（tkinter 通常叫 python3-tk）。")
        return
    print(f"  本机补装命令（{plan.manager}）:")
    for group in plan.groups:
        print(f"    {' '.join([*plan.install_argv, group.candidates[0]])}")


def run_check() -> int:
    """``--check``：只体检，不动环境。"""
    script_dir = Path(__file__).parent.absolute()
    os.chdir(script_dir)
    host = detect_host()
    print(f"平台: {host.describe()}")
    print(f"解释器: {sys.executable}（Python {platform.python_version()}）")
    missing = detect_missing_deps()
    if missing:
        print("\n系统依赖体检：")
        report_missing_deps(host, missing)
    else:
        print(f"\n{SYM_OK} 系统依赖齐全（venv / tkinter / unzip / make / zlib / ffmpeg）")
    return 0 if run_health_check(script_dir, host=host) else 1


def main(argv: Sequence[str] | None = None) -> int:
    options = parse_install_args(argv)

    print("=" * 50)
    print(f"   {APP_NAME} 安装程序 v{__version__}")
    print("=" * 50)

    script_dir = Path(__file__).parent.absolute()
    os.chdir(script_dir)

    if options.check_only:
        return run_check()

    host = detect_host()
    print(f"平台: {host.describe()}")
    print(f"解释器: {sys.executable}（Python {platform.python_version()}）")
    display_ok, display_detail = display_status(is_wsl=host.is_wsl)
    print(f"图形显示: {display_detail}")
    if options.dry_run:
        print("模式: --dry-run（只打印，不改动任何东西）")

    env_map = consent_env(options)
    interactive = options.interactive

    # 1/8 平台与 Python 版本（含 venv 支持体检）
    print_step("1/8", "检查 Python 版本与 venv 支持...")
    python_version = sys.version_info
    if not check_python_version(python_version):
        print_error(
            f"需要 Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} 或更高版本，"
            f"当前为 {python_version.major}.{python_version.minor}"
        )
        return 1
    print_ok(f"Python {python_version.major}.{python_version.minor}.{python_version.micro}")
    if not check_venv_support():
        print_warn("当前解释器缺少 venv/ensurepip（第 2 步会尝试补装）")

    # 2/8 系统依赖：tkinter / unzip / ffmpeg（可选自动补装）
    print_step("2/8", "检查系统依赖（tkinter / unzip / make / zlib / ffmpeg）...")
    missing = detect_missing_deps()
    if not missing:
        print_ok("系统依赖齐全")
    else:
        report_missing_deps(host, missing)
        plan = None if options.no_system else build_prereq_plan(host, missing)
        if plan is None:
            if options.no_system:
                print("  已按 --no-system 跳过系统包安装。")
        elif options.dry_run:
            print(f"  [dry-run] 将执行: {plan.description}")
        else:
            print(f"  {plan.description}")
            if system_packages_consent(
                plan, interactive=interactive, input_fn=input, env=env_map
            ):
                unresolved = install_prereq_packages(
                    plan, recheck=lambda key: key not in detect_missing_deps()
                )
                for key in unresolved:
                    print_warn(f"{DEP_TITLES.get(key, key)} 仍未就绪")
            else:
                print("  已跳过。可手动执行上面的命令，或用 --yes 让安装器代劳。")
        required_missing = [
            key
            for key in detect_missing_deps()
            if key in REQUIRED_DEPS
        ]
        if required_missing and not options.dry_run:
            print_warn("必需的系统依赖还没齐，安装可以继续，但界面可能起不来。")

    # 3/8 虚拟环境（创建 / 自愈）
    print_step("3/8", "准备虚拟环境（损坏会自动重建）...")
    venv_path = script_dir / VENV_DIRNAME
    ok, message = ensure_venv(venv_path, dry_run=options.dry_run)
    if not ok:
        print_error(message)
        print(venv_failure_hint(python_version))
        return 1
    print_ok(message)
    venv_python = str(venv_python_path(venv_path))

    # 4/8 Python 依赖（在线 / 离线 wheels）
    print_step("4/8", "安装 Python 依赖...")
    requirements = script_dir / REQUIREMENTS_FILENAME
    pip_log = script_dir / PIP_LOG_FILENAME
    wheels_dir = find_wheels_dir(
        options.wheels,
        script_dir / WHEELS_DIRNAME,
        script_dir.parent / WHEELS_DIRNAME,
    )
    if wheels_dir is not None:
        print_info(f"使用本地 wheel 目录: {wheels_dir}")
    ok, message = install_python_dependencies(
        venv_python,
        requirements,
        wheels_dir=wheels_dir,
        offline=options.offline,
        dry_run=options.dry_run,
        log_path=None if options.dry_run else pip_log,
    )
    if not ok:
        print_error(f"安装依赖包失败: {message}")
        print(dependency_failure_hint(
            offline=options.offline, wheels_dir=wheels_dir, log_path=pip_log
        ))
        return 1
    print_ok(message)

    # 5/8 MESA（已安装就检查；缺则按同意解压编译并配置）
    print_step("5/8", "检查 MESA 安装（可自动安装与配置）...")
    if options.no_mesa:
        print("  已按 --no-mesa 跳过（IDE 本身可用，但编译/运行 MESA 项目会失败）。")
    elif options.dry_run:
        archive_dirs = mesa_archive_dirs(options.archives)
        print(f"  [dry-run] {plan_mesa_install(archive_dirs=archive_dirs).description}")
    else:
        archive_dirs = mesa_archive_dirs(options.archives)
        if options.archives:
            print_info(f"归档搜索目录: {archive_dirs[0]}")
        setup_mesa(
            env=env_map, interactive=interactive, input_fn=input, archive_dirs=archive_dirs
        )

    # 6/8 界面字体（中文显示）
    print_step("6/8", "检查界面字体（中文显示）...")
    if options.no_fonts:
        print("  已按 --no-fonts 跳过。")
    elif options.dry_run:
        print("  [dry-run] 将安装自带中文字体（免 sudo）")
    else:
        check_ui_fonts(env=env_map, interactive=interactive, input_fn=input)

    # 7/8 MESA 参数数据库
    print_step("7/8", "检查 MESA 参数数据库...")
    db_ok, db_detail = check_parameter_db(script_dir / DATABASE_FILENAME)
    if db_ok:
        print_ok(db_detail)
    else:
        print_warn(db_detail)
        print_info("请把 mesa_data.db 放到 IDE 目录（随发行包一起提供）")

    # 8/8 启动脚本 + 自检
    print_step("8/8", "创建启动脚本...")
    if options.dry_run:
        run_script = script_dir / ("run_mesa.bat" if host.is_windows else "run_mesa.sh")
        print(f"  [dry-run] 将生成 {run_script.name}")
    else:
        run_script = create_launcher_scripts(script_dir)
        print_ok(f"启动脚本已就绪: {run_script.name}")

    healthy = True
    if not options.dry_run:
        healthy = run_health_check(script_dir, env=env_map, host=host)

    print("\n" + "=" * 50)
    if healthy:
        print("   安装完成！")
    else:
        print("   安装基本完成（自检有告警，见上）")
    print("=" * 50)
    print("\n开始使用（现阶段）:")
    print(f"  {run_script}   # 启动 MESA IDE（面板: 创建/打开项目）")
    print("  启动后：")
    print("    「创建新项目」 → 复制 MESA 官方 star/work 模板，起一个项目名即可")
    print("    「打开老项目」 → 选择已有项目目录（或从 MESA test_suite 选）")
    print("    「编译运行」   → 在新终端执行 ./mk && ./rn（会先询问是否实时画图）")
    print("    「HR图轨迹 / 内部剖面」 → 运行结束后按 history/profile 数据画图")
    print(f"  MESA 环境脚本: {script_dir / 'mesa_env.sh'}（终端编译运行会自动加载）")
    print(f"  编译日志: {script_dir / 'mesa_install.log'}（MESA 编译输出）")
    print("  修复/升级: 重跑本安装器即可（已完成的步骤会自动跳过）")
    if not display_ok:
        print(f"\n{SYM_WARN} {display_detail}")
    print()
    return 0 if healthy else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        print("已中断（Ctrl-C）。MESA 源码与环境配置已保留；")
        print("重新运行安装器即可继续（已完成的步骤会自动跳过）。")
        sys.exit(130)

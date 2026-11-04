"""界面字体保障（core 层，仅标准库）。

目标：**别人装完软件就能正常显示中文** —— 两条腿走路，都不依赖管理员权限：

1. **自带字体**：仓库 ``assets/fonts/`` 里有 Noto Sans SC 的 OTF 子集
   （SIL OFL 1.1，允许随软件分发）。:func:`ensure_bundled_font` 把它复制到
   用户字体目录（Linux 用 XDG 规范 / macOS ``~/Library/Fonts`` /
   Windows ``%LOCALAPPDATA%`` + HKCU 注册表），Linux 上再刷新 fontconfig
   缓存。之后 Tk（走 fontconfig）与 matplotlib 都能用族名 ``Noto Sans SC``。
2. **系统字体包**：自带字体失效时，按平台/包管理器给出安装计划
   （apt / dnf / pacman / brew），**征得用户同意后**以 argv 列表执行
   （绝不 ``shell=True``、绝不静默 ``sudo``）。

纪律：
- 全部子命令走 argv 列表；动态内容（路径/包名）不拼 shell 字符串；
- 所有副作用（复制、fc-cache、包管理）都可注入，便于离线测试；
- 本层零 Tk/matplotlib 依赖 —— 字体族解析留给 ``ide_ui/fonts.py``。
"""

from __future__ import annotations

import logging
import os
import platform as platform_module
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from core.config import project_root

logger = logging.getLogger(__name__)

#: 自带字体文件名（位于 ``IDE/assets/fonts/``）
BUNDLED_FONT_FILENAME = "NotoSansSC-Regular.otf"
#: 该字体在 fontconfig/matplotlib 里的族名
BUNDLED_FONT_FAMILY = "Noto Sans SC"

#: 编辑器/诊断列表用的等宽中文字体（随包分发第二份字体）
MONO_FONT_FILENAME = "NotoSansMonoCJKsc-Regular.otf"
MONO_FONT_FAMILY = "Noto Sans Mono CJK SC"

#: 全部自带字体（文件名 → 族名），安装器/启动器统一处理
BUNDLED_FONTS: tuple[tuple[str, str], ...] = (
    (BUNDLED_FONT_FILENAME, BUNDLED_FONT_FAMILY),
    (MONO_FONT_FILENAME, MONO_FONT_FAMILY),
)

#: 检测"系统中文字体"用的文件名/族名关键词（小写、不含连字符变体）
CJK_FONT_HINTS: tuple[str, ...] = (
    "notosanscjk",
    "notoserifcjk",
    "notosansmonocjk",
    "notosanssc",
    "sourcehansans",
    "sourcehanserif",
    "sourcehanmono",
    "wqy",
    "wenquanyi",
    "droidsansfallback",
    "simhei",
    "simsun",
    "msyh",
    "microsoftyahei",
    "msjh",
    "msttcore",
    "uming",
    "ukai",
    "arphic",
    "pingfang",
    "hiraginosansgb",
    "fandol",
    "heiti",
    "cjk",
)

#: 系统级字体目录（扫描回退用）
SYSTEM_FONT_ROOTS: tuple[str, ...] = (
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    "/opt/share/fonts",
    "/System/Library/Fonts",
    "/Library/Fonts",
    r"C:\Windows\Fonts",
)


@dataclass(frozen=True)
class FontInstallResult:
    """一次"确保自带字体可用"的结果。"""

    family: str
    target: str
    copied: bool
    refreshed: bool
    ok: bool
    warnings: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class FontPackagePlan:
    """一个系统字体包的安装计划（动态内容只有包名，argv 其余部分冻结）。"""

    manager: str
    description: str
    packages: tuple[str, ...]  # 候选包名，依次尝试，成功即停
    install_argv: tuple[str, ...]  # 安装命令前缀（不含包名）
    update_argv: tuple[str, ...] = ()  # 安装前刷新索引的命令（如 apt update）


def bundled_font_source(
    root: str | os.PathLike[str] | None = None,
    filename: str = BUNDLED_FONT_FILENAME,
) -> Path:
    """自带字体在仓库里的位置（``<IDE>/assets/fonts/...``）。"""
    base = Path(root) if root is not None else project_root()
    return base / "assets" / "fonts" / filename


def user_fonts_dir(
    *,
    platform_system: str | None = None,
    env: Mapping[str, str] | None = None,
    home: str | os.PathLike[str] | None = None,
) -> Path:
    """用户级字体目录（写这里不需要管理员权限）。"""
    system = platform_system or platform_module.system()
    source = os.environ if env is None else env
    home_path = Path(home) if home is not None else Path.home()

    if system == "Windows":
        base = source.get("LOCALAPPDATA") or str(home_path / "AppData" / "Local")
        return Path(base) / "Microsoft" / "Windows" / "Fonts"
    if system == "Darwin":
        return home_path / "Library" / "Fonts"
    # Linux/其他 POSIX：fontconfig 的 XDG 数据目录
    data_home = source.get("XDG_DATA_HOME")
    base = Path(data_home) if data_home else home_path / ".local" / "share"
    return base / "fonts"


def refresh_font_cache(
    fonts_dir: str | os.PathLike[str],
    *,
    runner: Callable[..., object] = subprocess.run,
    env: Mapping[str, str] | None = None,
) -> tuple[bool, str]:
    """Linux：``fc-cache -f <目录>``，让 fontconfig/Tk 立即看到新字体。

    返回 ``(成功, 失败原因或空串)``。没有 fc-cache 时视为失败（带原因）。
    ``env`` 会传给子进程（fontconfig 用 ``XDG_DATA_HOME``/``XDG_CACHE_HOME``
    决定扫描目录与缓存位置，隔离测试时靠它）。
    """
    if shutil.which("fc-cache") is None:
        return False, "未找到 fc-cache（fontconfig 未安装？）"
    try:
        completed = runner(["fc-cache", "-f", str(fonts_dir)], check=False, env=env)
        code = completed if isinstance(completed, int) else getattr(completed, "returncode", 0)
    except OSError as exc:
        return False, str(exc)
    if code == 0:
        return True, ""
    return False, f"fc-cache 退出码 {code}"


def _register_windows_font(target: str | os.PathLike[str]) -> None:
    """Windows：把字体登记进 HKCU（用户级，无需管理员）。"""
    import winreg  # 仅 Windows 可用；其他平台本函数不会被调用

    value_name = f"{BUNDLED_FONT_FAMILY} (TrueType)"
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows NT\CurrentVersion\Fonts",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, str(target))
    except OSError as exc:  # pragma: no cover - 取决于 Windows 版本
        logger.warning("Windows 字体注册失败（下次启动可能才可见）: %s", exc)


def _ensure_font_file(
    filename: str,
    family: str,
    *,
    project_root: str | os.PathLike[str] | None = None,
    platform_system: str | None = None,
    env: Mapping[str, str] | None = None,
    home: str | os.PathLike[str] | None = None,
    runner: Callable[..., object] = subprocess.run,
    copy_file: Callable[[str, str], str] = shutil.copy2,
    register_windows: Callable[[str], None] | None = _register_windows_font,
) -> FontInstallResult:
    """把**一个**自带字体装进用户字体目录并刷新缓存（幂等、无需管理员）。

    幂等规则：目标文件已存在且大小一致 → 不复制、不刷新（启动时调用无开销）。
    """
    system = platform_system or platform_module.system()
    source = bundled_font_source(project_root, filename=filename)
    warnings: list[str] = []

    if not source.is_file():
        message = f"自带字体缺失: {source}"
        warnings.append(message)
        logger.error("%s", message)
        return FontInstallResult(
            family=family, target="", copied=False,
            refreshed=False, ok=False, warnings=tuple(warnings),
        )

    target_dir = user_fonts_dir(platform_system=system, env=env, home=home)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / filename

    copied = False
    if not target.exists() or target.stat().st_size != source.stat().st_size:
        copy_file(str(source), str(target))
        copied = True
        logger.info("已安装自带中文字体: %s", target)

    refreshed = False
    cache_marker = target_dir / f".{filename}.cache-ok"
    needs_refresh = copied or not cache_marker.exists()
    if system == "Linux" and needs_refresh:
        # 子进程要看到与目录解析一致的环境（尤其是测试注入的 XDG_DATA_HOME）
        cache_env: Mapping[str, str] | None = None
        if env is not None:
            cache_env = {**os.environ, **env}
        ok, reason = refresh_font_cache(target_dir, runner=runner, env=cache_env)
        refreshed = ok
        if ok:
            try:
                cache_marker.touch()
            except OSError:  # pragma: no cover - 只读目录等
                pass
        else:
            message = f"字体缓存刷新失败（{reason}）; Tk 可能要重启后才能看到新字体"
            warnings.append(message)
            logger.warning("%s", message)
    elif system == "Windows" and copied and register_windows is not None:
        register_windows(str(target))

    return FontInstallResult(
        family=family,
        target=str(target),
        copied=copied,
        refreshed=refreshed,
        ok=True,
        warnings=tuple(warnings),
    )


def ensure_bundled_font(
    *,
    project_root: str | os.PathLike[str] | None = None,
    platform_system: str | None = None,
    env: Mapping[str, str] | None = None,
    home: str | os.PathLike[str] | None = None,
    runner: Callable[..., object] = subprocess.run,
    copy_file: Callable[[str, str], str] = shutil.copy2,
    register_windows: Callable[[str], None] | None = _register_windows_font,
) -> FontInstallResult:
    """把**界面字体**（Noto Sans SC）装进用户字体目录并刷新缓存。

    与旧版签名一致；全部字体（含编辑器等宽字体）用 :func:`ensure_bundled_fonts`。
    """
    return _ensure_font_file(
        BUNDLED_FONT_FILENAME,
        BUNDLED_FONT_FAMILY,
        project_root=project_root,
        platform_system=platform_system,
        env=env,
        home=home,
        runner=runner,
        copy_file=copy_file,
        register_windows=register_windows,
    )


def ensure_bundled_fonts(
    *,
    project_root: str | os.PathLike[str] | None = None,
    platform_system: str | None = None,
    env: Mapping[str, str] | None = None,
    home: str | os.PathLike[str] | None = None,
    runner: Callable[..., object] = subprocess.run,
    copy_file: Callable[[str, str], str] = shutil.copy2,
    register_windows: Callable[[str], None] | None = _register_windows_font,
) -> list[FontInstallResult]:
    """把**全部自带字体**装进用户字体目录（界面 + 编辑器等宽），返回逐个结果。"""
    return [
        _ensure_font_file(
            filename,
            family,
            project_root=project_root,
            platform_system=platform_system,
            env=env,
            home=home,
            runner=runner,
            copy_file=copy_file,
            register_windows=register_windows,
        )
        for filename, family in BUNDLED_FONTS
    ]


def detect_cjk_fonts(
    *,
    fc_list_cmd: str = "fc-list",
    runner: Callable[..., object] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
    scan_roots: Iterable[str | os.PathLike[str]] | None = None,
    exists: Callable[[str], bool] = os.path.exists,
) -> list[str]:
    """检测系统可见的中文字体（返回证据名列表，可能为空）。

    优先用 ``fc-list :lang=zh``（fontconfig 的标准查询，Linux 也覆盖用户目录）；
    fc-list 缺失/失败时回退到扫描字体目录文件名关键词。
    """
    if which(fc_list_cmd) is not None:
        try:
            # 注意不用 ":lang=zh"：fontconfig 对**子集字体**的 lang 覆盖判定
            # 可能不认 zh（我们验证过），但族名一定在 —— 按关键词匹配族名最稳。
            completed = runner(
                [fc_list_cmd, "--format=%{family}\n"],
                check=False,
                capture_output=True,
                text=True,
            )
            code = completed if isinstance(completed, int) else getattr(completed, "returncode", 0)
            output = "" if isinstance(completed, int) else (getattr(completed, "stdout", "") or "")
            if code == 0 and output.strip():
                seen: list[str] = []
                for line in output.splitlines():
                    name = line.strip()
                    lowered = "".join(ch for ch in name.lower() if ch.isalnum())
                    if name and name not in seen and any(
                        hint in lowered for hint in CJK_FONT_HINTS
                    ):
                        seen.append(name)
                if seen:
                    return seen
        except OSError:
            pass  # fc-list 存在但执行失败 → 走扫描回退

    roots: list[str | os.PathLike[str]] = list(scan_roots) if scan_roots is not None else [
        *SYSTEM_FONT_ROOTS,
        str(user_fonts_dir()),
    ]
    found: list[str] = []
    seen_names: set[str] = set()
    for root in roots:
        base = Path(root)
        if not exists(str(base)) or not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".ttf", ".ttc", ".otf", ".otc"}:
                continue
            lowered = "".join(ch for ch in path.stem.lower() if ch.isalnum())
            if any(hint in lowered for hint in CJK_FONT_HINTS):
                if path.name not in seen_names:
                    seen_names.add(path.name)
                    found.append(path.name)
    return found


# ---------------------------------------------------------------------------
# 系统字体包安装计划（需用户同意）
# ---------------------------------------------------------------------------

#: 规范名 → 探测用的可执行名
_PACKAGE_MANAGERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("apt", ("apt-get", "apt")),
    ("dnf", ("dnf",)),
    ("yum", ("yum",)),
    ("pacman", ("pacman",)),
    ("zypper", ("zypper",)),
    ("apk", ("apk",)),
    ("brew", ("brew",)),
)


def detect_package_manager(
    which: Callable[[str], str | None] = shutil.which,
) -> str | None:
    """按常见顺序探测包管理器，返回规范名（apt/dnf/yum/pacman/zypper/apk/brew）。"""
    for canonical, names in _PACKAGE_MANAGERS:
        if any(which(name) is not None for name in names):
            return canonical
    return None


def build_font_plan(
    platform_system: str,
    manager: str | None,
) -> FontPackagePlan | None:
    """给出"给这台机器装中文字体包"的安装计划；给不出时返回 None。

    Windows 不需要：自带字体 + HKCU 注册即可。
    """
    if platform_system == "Windows":
        return None
    if platform_system == "Darwin":
        if manager == "brew":
            return FontPackagePlan(
                manager="brew",
                description="Homebrew 安装 Noto Sans CJK（无需 sudo）",
                packages=("font-noto-sans-cjk",),
                install_argv=("brew", "install"),
            )
        return None
    if manager == "apt":
        return FontPackagePlan(
            manager="apt",
            description="APT 安装中文字体包（fonts-noto-cjk，需要 sudo 密码）",
            packages=("fonts-noto-cjk", "fonts-wqy-zenhei"),
            install_argv=("sudo", "apt-get", "install", "-y"),
            update_argv=("sudo", "apt-get", "update"),
        )
    if manager == "dnf":
        return FontPackagePlan(
            manager="dnf",
            description="DNF 安装中文字体包（需要 sudo 密码）",
            packages=("google-noto-sans-cjk-fonts", "wqy-zenhei-fonts"),
            install_argv=("sudo", "dnf", "install", "-y"),
        )
    if manager == "yum":
        return FontPackagePlan(
            manager="yum",
            description="YUM 安装中文字体包（需要 sudo 密码）",
            packages=("google-noto-sans-cjk-fonts", "wqy-zenhei-fonts"),
            install_argv=("sudo", "yum", "install", "-y"),
        )
    if manager == "pacman":
        return FontPackagePlan(
            manager="pacman",
            description="pacman 安装中文字体包（需要 sudo 密码）",
            packages=("noto-fonts-cjk",),
            install_argv=("sudo", "pacman", "-S", "--noconfirm"),
        )
    if manager == "zypper":
        return FontPackagePlan(
            manager="zypper",
            description="zypper 安装中文字体包（需要 sudo 密码）",
            packages=("noto-sans-cjk-fonts",),
            install_argv=("sudo", "zypper", "install", "-y"),
        )
    if manager == "apk":
        return FontPackagePlan(
            manager="apk",
            description="apk 安装中文字体包（需要 root）",
            packages=("font-noto-cjk",),
            install_argv=("sudo", "apk", "add"),
        )
    return None


def install_font_package(
    plan: FontPackagePlan,
    *,
    runner: Callable[..., object] = subprocess.run,
) -> bool:
    """按计划依次尝试候选包名，任一成功即返回 True（绝不 shell=True）。"""
    attempted: list[str] = []
    try:
        if plan.update_argv:
            attempted.append(" ".join(plan.update_argv))
            runner(list(plan.update_argv), check=False)
        for package in plan.packages:
            argv = [*plan.install_argv, package]
            attempted.append(" ".join(argv))
            completed = runner(argv, check=False)
            code = completed if isinstance(completed, int) else getattr(completed, "returncode", 0)
            if code == 0:
                logger.info("已安装字体包: %s", package)
                return True
            logger.warning("字体包安装失败（退出码 %s）: %s", code, package)
    except OSError as exc:
        logger.warning("执行字体安装失败: %s", exc)
    logger.info("尝试过的命令: %s", attempted)
    return False

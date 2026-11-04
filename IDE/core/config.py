"""应用配置、版本与日志（core 层，仅标准库）。

修复 P22：「版本号硬编码」「无配置系统」「无日志框架」三件事收拢到单一来源。

- 版本号只在本模块声明一次，``main.py`` / ``install.py`` / ``run_mesa.py`` 共用；
- 可通过环境变量覆盖的少量设置集中在此（默认值与原行为一致）；
- :func:`configure_logging` 提供文件 + 控制台双通道日志，
  默认写到项目内 ``logs/mesa_ide.log``（已在 .gitignore 中忽略）。
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, TextIO

#: 应用名与版本（**单一来源**；界面标题与安装器输出都从这里取）
APP_NAME = "MESA Control Console"
#: 与基线界面显示的 v1.1 保持一致；升版本号由人工决定
__version__ = "1.1"
#: 启动面板标题后缀（基线为 "(Environment Managed)"）
APP_TITLE_SUFFIX = "(Environment Managed)"

ENV_LOG_LEVEL = "MESA_IDE_LOG_LEVEL"
ENV_LOG_FILE = "MESA_IDE_LOG_FILE"
ENV_USER_PROGRAMS = "MESA_PROGRAMS_DIR"

DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_DIRNAME = "logs"
DEFAULT_LOG_FILENAME = "mesa_ide.log"
DEFAULT_VIDEO_FPS = 10
DEFAULT_VIDEO_PREFIX = "hr"

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

#: 界面字体偏好（**按优先级**；此处只是数据，Tk 侧解析见 ``ide_ui/fonts.py``）。
#: **自带字体排在第一位**：安装器会把 Noto Sans SC 装进用户字体目录，因此它
#: 在所有平台都保证可用且有完整 CJK 覆盖 —— 这是"空白 WSL2 装完就能显示中文"
#: 的关键。其余条目保留常见中文字体族，供自带字体缺失时兜底。
ENV_UI_FONT = "MESA_IDE_UI_FONT"
DEFAULT_UI_FONT_PREFERENCES: tuple[str, ...] = (
    "Noto Sans SC",  # 仓库自带字体（core.fonts 会装进用户字体目录）
    "Arial",
    "Helvetica",
    "Microsoft YaHei",
    "YaHei",
    "Noto Sans CJK SC",
    "Noto Sans CJK JP",
    "Source Han Sans SC",
    "WenQuanYi Micro Hei",
    "WenQuanYi Zen Hei",
    "Droid Sans Fallback",
    "SimHei",
    "DejaVu Sans",
)

#: 等宽字体偏好（编辑器、诊断列表、参数搜索结果）。
#: 自带等宽中文字体排在第一位（同理保证编辑器里中文注释可见）。
DEFAULT_MONO_FONT_PREFERENCES: tuple[str, ...] = (
    "Noto Sans Mono CJK SC",  # 仓库自带字体
    "Consolas",
    "Cascadia Mono",
    "DejaVu Sans Mono",
    "Source Han Mono SC",
    "WenQuanYi Zen Hei Mono",
    "Liberation Mono",
    "Courier New",
    "monospace",
)


def parse_font_preferences(raw: str | None) -> tuple[str, ...]:
    """解析 ``MESA_IDE_UI_FONT``：逗号/分号分隔，去空白与引号，忽略空项。

    返回空元组表示"没有覆盖，用默认表"。
    """
    if not raw:
        return ()
    parts = (part.strip().strip("'\"") for part in raw.replace(";", ",").split(","))
    return tuple(part for part in parts if part)


@dataclass(frozen=True)
class Settings:
    """运行期设置（不可变；全部有与原行为一致的默认值）。"""

    app_name: str = APP_NAME
    version: str = __version__
    log_level: str = DEFAULT_LOG_LEVEL
    log_file: str | None = None
    user_programs: str = ""
    video_fps: int = DEFAULT_VIDEO_FPS
    video_prefix: str = DEFAULT_VIDEO_PREFIX
    ui_font_preferences: tuple[str, ...] = DEFAULT_UI_FONT_PREFERENCES
    mono_font_preferences: tuple[str, ...] = DEFAULT_MONO_FONT_PREFERENCES

    def title(self) -> str:
        return f"{self.app_name} v{self.version}"

    def window_label(self) -> str:
        return f"{self.title()} {APP_TITLE_SUFFIX}"


def project_root() -> Path:
    """项目根目录（core/ 的上一级）。"""
    return Path(__file__).resolve().parent.parent


def default_log_path(root: str | os.PathLike[str] | None = None) -> Path:
    base = Path(root) if root is not None else project_root()
    return base / DEFAULT_LOG_DIRNAME / DEFAULT_LOG_FILENAME


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """从环境变量读取设置（缺省即基线行为）。"""
    source = os.environ if env is None else env

    level = (source.get(ENV_LOG_LEVEL) or DEFAULT_LOG_LEVEL).strip().upper()
    if level not in logging._nameToLevel:  # noqa: SLF001 - 标准库无公开查询接口
        level = DEFAULT_LOG_LEVEL

    raw_fps = (source.get("MESA_IDE_VIDEO_FPS") or "").strip()
    try:
        fps = int(raw_fps) if raw_fps else DEFAULT_VIDEO_FPS
    except ValueError:
        fps = DEFAULT_VIDEO_FPS
    if fps <= 0:
        fps = DEFAULT_VIDEO_FPS

    # 复用 core.project 的用户项目目录规则（含 MESA_PROGRAMS_DIR 覆盖）
    from core.project import user_programs_dir

    override = parse_font_preferences(source.get(ENV_UI_FONT))

    return Settings(
        log_level=level,
        log_file=(source.get(ENV_LOG_FILE) or "").strip() or None,
        user_programs=user_programs_dir(source),
        video_fps=fps,
        video_prefix=(source.get("MESA_IDE_VIDEO_PREFIX") or DEFAULT_VIDEO_PREFIX).strip()
        or DEFAULT_VIDEO_PREFIX,
        ui_font_preferences=override or DEFAULT_UI_FONT_PREFERENCES,
    )


def configure_logging(
    settings: Settings | None = None,
    *,
    stream: TextIO | None = None,
    force: bool = False,
) -> Path | None:
    """配置根 logger（文件 + 控制台），返回实际使用的日志文件路径。

    - 已配置过且 ``force=False`` 时直接返回（幂等）；
    - 日志文件不可写时降级为仅控制台，并把原因写入日志。
    """
    resolved = settings or load_settings()
    root_logger = logging.getLogger()

    if root_logger.handlers and not force:
        existing = getattr(root_logger, "_mesa_ide_log_path", None)
        return Path(existing) if existing else None

    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    level = logging._nameToLevel.get(resolved.log_level, logging.INFO)  # noqa: SLF001
    root_logger.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT)

    console = logging.StreamHandler(stream or sys.stderr)
    console.setFormatter(formatter)
    root_logger.addHandler(console)

    log_path: Path | None = Path(resolved.log_file) if resolved.log_file else default_log_path()
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except OSError as exc:
        logging.getLogger(__name__).warning("无法写入日志文件 %s: %s", log_path, exc)
        log_path = None

    root_logger._mesa_ide_log_path = str(log_path) if log_path else None  # type: ignore[attr-defined]
    logging.getLogger(__name__).info(
        "%s v%s 启动（日志级别 %s）", resolved.app_name, resolved.version, resolved.log_level
    )
    return log_path

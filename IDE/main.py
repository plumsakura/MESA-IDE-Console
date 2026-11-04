"""入口：MESA Control Console 启动面板。

相对基线的改动（阶段 4）：

- **P22**：版本号与日志级别来自 :mod:`core.config` 单一来源，不再硬编码；
- **P17**：核心模块导入失败时记录日志、给出可读错误并明确以退出码 1 结束；
- **裸 except 清理**：无法弹窗时记录警告而不是静默 ``pass``；
- **"已安装就检查"**：启动时检测 MESA 安装，在面板上显示一行状态
  （可用 / 不可用 + 路径），并把详细诊断写入日志。
"""

from __future__ import annotations

import logging
import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox
from typing import Callable

from core.config import configure_logging, load_settings
from core.env import MesaEnvironment, detect_mesa
from core.fonts import ensure_bundled_fonts
from ide_ui.fonts import apply_to_root

logger = logging.getLogger(__name__)

WINDOW_GEOMETRY = "600x400"
CREATE_BUTTON_TEXT = "创建新项目"
OPEN_BUTTON_TEXT = "打开老项目"


def mesa_status_text(detected: MesaEnvironment) -> str:
    """把一次 MESA 检测结果转成一行界面文案。"""
    if detected.is_valid:
        return f"MESA: 可用（{detected.mesa_dir}）"
    if detected.mesa_dir:
        return f"MESA: 不可用（{detected.mesa_dir}）"
    return "MESA: 未检测到"


def _report_startup_error(message: str) -> None:
    """尽力弹出图形错误提示；无显示环境时只记录日志。"""
    try:
        root_dummy = tk.Tk()
        root_dummy.withdraw()
        messagebox.showerror("启动错误", message)
        root_dummy.destroy()
    except tk.TclError:
        logger.warning("无显示环境，无法弹出图形错误提示")


def _import_features() -> tuple[Callable[..., object], Callable[..., object]] | None:
    """延迟导入功能模块：缺文件时给出可读错误而非半启动的界面。"""
    try:
        from create_new_program import create_new_program
        from open_old_program import open_old_program
    except ImportError as exc:
        logger.exception("核心模块导入失败")
        print(f"模块导入错误: {exc}", file=sys.stderr)
        _report_startup_error(f"无法找到核心脚本文件:\n{exc}")
        return None
    return create_new_program, open_old_program


def main() -> int:
    settings = load_settings()
    configure_logging(settings)

    detected = detect_mesa()
    logger.info("%s", detected.summary())
    for warning in detected.warnings:
        logger.warning("%s", warning)

    features = _import_features()
    if features is None:
        return 1
    create_new_program, open_old_program = features

    # 确保自带中文字体（界面 + 编辑器等宽）在用户字体目录就位（幂等；失败不阻断启动）
    try:
        font_results = ensure_bundled_fonts()
        for font_result in font_results:
            if font_result.copied:
                logger.info("已安装自带中文字体: %s", font_result.target)
            for warning in font_result.warnings:
                logger.warning("%s", warning)
    except Exception:  # noqa: BLE001 - 字体不是启动的必要条件
        logger.warning("自带字体安装失败，界面中文可能显示为方框", exc_info=True)

    root = tk.Tk()
    root.title(settings.title())
    root.geometry(WINDOW_GEOMETRY)
    if sys.platform == "win32":
        root.state("zoomed")
    else:
        root.attributes("-fullscreen", True)

    root.grid_rowconfigure([0, 1, 2, 3], weight=1)
    root.grid_columnconfigure(0, weight=1)

    # 修复"中文显示成方框"：原实现写死 Helvetica/Arial，在没装这些字体、也没有
    # 中文字体的 Linux 上会回落到 DejaVu Sans（无 CJK 字形）。这里按偏好表挑出
    # 系统上**真实可用**的字体族；有 Arial/Helvetica 的机器行为不变。
    ui_family = apply_to_root(
        root,
        preferences=settings.ui_font_preferences,
        mono_preferences=settings.mono_font_preferences,
    )
    logger.info("界面字体族: %s", ui_family)
    custom_font = tkfont.Font(family=ui_family, size=16, weight="bold")
    label_font = tkfont.Font(family=ui_family, size=10)

    def handle_create() -> None:
        try:
            create_new_program(root)
        except Exception as exc:  # noqa: BLE001 - 需向用户报告
            logger.exception("启动创建项目失败")
            messagebox.showerror("运行错误", f"启动创建项目失败:\n{str(exc)}")

    def handle_open() -> None:
        try:
            open_old_program(root)
        except Exception as exc:  # noqa: BLE001 - 需向用户报告
            logger.exception("启动打开项目失败")
            messagebox.showerror("打开老项目错误", f"启动打开项目失败:\n{str(exc)}")

    tk.Button(
        root, text=CREATE_BUTTON_TEXT, font=custom_font, width=25, height=3,
        bg="#e8f5e9", command=handle_create,
    ).grid(row=0, column=0, pady=20)

    tk.Button(
        root, text=OPEN_BUTTON_TEXT, font=custom_font, width=25, height=3,
        bg="#fffde7", command=handle_open,
    ).grid(row=1, column=0, pady=20)

    tk.Label(
        root,
        text=mesa_status_text(detected),
        fg="green" if detected.is_valid else "gray",
        font=label_font,
    ).grid(row=2, column=0, pady=(0, 4))

    tk.Label(root, text=settings.window_label(), fg="gray", font=label_font).grid(
        row=3, column=0, sticky="s", pady=10
    )

    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

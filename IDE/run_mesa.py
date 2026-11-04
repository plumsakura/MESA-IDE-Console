#!/usr/bin/env python3
"""通用启动脚本：检查虚拟环境 → 检查 MESA 环境 → 启动图形界面。

相对基线的改动（阶段 4）：

- **"已安装就检查"**：从原来的"只看 MESA_DIR 是否为空"改为
  :func:`core.env.detect_mesa` 的完整检测，并逐条打印 warnings 与修复提示；
- 启动前初始化日志（``core.config.configure_logging``），异常不再只打印到终端；
- 退出码明确：venv 缺失 → 1，正常退出 → 0。
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import sys
from pathlib import Path

from core.config import configure_logging, load_settings
from core.env import detect_mesa

logger = logging.getLogger(__name__)

MESA_HINT = (
    "  提示: 设置 MESA_DIR 指向 MESA 安装目录（例如 export MESA_DIR=~/mesa）。\n"
    "  未检测到 MESA 不影响 IDE 启动，但编译/运行 MESA 项目会失败。"
)


def venv_python(script_dir: Path, system: str | None = None) -> Path:
    """返回虚拟环境中的解释器路径（不存在时由调用方处理）。"""
    current = system or platform.system()
    if current == "Windows":
        return script_dir / "venv" / "Scripts" / "python"
    return script_dir / "venv" / "bin" / "python"


def report_mesa_environment(env=None) -> bool:
    """打印 MESA 环境诊断，返回是否可用。"""
    detected = detect_mesa(env=env)
    print(detected.summary())
    for warning in detected.warnings:
        print(f"  ⚠ {warning}")
    if not detected.is_valid:
        print(MESA_HINT)
    return detected.is_valid


def main() -> int:
    script_dir = Path(__file__).parent.absolute()
    os.chdir(script_dir)

    settings = load_settings()
    log_path = configure_logging(settings)
    logger.info("%s 启动器", settings.title())

    python_path = venv_python(script_dir)
    if not python_path.exists():
        print("错误: 虚拟环境不存在，请先运行: python install.py")
        input("按 Enter 键退出...")
        return 1

    print("检查 MESA 环境...")
    report_mesa_environment()

    print("启动 MESA IDE...")
    try:
        completed = subprocess.run([str(python_path), "main.py"], check=False)
    except KeyboardInterrupt:
        print("\n程序已退出")
        return 0
    except OSError as exc:
        logger.exception("启动失败")
        print(f"启动失败: {exc}")
        input("按 Enter 键退出...")
        return 1

    if log_path is not None:
        logger.info("界面已退出（返回码 %s），日志: %s", completed.returncode, log_path)
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main())

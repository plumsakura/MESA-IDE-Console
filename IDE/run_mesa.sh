#!/bin/bash
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

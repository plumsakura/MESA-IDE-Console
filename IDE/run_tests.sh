#!/usr/bin/env bash
# 项目快照测试运行器（标准库 unittest，无第三方测试依赖）。
#
# 用法:
#   ./run_tests.sh                 # 运行全部测试
#   ./run_tests.sh tests.test_db_snapshot   # 只运行某个模块
#
# 注意: 必须使用 venv 解释器（mesa_reader / matplotlib 只装在 venv 里）。
#
# 环境说明:
#   - MPLCONFIGDIR 指向工作区内的 .cache/，避免 matplotlib 因主目录不可写
#     而每次回退到临时目录（噪音 + 变慢）；
#   - UI 测试（Tk）需要能访问 X11 socket。受限沙箱/容器里 /tmp 常被换成
#     tmpfs，导致 /tmp/.X11-unix 不可见 —— 此时 Tk 测试会自动跳过而不是挂起
#     （探测逻辑见 tests/test_ui_components.py::tk_reachable）。
set -euo pipefail
cd "$(dirname "$0")"

export MPLCONFIGDIR="${MPLCONFIGDIR:-$PWD/.cache/matplotlib}"
mkdir -p "$MPLCONFIGDIR"

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
    if [ -x venv/bin/python ]; then
        PY=venv/bin/python
    else
        PY=python3
    fi
fi

echo "使用解释器: $($PY -c 'import sys; print(sys.executable)')"
echo "MPLCONFIGDIR: $MPLCONFIGDIR"
exec "$PY" -m unittest discover -s tests -t . -v "$@"

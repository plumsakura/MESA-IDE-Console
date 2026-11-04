#!/usr/bin/env bash
# ============================================================================
#  MESA IDE 一键引导安装（面向**空白 WSL2 / Linux**，也兼容 macOS）
# ============================================================================
#
#  用法：
#    bash install.sh                 # 交互式（缺什么问什么）
#    bash install.sh --yes           # 无人值守：自动补系统包 / 装 MESA / 装字体
#    bash install.sh --no-sudo       # 绝不调用 sudo：只体检 + 打印要装的包
#    bash install.sh --doctor        # 只体检，不安装任何东西
#    bash install.sh --help
#
#  这个脚本负责"把门打开"，真正的安装由 IDE/install.py 完成：
#
#    1. 定位 IDE/ 目录（放在仓库根、发行包根、symbolic link 都能认出来）
#    2. 找一个 Python >= 3.8（一个都没有时按发行版自动装）
#    3. 确认 venv + ensurepip 可用（Debian/Ubuntu 缺 python3-venv 会失败，自动补）
#    4. 确认 tkinter 可用（图形界面必需，自动补）
#    5. exec IDE/install.py（虚拟环境、依赖、MESA、字体、参数库、启动脚本、自检）
#
#  设计约束（与项目纪律一致）：
#    * 只在确实要装包时才用 sudo，且执行前把命令原样打印出来；
#    * 绝不修改应用源码，只改本机环境（venv / 用户字体 / mesa_env.sh / 启动脚本）；
#    * 幂等：重复运行不会重复装；任何一步失败都给出"复制即用"的修复命令。
# ============================================================================

set -euo pipefail

# ------------------------------------------------------------------ 输出工具

if [ -t 1 ]; then
    C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'
    C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_BLUE=$'\033[36m'
else
    C_RESET=""; C_BOLD=""; C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""
fi

say()   { printf '%s\n' "$*"; }
step()  { printf '\n%s[%s]%s %s\n' "$C_BLUE" "$1" "$C_RESET" "$2"; }
good()  { printf '%s✓%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn()  { printf '%s⚠%s %s\n' "$C_YELLOW" "$C_RESET" "$*"; }
bad()   { printf '%s×%s %s
' "$C_RED" "$C_RESET" "$*"; }
info()  { printf '  %s\n' "$*"; }
die()   { bad "$*"; exit 1; }

# ------------------------------------------------------------------ 参数解析

ASSUME_YES=0        # --yes：不再询问
NO_SUDO=0           # --no-sudo：绝不调用 sudo
DOCTOR=0            # --doctor：只体检
PASSTHROUGH=()      # 原样转交给 install.py 的参数

usage() {
    sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        -y|--yes)    ASSUME_YES=1; PASSTHROUGH+=("--yes") ;;
        --no-sudo|--no-system) NO_SUDO=1; PASSTHROUGH+=("--no-system") ;;
        --doctor|--check-only) DOCTOR=1 ;;
        -h|--help)   usage; exit 0 ;;
        *)           PASSTHROUGH+=("$1") ;;
    esac
    shift
done

# 中文输出兜底：C/POSIX locale 下 Python 打印非 ASCII 会直接报错
if [ -z "${LANG:-}" ] || [ "${LANG}" = "C" ] || [ "${LANG}" = "POSIX" ]; then
    if command -v locale >/dev/null 2>&1 && locale -a 2>/dev/null | grep -qi '^C\.utf-\?8$'; then
        export LANG=C.UTF-8
    fi
fi
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"

say "${C_BOLD}MESA IDE 安装引导${C_RESET}"

# ------------------------------------------------------------------ 定位源码

SELF_PATH="${BASH_SOURCE[0]}"
while [ -L "$SELF_PATH" ]; do
    link_target="$(readlink "$SELF_PATH")"
    case "$link_target" in
        /*) SELF_PATH="$link_target" ;;
        *)  SELF_PATH="$(dirname "$SELF_PATH")/$link_target" ;;
    esac
done
SCRIPT_DIR="$(cd "$(dirname "$SELF_PATH")" && pwd)"

IDE_DIR=""
for candidate in "$SCRIPT_DIR/IDE" "$SCRIPT_DIR" "$SCRIPT_DIR/../IDE"; do
    if [ -f "$candidate/install.py" ] && [ -f "$candidate/main.py" ]; then
        IDE_DIR="$(cd "$candidate" && pwd)"
        break
    fi
done
[ -n "$IDE_DIR" ] || die "找不到 IDE/ 目录（应包含 install.py 与 main.py）。请在发行包根目录运行本脚本。"
step "1/5" "源码目录: $IDE_DIR"

if [ -f "$IDE_DIR/requirements.txt" ]; then
    good "依赖清单 requirements.txt 已就位"
else
    die "发行包不完整：缺少 $IDE_DIR/requirements.txt"
fi
[ -f "$IDE_DIR/mesa_data.db" ] || warn "缺少 mesa_data.db（参数校验与搜索功能会受限）"

# ------------------------------------------------------------------ 包管理器

PM=""
PM_INSTALL=""
PM_UPDATE=""
for probe in apt-get:apt dnf:dnf yum:yum pacman:pacman zypper:zypper apk:apk; do
    binary="${probe%%:*}"
    if command -v "$binary" >/dev/null 2>&1; then
        PM="${probe##*:}"
        break
    fi
done

case "$PM" in
    apt)    PM_INSTALL="apt-get install -y";    PM_UPDATE="apt-get update" ;;
    dnf)    PM_INSTALL="dnf install -y";        PM_UPDATE="" ;;
    yum)    PM_INSTALL="yum install -y";        PM_UPDATE="" ;;
    pacman) PM_INSTALL="pacman -S --noconfirm"; PM_UPDATE="" ;;
    zypper) PM_INSTALL="zypper install -y";     PM_UPDATE="zypper refresh" ;;
    apk)    PM_INSTALL="apk add";               PM_UPDATE="apk update" ;;
    *)      PM="";                              PM_INSTALL=""; PM_UPDATE="" ;;
esac

SUDO=""
if [ "$NO_SUDO" -eq 0 ] && [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
fi

# ------------------------------------------------------------------ 装包辅助

print_install_command() {
    local packages="$1"
    if [ -n "$SUDO" ]; then
        info "将执行: $SUDO $PM_INSTALL $packages"
    else
        info "将执行: $PM_INSTALL $packages"
    fi
}

confirm() {
    # $1 = 问题；$2 = 默认答案（y/n，默认 n）
    local prompt="$1" default="${2:-n}" answer=""
    if [ "$ASSUME_YES" -eq 1 ]; then
        return 0
    fi
    if [ ! -t 0 ]; then
        return 1
    fi
    if [ "$default" = "y" ]; then
        printf '  %s [Y/n] ' "$prompt"
    else
        printf '  %s [y/N] ' "$prompt"
    fi
    read -r answer || answer=""
    answer="${answer:-$default}"
    case "$answer" in y|Y|yes|YES|Yes|是) return 0 ;; *) return 1 ;; esac
}

install_packages() {
    # 依次尝试候选包名，任一成功即返回 0
    local title="$1"; shift
    local package
    if [ -z "$PM" ]; then
        warn "未识别包管理器，请手动安装: $*（$title）"
        return 1
    fi
    if [ "$NO_SUDO" -eq 1 ]; then
        warn "已按 --no-sudo 跳过自动安装，请手动执行: ${SUDO}$PM_INSTALL $*"
        return 1
    fi
    if [ -n "$SUDO" ] && ! $SUDO -n true 2>/dev/null; then
        info "提示: 接下来的命令会要求输入 sudo 密码"
    fi
    if [ -n "$PM_UPDATE" ]; then
        info "更新软件源: ${SUDO:+$SUDO }$PM_UPDATE"
        ${SUDO:+$SUDO} $PM_UPDATE >/dev/null 2>&1 || warn "更新软件源失败（继续尝试安装）"
    fi
    for package in "$@"; do
        print_install_command "$package"
        # shellcheck disable=SC2086
        if ${SUDO:+$SUDO} $PM_INSTALL "$package"; then
            return 0
        fi
        warn "$package 安装失败，尝试下一个候选包名"
    done
    return 1
}

# ------------------------------------------------------------------ 找 Python

PYTHON=""
PYTHON_VERSION=""
try_python() {
    local candidate="$1" resolved
    command -v "$candidate" >/dev/null 2>&1 || return 1
    resolved="$(command -v "$candidate")"
    if "$resolved" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 8) else 1)' >/dev/null 2>&1; then
        PYTHON="$resolved"
        PYTHON_VERSION="$("$resolved" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
        return 0
    fi
    return 1
}

find_python() {
    local candidate
    for candidate in python3 python3.13 python3.12 python3.11 python3.10 python3.9 python3.8 python; do
        if try_python "$candidate"; then
            return 0
        fi
    done
    # 版本号不在候选表里的（例如 python3.14）：把所有 python3.x 都试一遍
    for candidate in $(compgen -c python3. 2>/dev/null | sort -u -Vr || true); do
        if try_python "$candidate"; then
            return 0
        fi
    done
    return 1
}

step "2/5" "查找 Python 3.8+ ..."
if find_python; then
    good "Python $PYTHON_VERSION（$PYTHON）"
else
    warn "没有找到 Python >= 3.8"
    case "$PM" in
        apt)    candidates="python3 python3-venv" ;;
        dnf|yum) candidates="python3" ;;
        pacman) candidates="python" ;;
        zypper) candidates="python3" ;;
        apk)    candidates="python3 py3-pip" ;;
        *)      candidates="" ;;
    esac
    if [ -z "$candidates" ]; then
        die "请先安装 Python 3.8+ 后重试（例如: sudo apt install python3 python3-venv）"
    fi
    if confirm "是否用 $PM 安装 Python（$candidates）？"; then
        # shellcheck disable=SC2086
        install_packages "Python 解释器" $candidates || true
        if ! find_python; then
            die "Python 安装后仍未找到，请手动安装 Python 3.8+ 后重新运行 bash install.sh"
        fi
        good "Python $PYTHON_VERSION（$PYTHON）"
    else
        die "已取消。安装 Python 3.8+ 后重新运行: bash install.sh"
    fi
fi

# ------------------------------------------------------------------ venv / tk

step "3/5" "检查 venv + ensurepip（建虚拟环境用）..."
if "$PYTHON" -c 'import venv, ensurepip' >/dev/null 2>&1; then
    good "venv + ensurepip 可用"
else
    warn "缺少 venv/ensurepip（Debian/Ubuntu 拆在 python${PYTHON_VERSION}-venv 包里）"
    case "$PM" in
        apt)
            if confirm "是否安装 python${PYTHON_VERSION}-venv？"; then
                install_packages "venv 支持" "python${PYTHON_VERSION}-venv" "python3-venv" || true
            fi
            ;;
        dnf|yum)
            if confirm "是否安装 python3-libs（提供 ensurepip）？"; then
                install_packages "venv 支持" python3-libs || true
            fi
            ;;
        apk)
            if confirm "是否安装 py3-virtualenv / py3-pip？"; then
                install_packages "venv 支持" py3-virtualenv py3-pip || true
            fi
            ;;
        *)
            warn "请手动安装 Python 的 venv/ensurepip 支持"
            ;;
    esac
    if "$PYTHON" -c 'import venv, ensurepip' >/dev/null 2>&1; then
        good "venv + ensurepip 已就绪"
    else
        warn "venv 仍不可用：安装可以继续，但第 3 步建虚拟环境会失败"
        case "$PM" in
            apt) info "手动修复: sudo apt install python${PYTHON_VERSION}-venv" ;;
        esac
    fi
fi

step "4/5" "检查 tkinter（图形界面用）..."
if "$PYTHON" -c 'import tkinter' >/dev/null 2>&1; then
    good "tkinter 可用"
else
    warn "缺少 tkinter，界面无法启动"
    case "$PM" in
        apt)
            if confirm "是否安装 python3-tk？"; then
                install_packages "tkinter" python3-tk || true
            fi
            ;;
        dnf|yum)
            if confirm "是否安装 python3-tkinter？"; then
                install_packages "tkinter" python3-tkinter || true
            fi
            ;;
        pacman)
            if confirm "是否安装 tk？"; then
                install_packages "tkinter" tk || true
            fi
            ;;
        zypper)
            if confirm "是否安装 python3-tk？"; then
                install_packages "tkinter" python3-tk || true
            fi
            ;;
        apk)
            if confirm "是否安装 py3-tkinter？"; then
                install_packages "tkinter" py3-tkinter || true
            fi
            ;;
        *)
            warn "请手动安装 tkinter（Debian/Ubuntu: python3-tk；Fedora: python3-tkinter；Arch: tk）"
            ;;
    esac
    if "$PYTHON" -c 'import tkinter' >/dev/null 2>&1; then
        good "tkinter 已就绪"
    else
        warn "tkinter 仍不可用：装完后可以用 python3 install.py --check 复查"
    fi
fi

# ------------------------------------------------------------------ 交给 install.py

if [ "$DOCTOR" -eq 1 ]; then
    step "5/5" "只体检（--doctor）"
    exec "$PYTHON" "$IDE_DIR/install.py" --check
fi

step "5/5" "交给安装器完成剩余步骤..."
info "解释器: $PYTHON（Python $PYTHON_VERSION）"
info "安装目录: $IDE_DIR"
if [ "$NO_SUDO" -eq 1 ]; then
    info "模式: --no-sudo（不会调用 sudo，也不会安装系统包）"
fi
if [ -n "$PM" ]; then
    info "包管理器: $PM"
fi
say ""

cd "$IDE_DIR"
if [ "${#PASSTHROUGH[@]}" -gt 0 ]; then
    exec "$PYTHON" install.py "${PASSTHROUGH[@]}"
fi
exec "$PYTHON" install.py

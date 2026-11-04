#!/usr/bin/env bash
# ============================================================================
#  MESA IDE 完整安装（IDE + MESA 源码 + MESA SDK）—— 一条命令
# ============================================================================
#
#  用法（在任意 WSL / Linux 里）:
#    bash packaging/install-all.sh                 # 交互式：缺什么问什么
#    bash packaging/install-all.sh --yes           # 全自动：补依赖 + 解压 + 编译
#    bash packaging/install-all.sh --skip-build    # 只装 IDE + 解压 MESA，不编译
#    bash packaging/install-all.sh --no-sudo       # 绝不调用 sudo（只打印命令）
#    bash packaging/install-all.sh --archives DIR  # 指定 MESA / SDK 归档所在目录
#
#  需要的两个官方归档（本仓库不包含，见 docs/DOWNLOADS.md）:
#    mesa-24.08.1.zip                    MESA 源码
#    mesasdk-x86_64-linux-24.7.1.tar.gz  MESA SDK
#
#  它做的事:
#    1. 找到 MESA / SDK 归档（当前目录、~/mesa、~/Downloads、~ 或 --archives）
#    2. 检查 ~/mesa 可写性（归档被 sudo 复制进来时属主会变成 root）
#    3. 把归档复制进 ~/mesa（以普通用户身份复制 → 属主正确）
#    4. IDE 就位：有发行包用发行包，否则直接用当前仓库源码
#    5. 调用 IDE/install.sh 完成：依赖 → 解压 → 编译 → 字体 → 自检
#
#  全程只写用户目录（~/mesa、~/MESA-IDE-1.1、~/.bashrc 标记块、用户字体目录），
#  系统包安装仅在需要且你同意时用 sudo，命令会先打印出来。
# ============================================================================

set -euo pipefail

# ------------------------------------------------------------------ 自定位
SCRIPT_PATH="${BASH_SOURCE[0]}"
while [ -L "$SCRIPT_PATH" ]; do
    target="$(readlink "$SCRIPT_PATH")"
    case "$target" in
        /*) SCRIPT_PATH="$target" ;;
        *)  SCRIPT_PATH="$(dirname "$SCRIPT_PATH")/$target" ;;
    esac
done
PKG_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
REPO_DIR="$(cd "$PKG_DIR/.." && pwd)"

IDE_PKG="MESA-IDE-1.1-linux.tar.gz"
MESA_ZIP="mesa-24.08.1.zip"
SDK_TGZ="mesasdk-x86_64-linux-24.7.1.tar.gz"
MESA_URL="https://doi.org/10.5281/zenodo.2602941"
SDK_URL="https://user.astro.wisc.edu/~townsend/static.php?ref=mesasdk"

# ------------------------------------------------------------------ 输出
say()  { printf '%s\n' "$*"; }
good() { printf '✓ %s\n' "$*"; }
bad()  { printf '× %s\n' "$*"; }

# ------------------------------------------------------------------ 参数
ASSUME_YES=0
SKIP_BUILD=0
ARCHIVE_DIR=""
PASSTHROUGH=()
usage() { sed -n '3,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }
while [ "$#" -gt 0 ]; do
    case "$1" in
        -y|--yes)        ASSUME_YES=1; PASSTHROUGH+=("--yes") ;;
        --skip-build)    SKIP_BUILD=1; PASSTHROUGH+=("--no-mesa") ;;
        --no-sudo|--no-system) PASSTHROUGH+=("--no-system") ;;
        --archives)      shift; ARCHIVE_DIR="${1:-}" ;;
        -h|--help)       usage; exit 0 ;;
        *)               PASSTHROUGH+=("$1") ;;
    esac
    shift
done

# 中文输出兜底
if [ -z "${LANG:-}" ] || [ "${LANG}" = "C" ] || [ "${LANG}" = "POSIX" ]; then
    export LANG=C.UTF-8
fi
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"

say "MESA IDE 完整安装（IDE + MESA 源码 + MESA SDK）"
say "  脚本目录: $PKG_DIR"

# ------------------------------------------------------------------ 1. 找归档
find_archive() {
    local name="$1"
    shift
    local dir
    for dir in "$@"; do
        [ -n "$dir" ] || continue
        if [ -f "$dir/$name" ]; then
            printf '%s\n' "$dir/$name"
            return 0
        fi
    done
    return 1
}

CANDIDATE_DIRS=("$PKG_DIR" "${ARCHIVE_DIR:-}" "$HOME/mesa" "$HOME/Downloads" "$HOME")
MESA_PATH="$(find_archive "$MESA_ZIP" "${CANDIDATE_DIRS[@]}" || true)"
SDK_PATH="$(find_archive "$SDK_TGZ" "${CANDIDATE_DIRS[@]}" || true)"

if [ -z "$MESA_PATH" ] || [ -z "$SDK_PATH" ]; then
    bad "缺少 MESA 归档，本仓库不包含它们（体积约 2 GB）。"
    [ -z "$MESA_PATH" ] && say "  未找到: $MESA_ZIP"
    [ -z "$SDK_PATH" ]  && say "  未找到: $SDK_TGZ"
    say ""
    say "  请从官方渠道下载后，放到 $HOME/mesa（或 --archives 指定的目录）："
    say "    MESA 源码 : $MESA_URL"
    say "    MESA SDK  : $SDK_URL"
    say ""
    say "  版本与校验值见 docs/DOWNLOADS.md；只想先装 IDE 可用 --skip-build。"
    if [ "$SKIP_BUILD" -eq 0 ]; then
        exit 1
    fi
else
    good "找到 MESA 归档: $MESA_PATH"
    good "找到 SDK 归档 : $SDK_PATH"
fi

# ------------------------------------------------------------------ 2. ~/mesa 可写性
MESA_HOME="$HOME/mesa"
if [ -e "$MESA_HOME" ] && [ ! -w "$MESA_HOME" ]; then
    bad "目录不可写: $MESA_HOME"
    say "  常见原因：归档之前是用 sudo / Windows 管理员方式复制进来的，目录属主变成了 root。"
    say "  请执行下面命令修复（一次性），然后重新运行本脚本："
    say ""
    say "    sudo chown -R \"\$(id -un):\$(id -gn)\" \"$MESA_HOME\""
    say ""
    exit 1
fi

# ------------------------------------------------------------------ 3. 复制归档
mkdir -p "$MESA_HOME"
copy_if_needed() {
    local src="$1" dst="$2"
    local size_src size_dst
    size_src="$(stat -c%s "$src" 2>/dev/null || echo 0)"
    size_dst="$(stat -c%s "$dst" 2>/dev/null || echo 0)"
    if [ -f "$dst" ] && [ "$size_dst" = "$size_src" ]; then
        good "已存在（大小一致，跳过）: $dst"
        return 0
    fi
    say "  复制 $(basename "$src")（约 $(( size_src / 1024 / 1024 / 1024 )) GB，请稍候）..."
    cp "$src" "$dst.tmp" && mv "$dst.tmp" "$dst"
    good "已复制: $dst"
}
[ -n "$MESA_PATH" ] && copy_if_needed "$MESA_PATH" "$MESA_HOME/$MESA_ZIP"
[ -n "$SDK_PATH" ]  && copy_if_needed "$SDK_PATH"  "$MESA_HOME/$SDK_TGZ"

# ------------------------------------------------------------------ 4. IDE 就位
IDE_ROOT="$HOME/MESA-IDE-1.1"
if [ -f "$PKG_DIR/$IDE_PKG" ]; then
    say "解出 IDE 发行包 → $IDE_ROOT"
    mkdir -p "$IDE_ROOT"
    tar -xzf "$PKG_DIR/$IDE_PKG" -C "$IDE_ROOT" --strip-components=1
elif [ -f "$REPO_DIR/install.sh" ] && [ -d "$REPO_DIR/IDE" ]; then
    say "从仓库源码安装 → $IDE_ROOT"
    mkdir -p "$IDE_ROOT"
    if command -v rsync >/dev/null 2>&1; then
        rsync -a --delete --exclude '.git' --exclude 'venv' "$REPO_DIR"/ "$IDE_ROOT"/
    else
        tar -C "$REPO_DIR" --exclude '.git' --exclude 'venv' -cf - . | tar -C "$IDE_ROOT" -xf -
    fi
else
    bad "既没有发行包 $IDE_PKG，也不在仓库目录里（找不到 $REPO_DIR/install.sh）"
    exit 1
fi
good "IDE 已就位: $IDE_ROOT"

# ------------------------------------------------------------------ 5. 交给安装器
say ""
say "启动安装器（venv → 依赖 → MESA → 字体 → 自检）..."
if [ "$SKIP_BUILD" -eq 1 ]; then
    say "  已按 --skip-build 跳过 MESA 编译（只解压源码，编译可稍后单独跑）。"
fi
cd "$IDE_ROOT"
bash install.sh "${PASSTHROUGH[@]}"
status=$?

say ""
say "======================================================"
if [ "$status" -eq 0 ]; then
    good "安装完成"
    say "开始使用:"
    say "  $IDE_ROOT/IDE/run_mesa.sh   # 启动 MESA IDE"
    say "  启动后："
    say "    「创建新项目」 → 复制 MESA 官方 star/work 模板，起一个项目名即可"
    say "    「打开老项目」 → 选择已有项目目录（或从 MESA test_suite 选）"
    say "    「编译运行」   → 在新终端执行 ./mk && ./rn（会先询问是否实时画图）"
    say "    「HR图轨迹 / 内部剖面」 → 按 history/profile 数据画图"
    say "  MESA 环境脚本: $IDE_ROOT/IDE/mesa_env.sh（终端编译运行会自动加载）"
    if [ "$SKIP_BUILD" -eq 1 ]; then
        say "  稍后编译 MESA: cd $IDE_ROOT && MESA_IDE_AGREE_MESA_INSTALL=1 bash install.sh --yes"
    fi
else
    bad "安装未完全成功（退出码 $status）；日志: $IDE_ROOT/IDE/mesa_install.log"
fi
say "======================================================"
exit "$status"

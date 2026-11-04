# packaging/ —— 一键安装脚本

这个目录放"把 IDE、MESA 源码、MESA SDK 一起装好"的脚本。MESA 与 SDK 归档
**不在仓库里**（见 [../docs/DOWNLOADS.md](../docs/DOWNLOADS.md)），需要你自己下载。

## 用法

```bash
# 1. 下载两个官方归档，放进 ~/mesa（或任意目录）
#    mesa-24.08.1.zip
#    mesasdk-x86_64-linux-24.7.1.tar.gz

# 2. 在仓库根目录执行
bash packaging/install-all.sh --yes

# 或者把它们放在别处
bash packaging/install-all.sh --archives /mnt/e/mesa --yes
```

脚本会依次：

1. 在 `packaging/`、`--archives`、`~/mesa`、`~/Downloads`、`~` 里查找两个归档，
   找不到就打印官方下载地址后退出（`--skip-build` 时只提示不退出）；
2. 检查 `~/mesa` 是否可写（归档被 `sudo` 复制进来时属主会变成 root，脚本给出
   `chown` 修复命令而不是直接崩溃）；
3. 以普通用户身份把归档复制进 `~/mesa`（大小一致则跳过，可重复执行）；
4. 准备 IDE 目录：同目录有 `MESA-IDE-<版本>-linux.tar.gz` 用它解包，否则直接
   复制当前仓库源码到 `~/MESA-IDE-1.1`；
5. 调用 `install.sh` 完成：系统依赖 → venv → Python 依赖 → 解压并编译 MESA
   （约 15–40 分钟）→ 装中文字体 → 自检。

## 开关

| 开关 | 作用 |
|---|---|
| `--yes` | 无人值守，缺系统包时自动 `sudo` 安装 |
| `--skip-build` | 只装 IDE、解压 MESA 源码，不编译 |
| `--no-sudo` | 绝不调用 `sudo`，只打印需要执行的命令 |
| `--archives DIR` | 指定 MESA / SDK 归档所在目录 |

## 环境变量

| 变量 | 作用 |
|---|---|
| `MESA_IDE_PIP_INDEX_URL` | 指定 pip 镜像，例如 `https://pypi.tuna.tsinghua.edu.cn/simple` |
| `MESA_IDE_AGREE_MESA_INSTALL=1` | 稍后单独补编译 MESA 时跳过确认 |

## 装完之后

```bash
~/MESA-IDE-1.1/IDE/run_mesa.sh
```

MESA 环境写在 `~/MESA-IDE-1.1/IDE/mesa_env.sh`，终端里编译运行会自动加载。

# MESA IDE 1.1 安装说明（Linux / WSL2）

版本：**1.1**（构建于 2026-10-15）

这是一个**源码安装**项目：仓库里不含虚拟环境、不含编译产物，也**不含 MESA 源码
与 MESA SDK**（各约 2 GB / 300 MB，需从官方渠道下载，见
[docs/DOWNLOADS.md](docs/DOWNLOADS.md)）。目标机器上由安装脚本就地创建
`IDE/venv`、安装依赖、配置 MESA 环境——从空白 WSL2 / 空白 Linux 装起来，与从
别人机器上装起来是一样的。

---

## 一、最快路径

### 方式 A：从仓库安装（推荐）

```bash
git clone https://github.com/plumsakura/MESA-IDE-Console.git
cd MESA-IDE-Console
bash install.sh --yes           # 装依赖 → venv → 依赖 → 字体 →（可选）MESA
./IDE/run_mesa.sh               # 启动
```

### 方式 B：发行包

```bash
tar -xzf MESA-IDE-1.1-linux.tar.gz
cd MESA-IDE-1.1
bash install.sh                 # 交互式：缺什么问什么
```

### 方式 C：完整安装包（IDE + MESA 源码 + SDK，一条命令）

先按 [docs/DOWNLOADS.md](docs/DOWNLOADS.md) 下载两个官方归档，然后：

```bash
bash packaging/install-all.sh --yes            # 归档放 ~/mesa 或 --archives 指定
bash packaging/install-all.sh --skip-build     # 只装 IDE + 解压源码，不编译
```

脚本会：找归档 → 复制进 `~/mesa` → IDE 就位 → 补系统依赖 → 解压并编译 MESA
（约 15–40 分钟）→ 装中文字体 → 自检。详见 [packaging/README.md](packaging/README.md)。

### 启动

```bash
~/MESA-IDE-1.1/IDE/run_mesa.sh      # 或 cd MESA-IDE-Console/IDE && ./run_mesa.sh
```

面板上会显示 MESA 状态一行；点「创建新项目 / 打开老项目」即可开工：

- 「创建新项目」→ 复制 MESA 官方 `star/work` 模板，起个名字；
- 「打开老项目」→ 选择已有项目目录（或从 MESA `star/test_suite` 选）；
- 「编译运行」→ 在新终端执行 `./mk && ./rn`（先询问是否实时画图）；
- 「HR图轨迹 / 内部剖面」→ 运行结束后按 history/profile 数据画图。

---

## 二、安装器实际做了什么

| 步骤 | 内容 | 需要 sudo？ |
|---|---|---|
| 1 | 找 Python ≥ 3.8（没有则按发行版自动安装） | 仅这一步 |
| 2 | 补齐 `python3-venv`、`python3-tk`、`unzip`、`build-essential`（make + glibc 开发文件）、`zlib1g-dev`、`ffmpeg` | 仅这一步 |
| 3 | 在 `IDE/venv` 建虚拟环境；**已有但损坏的 venv 自动重建** | 否 |
| 4 | 安装 `mesa_reader` / `matplotlib` 等依赖（pip 内置重试，弱网可换镜像） | 否 |
| 5 | 检测 MESA：已编译→写环境；有归档→经同意后解压并编译；都没有→给官方下载指引 | 否 |
| 6 | 把自带中文字体（Noto Sans SC + Noto Sans Mono CJK SC，完整版）装进用户字体目录 | 否 |
| 7 | 校验 `mesa_data.db`（4147 个 MESA 参数 + FTS） | 否 |
| 8 | 生成 `IDE/run_mesa.sh`，打印**开始使用提示**，并对整条链路自检 | 否 |

安装器**不修改任何应用源码**，只改本机环境：`IDE/venv/`、用户字体目录、
`IDE/mesa_env.sh`（MESA 环境变量）、`~/.bashrc` 标记块、启动脚本。
重复运行是幂等的：已完成的步骤自动跳过（Ctrl-C 中断后重跑会从编译继续）。

---

## 三、常用开关

```bash
bash install.sh --yes            # 全自动：系统包 / MESA / 字体不再询问
bash install.sh --no-sudo        # 绝不调用 sudo（只体检 + 打印要装的包）
bash install.sh --doctor         # 只体检，不安装任何东西
bash install.sh --no-mesa        # 只装 IDE，不碰 MESA
bash install.sh --archives DIR   # MESA 归档所在目录（挂载的 Windows 盘也可）
bash install.sh --offline        # 只用随包 wheels/ 装 Python 依赖
bash install.sh --dry-run        # 只打印将要执行的步骤
```

---

## 四、离线安装 / 网络差

- pip 已内置 `--retries 12 --timeout 90`；仍失败换国内镜像：

```bash
MESA_IDE_PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple bash install.sh --yes
```

- 用带 `wheels/` 的离线包：`bash install.sh --offline --wheels /path/to/wheels`。

---

## 五、MESA 本体（编译/运行模拟才需要）

**版本**：本项目在 **MESA 24.08.1 + MESA SDK 24.7.1** 上验证通过。

**下载**：

| 归档 | 官方地址 | 校验（SHA-256） |
|---|---|---|
| `mesa-24.08.1.zip` | <https://doi.org/10.5281/zenodo.2602941> | `bd4a18c6…a6818d6` |
| `mesasdk-x86_64-linux-24.7.1.tar.gz` | <https://user.astro.wisc.edu/~townsend/static.php?ref=mesasdk> | `a3705f20…8fd5a0` |

完整说明与放置位置见 [docs/DOWNLOADS.md](docs/DOWNLOADS.md)。

安装器支持**从官方归档开始配置**：

1. 把归档放到 `~/mesa`、`~/Downloads` 或 `~`；或用 `--archives` 直接指向
   Windows 盘（如 `/mnt/e/mesa`），无需复制进 WSL；
2. 运行 `bash install.sh --yes`，安装器会：解压到正确位置
   （`~/mesasdk`、`~/mesa/mesa-<版本>`，自动处理归档顶层目录，并**自动修复**
   历史版本造成的双重嵌套）→ 补装编译依赖 → 用 SDK 的 gfortran 编译
   （日志 `IDE/mesa_install.log`，约 15–40 分钟）。

已有 MESA 时只做"检查 + 写环境"：`export MESA_DIR=$HOME/mesa/mesa-24.08.1`。

> 终端里的「编译运行」会**显式加载 `IDE/mesa_env.sh`**，不依赖交互式
> `.bashrc`（WSL 弹出的新终端是非交互 shell，读不到 .bashrc 的环境块）。

---

## 六、卸载

```bash
rm -rf ~/MESA-IDE-1.1                                      # 安装目录（含 venv）
rm -f  ~/.local/share/fonts/NotoSansSC-Regular.otf         # 自带界面字体（可选）
rm -f  ~/.local/share/fonts/NotoSansMonoCJKsc-Regular.otf  # 自带等宽字体（可选）
# ~/.bashrc 里 "# >>> MESA IDE: MESA environment >>>" 标记块（可选，装了 MESA 才有）
```

---

## 七、排错

| 现象 | 处理 |
|---|---|
| `ensurepip is not available` | `sudo apt install python3-venv` |
| `No module named tkinter` | `sudo apt install python3-tk` |
| `ModuleNotFoundError: matplotlib` | `cd IDE && python3 install.py` 重装依赖 |
| 中文显示成方框 | 安装器会装自带完整字体；仍不行 `MESA_IDE_UI_FONT="Noto Sans SC" ./IDE/run_mesa.sh` |
| WSL2 里窗口不显示 | 需要 WSLg（Windows 11）；`bash install.sh --doctor` 会报 DISPLAY 状态 |
| 目录不可写 `~/mesa` | 归档曾被 sudo/管理员复制进来：`sudo chown -R "$(id -un):$(id -gn)" ~/mesa` 后重跑 |
| `./mk` 报 MESA_DIR 未设置 | 本版终端命令已显式加载 `mesa_env.sh`，重装或更新安装目录即可 |
| MESA 编译失败 | 看 `IDE/mesa_install.log`；确认磁盘 ≥ 22 GB、已装 build-essential 与 zlib1g-dev |
| 依赖装不上（网络） | 见第四节：镜像或 `--offline --wheels` |
| 参数搜索/校验说数据库缺失 | 确认 `IDE/mesa_data.db` 存在（随仓库提供） |

体检一条命令：`cd IDE && python3 install.py --check`

---

## 八、已知问题（现阶段）

- **pgstar 实时绘图窗口在 WSL 下暂不弹出**：`./mk && ./rn` 与日志/数据输出正常，
  「编译运行」的实时画图询问与官方 `*_win_flag` 开关已就位，属待修复项。
- 部分 MESA 语义校验是启发式，可能对数组型参数误报。

---

## 九、开发/测试（可选）

```bash
cd IDE
./run_tests.sh                                  # 全量标准库 unittest
venv/bin/python -m unittest tests.test_core_db  # 单个模块
xvfb-run -a ./run_tests.sh                      # 无 X11 环境
```

有 X11 时全量通过；无头环境 Tk 用例自动跳过。详见
[docs/TESTING.md](docs/TESTING.md)。

# 开发与重构记录

本文说明这个项目是怎么从"能跑的脚本"变成"可维护的工程"的，以及继续开发时
需要遵守的约定。

## 1. 起点与目标

最初版本是一个约 400 行的 `IDE.py` 加一组独立脚本：功能齐，但界面逻辑、数据
访问、进程调用混在一起，改一个按钮要读通整个文件，也没法在无图形环境里测试。

重构目标只有两条：

1. **行为不变**：所有用户可见的行为先被测试固定下来，再动结构；
2. **可测试**：核心逻辑离开 Tk 也能跑，能在 CI 与无显示服务器上验证。

## 2. 阶段划分

| 阶段 | 内容 | 产出 |
|---|---|---|
| 0 | 基线锁定 | 冻结当前行为，记录已知缺陷清单（编号 P1…P22） |
| 1 | 行为快照测试 | 先给旧代码补测试，锁住输出，后续重构才有"不变"的判据 |
| 2 | `core` 抽取 | `env` / `db` / `linting` / `project` / `mesa.commands` / `mesa.terminal` 逐个迁出 |
| 3 | UI 拆分与去重 | `IDE.py` 拆成 `ide_ui/app.py` + 视图模块，清掉 9 处重复方法定义 |
| 4 | 非阻塞任务与日志 | 长任务走后台 `Popen`，`print` 改为 `logging`，CLI 开关补齐 |
| 5 | 真实链路验证 | 假 MESA 项目集成测试、真实 `LOGS/` 解析、真实 ffmpeg、真实 MESA 全流程、自带字体、CI |
| 6 | 视频模块对照官方手册 | 按 MESA 26.4.1《Using PGSTAR》校正帧序列规则与 ffmpeg 参数 |

每个批次都要求：**先有测试，再改代码，测试与实现同一次提交**。重构期间
`test_protocol_snapshot.py` 的作用最大——它把"点按钮会发生什么"变成可审阅的
文本 diff。

## 3. 工程约定

### 分层

- `core/` 只允许标准库；不 import `tkinter`、`matplotlib`；
- `ide_ui/` 不直接 import `sqlite3`、`subprocess`；
- 入口脚本（`main.py`、`run_mesa.py`、`install.py`）只做编排，不写业务规则。

违反会被 `tests/test_architecture_guards.py` 拦下。

### 外部命令

- 一律 argv 列表，`shell=False`；
- 需要在 shell 里串起来的（`./mk && ./rn`）由 `core.mesa.commands` 生成，
  每段命令单独转义，`&&` 只出现在命令之间；
- 新命令必须同步 `test_protocol_snapshot.py`。

### 错误处理

- 用 `logging` 记录，不用 `print`；
- 不写裸 `except: pass`；确实要吞异常时，至少记录 `warning` 并说明原因；
- 面向用户的错误要给出**可复制的修复命令**，而不是栈信息。

### 版本与配置

- 版本号只在 `core/config.py` 定义一次，`main.py` / `install.py` / `run_mesa.py`
  都从那里读；
- 路径、超时、轮询间隔等常量集中在模块顶部，不散落在函数里。

## 4. 新增一个工具栏动作

以「导出当前 inlist 快照」为例：

1. 在 `core/` 里实现纯逻辑（读写文件、校验路径），返回结构化结果或抛明确异常；
2. 若要执行外部命令，在 `core/mesa/commands.py` 的 `build()` 里加一个 action，
   并在 `tests/test_protocol_snapshot.py` 里补期望值；
3. 在 `ide_ui/app.py` 里绑定按钮，只负责取参数、调 core、把结果显示到诊断面板；
4. 补测试：核心逻辑一个用例，界面动作一个用例（无显示时跳过）；
5. 更新 `README.md` 的功能表与 `CHANGELOG.md`。

## 5. 提交与分支

- 从 `main` 切分支，PR 描述写清动机与验证方式；
- 一次提交只做一件事，提交信息用「动词 + 对象」开头，正文说明为什么；
- 不提交 `venv/`、`__pycache__/`、`mesa_env.sh`、日志；外部归档（MESA / SDK）
  一律不入库（见 `docs/DOWNLOADS.md`）。

## 6. 已知的坑

- **WSL2 下的 pgstar 窗口**：`pgstar` 的 X11 窗口在 WSLg 下不总是显示，
  数据输出正常。排查时先确认 `echo $DISPLAY` 与 `xeyes` 是否能开窗；
- **字体缓存**：改动 `assets/fonts/` 后 Linux 需要 `fc-cache -f`，否则 Tk 仍用旧字体；
- **路径含中文/空格**：测试夹具里刻意包含这类路径，回归时不要删；
- **真实 MESA 版本差异**：参数库按 24.08.1 校对；换版本后若出现参数名告警，
  先核对 `$MESA_DIR/star/defaults/*.defaults`。

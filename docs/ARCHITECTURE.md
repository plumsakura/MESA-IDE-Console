# 架构说明

本文说明 MESA IDE 的分层、模块职责、关键数据流，以及几个刻意的设计取舍。
读代码前先看这里，能少走很多弯路。

## 1. 三层结构

```
┌──────────────────────────────────────────────────────────────┐
│ 入口脚本   main.py / install.py / run_mesa.py / *.py 薄封装   │
├──────────────────────────────────────────────────────────────┤
│ 表现层     ide_ui/      Tk 视图与交互，只做「组装 + 动作编排」 │
├──────────────────────────────────────────────────────────────┤
│ 业务层     core/        纯标准库逻辑，可在无图形环境单独运行   │
└──────────────────────────────────────────────────────────────┘
                    ↓ 只经由 argv 列表
        MESA 工具链（./mk ./rn ./re ./clean）、ffmpeg、matplotlib
```

依赖方向**只能向下**：`ide_ui` 可以 import `core`，`core` 不知道 `ide_ui` 的存在。
这条规则由 `tests/test_architecture_guards.py` 用 `ast` 静态解析强制执行：

- `core/` 不得 import `tkinter` / `matplotlib`（保证核心逻辑可在 CI、SSH、容器里测试）；
- `ide_ui/` 不得直接 import `sqlite3` / `subprocess`（数据访问与进程管理必须经 `core`）；
- 同一类里不得出现重复方法定义（历史上 `IDE.py` 有 9 处，后者静默覆盖前者）。

## 2. 模块职责

### 表现层 `IDE/ide_ui/`

| 模块 | 职责 |
|---|---|
| `app.py` | 主窗口：组装各视图、绑定工具栏动作、协调 `core` 调用 |
| `editor.py` | 多标签文本编辑器，标签以绝对路径为键 |
| `project_tree.py` | 左侧项目文件树，双击打开文件 |
| `search_bar.py` | 参数名搜索框（调 `core.db` 的 FTS5 查询） |
| `diagnostics.py` | 底部诊断面板：显示校验结果、视频帧数、任务状态 |
| `fonts.py` | 把自带字体应用到 Tk 控件 |

### 业务层 `IDE/core/`

| 模块 | 职责 | 关键约束 |
|---|---|---|
| `config.py` | 版本号、设置、日志配置 | 版本号单一来源 |
| `env.py` | MESA 环境检测与自动发现 | 任何失败都要留有 `warnings` 与 `source` |
| `project.py` | 模板定位、项目创建、inlist 文件常量 | 拒绝 `..` 与路径分隔符 |
| `db.py` | `mesa_data.db` 访问（参数名、FTS5 前缀查询） | 缺库时返回空结果而非抛异常 |
| `linting/inlist.py` | namelist 语法与参数名校验 | 只返回结构化 `Issue`，不含 UI 文案 |
| `mesa/commands.py` | **命令构造**（按钮 → 命令的冻结协议） | 每个命令是 argv 列表，`&&` 只在命令之间连接 |
| `mesa/terminal.py` | 在新终端窗口执行命令 | 显式加载 `mesa_env.sh`，不依赖交互式 shell |
| `mesa/reader.py` | 解析 `LOGS/history.data`、`profile*.data` | 不依赖 numpy / matplotlib |
| `mesa/outputs.py` | 从 inlist 解析输出路径（`log_directory` 等） | 与 MESA 默认值保持一致 |
| `mesa/frames.py` | pgstar PNG 帧序列校验 | 只回答"目录里有哪些帧" |
| `video.py` | ffmpeg 合成视频（冻结行为） | 编码参数固定，便于复现 |
| `jobs.py` | 后台进程抽象（`Popen` + 回调 + 取消） | 禁止 `shell=True` |
| `mesa_install.py` | MESA 安装规划与执行（解压 SDK / 源码 / `./install`） | 只返回布尔与日志，不弹窗 |
| `fonts.py` | 自带字体安装到用户字体目录 | Linux 需刷新 fontconfig 缓存 |

### 入口脚本

- `main.py`：启动面板（MESA 状态 + 创建 / 打开项目）；
- `run_mesa.py` / `run_mesa.sh`：先检查 venv 与 MESA 环境，再拉起界面；
- `install.py`：安装器，见 [DEVELOPMENT.md](DEVELOPMENT.md)；
- `IDE.py`、`create_new_program.py` 等：兼容门面，保留旧导入路径。

## 3. 关键数据流

### 创建项目

```
按钮「创建新项目」
  → core.project.locate_template()      # 从 $MESA_DIR/star/work 等布局定位
  → core.project.create_project(name)   # 复制模板、补齐 columns 文件、建 png/
  → ide_ui.app 打开项目编辑器
```

### 编译运行

```
按钮「编译运行」
  → 询问是否开启 pgstar 实时绘图
  → core.mesa.outputs.set_pgstar_live_windows()   # 改 inlist_pgstar 的 *_win_flag
  → core.mesa.commands.build("compile_run")       # ["bash","-ic","./mk && ./rn"]
  → core.mesa.terminal.launch()                   # 新终端窗口，加载 mesa_env.sh
```

命令构造是**冻结协议**：新增或修改按钮行为必须同时更新
`tests/test_protocol_snapshot.py`，否则测试会失败——这是刻意的，避免界面行为
在无人察觉时漂移。

### 出图

```
按钮「HR图轨迹」/「内部剖面」
  → core.mesa.outputs.resolve()      # 从 inlist 读出 LOGS/ 与 profiles 路径
  → core.mesa.reader.load_history()  # 纯 Python 解析，Fortran 的 d0 指数转 e
  → mesa_plotter.plot_*()            # matplotlib 渲染 + 缩放/保存工具栏
```

### 视频

```
按钮「生成视频」
  → core.mesa.frames.scan()      # 目录里匹配 <prefix>_*.png，检查序号连续
  → core.video.MesaVideoTask     # ffmpeg -pattern_type glob ... libx264
  → core.jobs.Job                # 后台执行，回调显示进度，可取消
```

## 4. 设计取舍

**为什么把 `core` 限制成纯标准库？**
MESA 用户常在无图形界面的服务器上跑批处理。核心逻辑不碰 Tk 与 matplotlib，
就能在 5 秒内用标准库 `unittest` 跑完，也能在 CI 里验证。代价是绘图与字体
必须放在外层，接口要设计得更干净——这个代价是值得的。

**为什么冻结命令协议？**
「界面上点一下到底执行了什么」是这个工具最需要被信任的部分。把映射关系写成
数据（`build(action)`）并用快照测试固定，用户和我都能明确知道按钮的副作用；
改动会留下显式的 diff，而不是悄悄换了一条命令。

**为什么不用 `shell=True` 拼字符串？**
项目名、路径都可能带空格、引号、中文。拼字符串迟早出错，且是注入面。
统一 argv 列表 + 必要的转义，出错时错误信息也更准确。

**为什么自带字体？**
空白 WSL2 的中文字体经常缺失，Tk 默认字体显示中文会变成方块。打包完整字形
（约 32 MB）换来"装完即用"，比让用户自己折腾 `fc-cache` 更符合操作台的定位。
字体按 SIL OFL 分发，可再分发。

**为什么安装器这么长？**
安装失败是这类工具最常见的劝退点。`install.py` 把"这台机器是什么、缺什么、
怎么补、补完怎么验证"逐条打印出来，并保证幂等——重跑不会把环境搞坏。

## 5. 线程与进程模型

- UI 线程只做界面更新，长任务（视频合成、MESA 编译、安装）一律走
  `core.jobs.Job`，通过回调回到 UI 线程；
- 需要新终端窗口的命令（`./mk && ./rn`）以 `detached` 方式启动，IDE 退出不影响
  正在跑的模拟；
- 所有子进程句柄由 `Job` 持有，窗口关闭或重新发起任务时先结束旧进程，
  避免孤儿 `ffmpeg` / `star`。

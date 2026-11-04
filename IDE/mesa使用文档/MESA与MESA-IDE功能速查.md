# MESA 与 MESA-IDE 功能速查（要点版）

> 用途：一页看懂「MESA 有哪些基础功能」和「MESA-IDE 提供了哪些功能」。
> 依据：MESA 官方手册（26.4.1「Using MESA」，离线中英对照见本目录 `zh/`、`en/`）
> 与 MESA-IDE 当前实现（`IDE/`）。**越简单越好，只列要点。**

---

## 一、MESA 是什么

- 恒星演化模拟软件（Modules for Experiments in Stellar Astrophysics），Fortran 编写。
- 本质是「**一堆模块 + 一个 star 程序**」：eos（状态方程）、kap（不透明度）、atm（大气）、net（核反应网络）等。
- 用户拿到的是 `star/work` 模板：复制一份、改配置文件（inlist）、编译、运行、看输出。

## 二、MESA 基础功能（官方手册要点）

### 1. 安装与配置
- 装 **MESA 源码** + **MESA SDK**（SDK 自带 gfortran、pgplot、ffmpeg 等）。
- 设 3 个环境变量：`MESA_DIR`、`MESASDK_ROOT`、`PATH`（加 `$MESASDK_ROOT/bin`）。
- 在 `$MESA_DIR` 里执行 `./install` 编译全部模块（耗时几分钟到一小时）。

### 2. 建项目 / 编译
- `cp -r $MESA_DIR/star/work 我的项目` —— 每个新项目都从 `work` 复制。
- `cd 我的项目 && ./mk` —— 编译项目自己的 `star` 程序。

### 3. 配置文件 inlist（5 个 namelist 段）
| 段 | 作用 |
|---|---|
| `&star_job` | 用哪些模块、起始模型、输出设置 |
| `&controls` | star 模块的物理与数值控制项（最常用） |
| `&eos` | 状态方程选项 |
| `&kap` | 不透明度选项（如 `use_Type2_opacities`、`Zbase`） |
| `&pgstar` | 绘图选项（26.4 起另有 `&colors` 合成测光） |
- 写法：`参数名 = 值 ! 注释`；`!` 是注释符；未写的参数用默认值。
- `inlist` 通常只做转发：`extra_*_inlist_name(1) = 'inlist_project'`。

### 4. 常用控制项（举例）
- 起始模型：`create_pre_main_sequence_model = .true.` 或 `load_saved_model = .true.` + `load_model_filename`
- 初始条件：`initial_mass`、`initial_z`、`initial_zfracs`（太阳组成预置）
- 何时停止：`max_model_number`、`stop_near_zams`、`xa_central_lower_limit(1)`
- 能量方程：`energy_eqn_option = 'dedt'`（守恒更好）
- 对流：`MLT_option`、`mixing_length_alpha`、`use_Ledoux_criterion`、`do_conv_premix`
- 时间步/网格：`varcontrol_target`、`mesh_delta_coeff`

### 5. 运行与输出
- `./rn` —— 运行；终端打印每一步；运行中可在 `photos/` 存快照。
- 输出目录与文件名**可配置**（默认值）：
  - `log_directory = 'LOGS'`、`star_history_name = 'history.data'`
  - `LOGS/profiles.index`（模型号 ↔ 剖面号）、`LOGS/profile<N>.data`
  - `photo_directory = 'photos'`、`photo_interval`
  - `history_interval`、`profile_interval`、`max_num_profile_models`
- 输出哪些列由 `star/defaults/history_columns.list`、`profile_columns.list` 决定；
  想自定义就复制到项目里改名，并在 inlist 里指定
  `history_columns_file` / `profile_columns_file`。

### 6. 重启 / 保存模型 / 清理
- `./re xNNN` —— 从 `photos/xNNN` 快照继续（不填则用最近快照）。
- 保存可移植模型：`save_model_when_terminate = .true.` + `save_model_filename = 'final.mod'`；
  再用 `load_saved_model = .true.` 从 `.mod` 继续。
- `./clean` —— 清理编译产物（**保留 LOGS/**）。

### 7. 绘图与后处理
- **pgstar**（MESA 自带）：`pgstar_flag = .true.` 实时画 HR 图、内部剖面等。
  - 默认**只画窗口、不落盘**；要出图片必须设 `file_device = 'png'` +
    `HR_file_flag = .true.` + `HR_file_interval`（数值越小帧越多）。
  - 图片默认落在 `png/hr_*.png`（由 `HR_file_dir`、`HR_file_prefix` 决定）。
- **后处理**（手册推荐 Python）：装 `mesa_reader`，用
  `MesaData`（读 history/profile）、`MesaProfileIndex`（读 profiles.index）、
  `MesaLogDir`（串起三者）配合 numpy/matplotlib 画图分析。
- 想输出列表里没有的量：改 `src/run_star_extras.f90`（见手册 Extending MESA）。
- 官方示例项目：`$MESA_DIR/star/test_suite`。

---

## 三、MESA-IDE 有哪些功能

### 1. 安装器（`python3 install.py`，7 步）
1. 检查 Python 版本 → 2. 建 venv → 3. 装依赖（`mesa_reader`、`matplotlib`）
4. **检查 / 安装 / 配置 MESA**：找本机归档（`mesa-*.zip`、`mesasdk-*.tar.gz`）→
   征得同意后解压 SDK 与源码 → 编译 → 生成 `mesa_env.sh` 并写入 `~/.bashrc` 标记块
5. **界面字体**：自带 Noto Sans SC（免 sudo 装到用户字体目录），
   系统没有中文字体时可按同意安装系统字体包
6. 检查参数数据库 `mesa_data.db` → 7. 生成自定位启动脚本
- 纪律：不打网络下载、非交互默认不装、绝不静默 sudo、
  `MESA_IDE_AGREE_MESA_INSTALL=1` / `MESA_IDE_AGREE_FONT_INSTALL=1` 可无人值守放行。

### 2. 启动面板（`./run_mesa.sh` 或 `python3 run_mesa.py`）
- 创建新项目（模板复制 + 补齐列定义 + 建 `png/`，项目名防路径穿越）
- 打开老项目（缺 inlist 会提示）
- 显示 MESA 状态：可用 / 不可用 / 未检测到（含路径）

### 3. 编辑器窗口
| 功能 | 说明 |
|---|---|
| 多标签编辑 | 自动打开 `inlist`、`inlist_project`、`inlist_pgstar`；同名文件不互相顶替 |
| 项目树 | 浏览项目文件、刷新、双击打开 |
| 💾 保存并检查 | 保存后做 namelist 校验，问题进诊断面板并可跳转行 |
| 🔍 仅检查语法 | 只校验不写盘 |
| 🔍 参数名搜索 | 在 4147 个 MESA 参数里做前缀搜索（FTS），双击复制参数名 |
| 诊断面板 | 列出问题（未知参数会提示「是否想写 xxx」）、可关闭 |
| 🚀 编译运行 | 在项目目录开新终端执行 `./mk && ./rn` |
| 🔄 重启 | 执行 `./re`；**会列出 `photos/` 里的可用快照并校验名字** |
| 🧹 Clean | 执行 `./clean` |
| 📊 HR图轨迹 | 读 `LOGS/history.data` 画 HR 图（matplotlib，可缩放/保存） |
| 🌡️ 内部剖面 | 读最后一个 profile 画 Rho–T 剖面（loglog） |
| 🎬 生成视频 | 把 pgstar 的 png 合成 mp4（后台执行、可取消；奇数尺寸自动补齐） |

### 4. 与 MESA 约定的适配（重要）
- **跟随 inlist 配置**：自动解析 `log_directory`、`star_history_name`、
  `photo_directory`、`HR_file_dir`/`HR_file_prefix`，用户改了目录名 IDE 也跟着改。
- **pgstar 未开启出图时**：生成视频前会给出手册要求的设置提示（`file_device`、
  `HR_file_flag`、`HR_file_interval`），前缀不一致也会提示。
- **两套 LOGS 读取器**：优先 `mesa_reader`（成熟、会剔除 restart 备份行），
  没有它时回退到自带纯标准库读取器（可移植）。
- 参数校验只针对参数库真正覆盖的 namelist 段（`controls`/`star_job`/`pgstar`），
  避免把 MESA 官方 inlist 误报成错误。

### 5. 工程与质量
- 分层：`core/`（纯逻辑、仅标准库）+ `ide_ui/`（Tk 界面），有 AST 级架构守卫。
- 测试：标准库 unittest，**当前 587 个用例**（无显示环境自动跳过 Tk 用例）。
- CI：GitHub Actions（Python 3.10/3.12）跑同一套 `./run_tests.sh`。
- 端到端验证：已用真实 MESA 24.08.1 + 真实项目验证
  `./mk`、`./rn`、`./re xNNN`、`./clean`、真实 `LOGS/` 绘图、真实 pgstar png → mp4。

---

## 四、命令 ↔ 按钮 速查

| 手册里的命令 | MESA-IDE 里对应 |
|---|---|
| `cp -r $MESA_DIR/star/work 项目` | 启动面板「创建新项目」 |
| 编辑 `inlist*` | 编辑器标签页 + 参数名搜索 |
| `./mk` | 「编译运行」（会先 `./mk` 再 `./rn`） |
| `./rn` | 「编译运行」 |
| `./re xNNN` | 「重启」（列出快照供选） |
| `./clean` | 「Clean」 |
| 看 `LOGS/history.data` 画 HR 图 | 「HR图轨迹」 |
| 看 `LOGS/profile<N>.data` 画剖面 | 「内部剖面」 |
| pgstar 出图 → 合成视频 | 「生成视频」（需先在 inlist_pgstar 开启出图） |
| 查参数名/含义 | 「参数名搜索」+ 诊断面板 |

---

## 五、限制与注意（简短）

- **MESA 本体仍需安装**：IDE 可以帮你解压/编译/配置，但没有 MESA 就无法模拟。
- **科学判断不能外包**：默认值与官方示例不保证适合你的课题（手册原话）。
- **文档版本**：本目录手册是 26.4.1，本机实测的是 24.08.1；参数差异以你安装版本的
  `$MESA_DIR/star/defaults/*.defaults` 为准。
- **未实测**：Windows/macOS 的字体与 MESA 安装路径（仅单元测试覆盖）；
  CI 尚未在真实 GitHub runner 跑过。
- **未提供**：`star/test_suite` 示例浏览器；`save_model_when_terminate` /
  `load_saved_model` 的专用按钮（目前直接改 inlist 即可）；绘图仍在主线程
  （大数据量时界面会短暂无响应）。

---

## 六、参考

- 官方手册（本文档依据）：<https://docs.mesastar.org/en/26.4.1/using_mesa.html>
- 本仓库离线中英对照：[README.md](README.md)（`en/` 英文原文，`zh/` 中文翻译）
- 项目内部文档：`IDE/开发文档/重构进度.md`（阶段验收）、`交接说明.md`（现状与遗留）

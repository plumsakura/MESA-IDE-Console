# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.1] - 2026-10-15

### 新增

- 视频合成：pgstar 输出的 PNG 序列经 ffmpeg 合成 mp4，后台任务不阻塞界面，
  编码前校验帧序列的完整性与顺序；
- 「编译运行」时询问是否开启 pgstar 实时绘图，按官方 `*_win_flag` 控制项写入
  `inlist_pgstar`；
- 重启（`./re`）支持列出并校验 `photos/` 中的快照名；
- 启动面板显示 MESA 状态；`MESA_DIR` 失效时按常见布局自动扫描真实安装目录；
- 安装器：平台自检、系统依赖按发行版提示、`venv` 自愈、`--offline` 离线安装、
  装完自检；
- 自带 Noto Sans SC / Noto Sans Mono CJK SC 字体，空白系统装完即可显示中文。

### 变更

- 应用整体分层：`core/`（纯逻辑）与 `ide_ui/`（Tk 视图）拆开，入口脚本只做编排；
  分层由 `tests/test_architecture_guards.py` 静态检查；
- 外部命令统一走 argv 列表构造（`core/mesa/commands.py`，协议冻结 + 快照测试），
  不再拼 shell 字符串；
- 后台任务统一由 `core/jobs.py` 管理（`Popen` 生命周期、输出回调、取消）；
- 版本号与日志配置收敛到 `core/config.py` 单一来源。

### 修复

- 编辑器读取失败时不再注册空标签页，避免「保存并检查」把空内容写回；
- 标签页以绝对路径为键，修复同名文件互相覆盖；
- 重复点击「生成视频」会先结束上一个任务，不再遗留孤儿 ffmpeg 进程；
- 项目名校验拒绝 `..` 与路径分隔符，避免写出 `~/MESA_program` 之外。

### 已知问题

- pgstar 实时绘图窗口在 WSL2 下暂不弹出（`./rn` 与数据输出正常）。

## [1.0]

- 首个可用版本：项目创建 / 打开、inlist 编辑与校验、编译运行、HR 图与内部剖面。

---

仓库整理说明：1.1 的源码此前以 `IDE.zip` 形式发布在
[plumsakura/MESA-IDE](https://github.com/plumsakura/MESA-IDE)。本仓库在其基础上
重新组织目录、补齐文档与 CI，历史记录从本仓库首次提交开始。

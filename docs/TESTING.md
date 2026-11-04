# 测试说明

测试用标准库 `unittest`，不依赖 pytest 等第三方测试框架；`mesa_reader` 与
`matplotlib` 只在实际运行应用时需要，部分用例在没有它们时会跳过。

## 运行

```bash
cd IDE

./run_tests.sh                                    # 全部
./run_tests.sh tests.test_core_env                # 单个模块
venv/bin/python -m unittest tests.test_core_env -v

xvfb-run -a ./run_tests.sh                        # 无 X11 的服务器 / 容器
```

`run_tests.sh` 会把 `MPLCONFIGDIR` 指向 `.cache/matplotlib`，避免 matplotlib
因主目录不可写而回退到临时目录（既吵又慢）。

没有图形显示时，Tk 用例通过 `tests/test_ui_components.py::tk_reachable` 探测后
自动跳过，而不是挂起或报错。

## 测试分组

| 分组 | 模块 | 覆盖内容 |
|---|---|---|
| 架构守卫 | `test_architecture_guards.py` | 分层（`core` 不碰 Tk/matplotlib）、无重复方法定义 |
| 协议快照 | `test_protocol_snapshot.py` | 「按钮 → 命令」映射冻结，改动必须显式更新 |
| 核心逻辑 | `test_core_config*.py`、`test_core_env*.py`、`test_core_db.py`、`test_core_project*.py` | 配置单一来源、MESA 环境检测与自动发现、参数库查询、项目模板 |
| 命令与终端 | `test_core_mesa_commands.py`、`test_core_mesa_terminal.py` | argv 构造、转义、终端启动不拼 shell |
| 数据解析 | `test_core_reader_real_data.py`、`test_db_snapshot.py`、`test_linter_snapshot.py` | 真实 `LOGS/` 样本解析、快照比对、inlist 校验 |
| 安装 | `test_core_mesa_install.py`、`test_install_mesa_step.py`、`test_cli_entrypoints.py` | 安装规划、CLI 开关、无 sudo 路径 |
| 视频 | `test_core_video.py`、`test_core_mesa_frames.py` | 帧序列校验、命令构造、失败处理 |
| 并发与任务 | `test_core_jobs*.py` | 输出回调、取消、并发下的进程回收 |
| 界面 | `test_ui_components.py`、`test_ui_fonts.py`、`test_ide_app.py` | 控件装配、字体应用、主窗口动作（无显示时跳过） |
| 集成 | `test_integration_fake_mesa.py` | 用假项目跑通"建项目 → 编译 → 出图"链路 |

## 测试夹具

`tests/fixtures/` 下有两类数据：

- `fake_mesa_project/`：由 `make_fake_project.py` 生成的合成 MESA 项目，含
  `inlist*`、`LOGS/history.data`、`profile*.data`、`profiles.index`，以及假的
  `mk` / `rn` / `re` / `clean` 脚本，可在没有 MESA 的机器上走完整流程；
- `real_mesa/`：从真实 MESA 运行中截取的 `history.data` / `profile2.data`，
  用于验证解析器对真实格式（Fortran `d` 指数、多行列头、`profiles.index`）
  的兼容性。

## 快照测试怎么用

`test_protocol_snapshot.py`、`test_db_snapshot.py`、`test_linter_snapshot.py`、
`test_env_paths_snapshot.py` 都是快照式断言。改动导致快照不一致时：

1. 先确认新行为是**有意**的；
2. 更新快照常量（测试文件内的期望值）；
3. 在提交信息里说明为什么改变，以及旧行为有什么问题。

不要"为了让测试变绿"直接改期望值而不解释——这些测试存在的意义就是让行为变化
可被审阅。

## CI

`.github/workflows/ci.yml` 做两件成本低、信号明确的事：

- `python -m compileall` 检查所有源码可解析；
- 对 `install.sh`、`IDE/*.sh`、`packaging/install-all.sh` 做 `bash -n` 语法检查。

完整测试需要 Tk 与图形环境，建议在本地或 `xvfb-run` 下运行；CI 不做图形用例，
避免因为 runner 环境差异产生假红。

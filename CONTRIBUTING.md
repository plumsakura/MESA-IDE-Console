# 贡献指南

感谢你关注这个项目。它主要面向 Linux / WSL2 上的 MESA 用户，提 PR 前请先读下面几条约定。

## 开发环境

```bash
git clone https://github.com/plumsakura/MESA-IDE-Console.git
cd MESA-IDE-Console
bash install.sh --doctor        # 只体检
bash install.sh                 # 装 venv、依赖、字体
cd IDE && ./run_tests.sh
```

没有图形显示的环境（服务器 / 容器）用：

```bash
xvfb-run -a ./run_tests.sh
```

## 约定

1. **分层不放宽**：`IDE/core/` 只能依赖标准库，不得 `import tkinter` 或
   `matplotlib`；`IDE/ide_ui/` 不得直接 `import sqlite3` / `subprocess`。
   `tests/test_architecture_guards.py` 会拦住违规改动。
2. **命令只用 argv 列表**：禁止 `shell=True`，禁止拼命令字符串。新增外部命令请走
   `core/mesa/commands.py` 的构造器，并同步 `test_protocol_snapshot.py` 的快照。
3. **不静默失败**：错误用 `logging` 记录并给用户可读提示，不要裸 `except: pass`。
4. **提交信息写清动机**：说明"为什么改"比"改了什么"更重要；一次提交只做一件事。
5. **测试先行**：修 bug 时先补一个能复现的用例，再改实现。

## 提交 PR

- 分支从 `main` 切出，PR 里说明改动动机与验证方式（跑了哪些测试）；
- CI 会跑语法检查与 shell 脚本检查，本地请先跑 `./run_tests.sh`；
- 涉及界面的改动请附截图或说明如何在 WSLg 下复现。

## 报告问题

请提供：MESA 版本、系统与发行版、Python 版本、`IDE/logs/mesa_ide.log` 相关片段、
复现步骤。涉及 MESA 编译失败时，附 `$MESA_DIR/build.log`。

"""MESA IDE 主窗口（由原 386 行的 ``IDE.py`` 拆分而来）。

本模块只做"组装 + 动作编排"，具体视图在 ``editor`` / ``diagnostics`` /
``project_tree`` / ``search_bar``，业务逻辑在 ``core``。

相对基线 ``IDE.py`` 的变更（均在阶段 3 提交信息中声明）：

1. **P1/P2**：删除 9 处重复方法定义与占位注释；
2. **P13**：``action_compile_and_run`` 不再 ``subprocess.Popen(["python3","-c",...])``
   绕道执行，直接调用 ``compile_and_run()``（其内部已是 fire-and-forget 启动终端）；
3. **P12**：核心 inlist 文件名改用 ``core.project.CORE_INLIST_FILES``（原先硬编码两处）；
4. **P20**：标签页以绝对路径为键；
5. 读取失败不再注册空标签页（防止"保存并检查"把空内容写回，数据丢失）；
6. 搜索条锚点由 Tk 内部名 ``"!frame"`` 改为显式控件引用；
7. **阶段 6（视频）**：再次点击「生成视频」先收掉上一个未完成任务，
   不再留下孤儿 ffmpeg；并在诊断面板显示匹配到的帧数与帧序告警。
"""

from __future__ import annotations

import logging
import os
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from clean import run_clean
from compile_and_run import compile_and_run
from core.config import load_settings
from core.mesa.outputs import pgstar_setup_hint, resolve_outputs, set_pgstar_live_windows
from core.project import CORE_INLIST_FILES, ensure_png_dir
from core.video import MesaVideoTask
from ide_ui.diagnostics import SUCCESS_COLOR, SUCCESS_MESSAGE, DiagnosticsPanel
from ide_ui.editor import EditorTabs
from ide_ui.project_tree import ProjectTree
from ide_ui.search_bar import ParameterSearchBar
from mesa_linter import MESALinter
from mesa_plotter import plot_hr_diagram, plot_rho_t_profile
from mesa_restart import run_restart

logger = logging.getLogger(__name__)

WINDOW_TITLE = "MESA控制台 - 项目编辑器"
FALLBACK_GEOMETRY = "1024x768"
MESA_START_MESSAGE = "启动 MESA..."
VIDEO_POLL_INTERVAL_MS = 250


class MESA_IDE:
    """项目编辑器窗口（组装各视图 + 动作编排）。"""

    def __init__(self, project_path: str) -> None:
        self.root = tk.Toplevel()
        self.root.title(WINDOW_TITLE)
        try:
            self.root.state("zoomed")
        except tk.TclError:
            self.root.geometry(FALLBACK_GEOMETRY)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.project_path = project_path
        self.settings = load_settings()
        self.linter = MESALinter()

        # 后台任务状态（P9：视频合成不再阻塞 UI 线程）
        self._video_task: MesaVideoTask | None = None
        self._video_poll_id: str | None = None

        # 1. 顶部工具栏
        self.toolbar = self._setup_toolbar()

        # 2. 搜索条（默认隐藏，锚定在工具栏下方）
        self.search_bar = ParameterSearchBar(self.root, database=self.linter.db)
        self.search_bar.set_anchor(self.toolbar)

        # 3. 主区域：左树 / 右编辑器
        self.main_paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, sashwidth=4)
        self.main_paned.pack(fill=tk.BOTH, expand=True)

        self.project_tree = ProjectTree(self.main_paned, on_open=self.open_file)
        # minsize 防止左侧树面板被拖/被布局压缩到 0 宽而"看不见文件树"
        self.main_paned.add(self.project_tree.frame, stretch="never", minsize=160)

        self.editor_paned = tk.PanedWindow(self.main_paned, orient=tk.VERTICAL, sashwidth=4)
        self.main_paned.add(self.editor_paned, stretch="always")

        self.notebook_frame = ttk.Frame(self.editor_paned)
        self.notebook = ttk.Notebook(self.notebook_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self.editor_paned.add(self.notebook_frame, stretch="always")

        self.tabs = EditorTabs(self.notebook)

        # 4. 诊断面板（创建但不加入 PanedWindow，直到需要显示）
        self.diagnostics = DiagnosticsPanel(
            self.editor_paned, on_jump=self.jump_to_diagnostic, on_close=self.hide_diagnostics
        )

        self.refresh_project_tree()
        self.initial_open_core_files()

    # ------------------------------------------------------------------
    # 工具栏
    # ------------------------------------------------------------------
    def _setup_toolbar(self) -> ttk.Frame:
        toolbar = ttk.Frame(self.root, padding="5")
        toolbar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(toolbar, text="保存并检查", command=self.action_save_and_lint).pack(side=tk.LEFT, padx=3)
        ttk.Button(toolbar, text="仅检查语法", command=self.action_just_lint).pack(side=tk.LEFT, padx=3)
        ttk.Button(toolbar, text="编译运行", command=self.action_compile_and_run).pack(side=tk.LEFT, padx=3)
        ttk.Button(toolbar, text="重启", command=self.action_restart).pack(side=tk.LEFT, padx=3)
        ttk.Button(toolbar, text="Clean", command=self.action_clean).pack(side=tk.LEFT, padx=3)

        ttk.Label(toolbar, text=" | ").pack(side=tk.LEFT, padx=5)

        ttk.Button(toolbar, text="HR图轨迹",
                   command=lambda: plot_hr_diagram(self.project_path)).pack(side=tk.LEFT, padx=3)
        ttk.Button(toolbar, text="内部剖面",
                   command=lambda: plot_rho_t_profile(self.project_path)).pack(side=tk.LEFT, padx=3)
        ttk.Button(toolbar, text="生成视频", command=self.action_make_video).pack(side=tk.LEFT, padx=3)

        ttk.Label(toolbar, text=" | ").pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="参数名搜索", command=self.toggle_param_search).pack(side=tk.LEFT, padx=3)

        ttk.Button(toolbar, text="刷新文件目录",
                   command=self.refresh_project_tree).pack(side=tk.RIGHT, padx=10)
        return toolbar

    # ------------------------------------------------------------------
    # 文件树 / 标签页
    # ------------------------------------------------------------------
    def refresh_project_tree(self) -> int:
        return self.project_tree.refresh(self.project_path)

    def open_file(self, file_path: str):
        return self.tabs.open_file(file_path)

    def initial_open_core_files(self) -> list[str]:
        """启动时打开项目根目录下的核心 inlist 文件。"""
        opened: list[str] = []
        for name in CORE_INLIST_FILES:
            path = os.path.join(self.project_path, name)
            if os.path.exists(path):
                self.tabs.open_file(path)
                opened.append(path)
        return opened

    def lint_targets(self):
        """需要语法检查的已打开文档：核心 inlist 文件。"""
        return [
            document
            for document in self.tabs.documents()
            if document.basename in CORE_INLIST_FILES
        ]

    # ------------------------------------------------------------------
    # 诊断面板
    # ------------------------------------------------------------------
    def diagnostics_visible(self) -> bool:
        """诊断面板当前是否已加入下方 PanedWindow。

        **必须比较 Tk 路径名（字符串）**：``panes()`` 返回 Tk window 对象，
        用控件对象做 ``in`` 比较在 Tk 8.6 下不成立（基线实现即有此隐患，
        后果是"关闭 [X]"无法真正隐藏面板、``show`` 会重复 add）。
        """
        return str(self.diagnostics.frame) in {str(pane) for pane in self.editor_paned.panes()}

    def show_diagnostics(self) -> None:
        if not self.diagnostics_visible():
            self.editor_paned.add(self.diagnostics.frame, stretch="never")

    def hide_diagnostics(self) -> None:
        try:
            if self.diagnostics_visible():
                self.editor_paned.forget(self.diagnostics.frame)
                self.root.update_idletasks()
        except tk.TclError:
            pass

    def jump_to_diagnostic(self, filename: str, line_number: int) -> bool:
        return self.tabs.focus_line(filename, line_number)

    # ------------------------------------------------------------------
    # 动作
    # ------------------------------------------------------------------
    def toggle_param_search(self) -> bool:
        return self.search_bar.toggle()

    def action_save_and_lint(self) -> None:
        """保存所有已打开文件并运行语法检查。"""
        self.tabs.save_all()
        self.run_lint_logic()

    def action_just_lint(self) -> None:
        self.run_lint_logic()

    def run_lint_logic(self) -> int:
        """执行语法/语义检查并把结果写入诊断面板，返回问题总数。"""
        self.diagnostics.clear()
        self.show_diagnostics()
        self.tabs.clear_error_marks()

        total = 0
        for document in self.lint_targets():
            issues = self.linter.check_file(document.widget.get("1.0", tk.END))
            if not issues:
                continue
            total += self.diagnostics.add_issues(document.label, issues)
            for issue in issues:
                self.tabs.mark_error_line(document.label, issue["line"])

        if total == 0:
            self.diagnostics.add(SUCCESS_MESSAGE, color=SUCCESS_COLOR)
        return total

    def action_compile_and_run(self) -> None:
        ensure_png_dir(self.project_path)
        self.diagnostics.clear()
        self.show_diagnostics()
        self.diagnostics.add(MESA_START_MESSAGE)
        # 编译运行前询问：是否一边编译运行一边实时画图（官方 pgstar 绘图窗口）
        self.apply_live_plotting(self.ask_live_plotting())
        try:
            compile_and_run(self.project_path)
        except Exception as exc:  # noqa: BLE001 - 与基线一致：向用户报告
            self.diagnostics.add(f"× 启动失败: {exc}")
        self.refresh_project_tree()

    def ask_live_plotting(self) -> bool:
        """编译运行前询问：是否一边编译运行一边实时画图。"""
        return messagebox.askyesno(
            "实时画图",
            "是否一边编译运行一边实时画图？\n\n"
            "选「是」将弹出两个图形窗口（HR 图 + 内部剖面），\n"
            "随模拟计算逐步更新（MESA 官方 pgstar 实时绘图）。\n\n"
            "选「否」则关闭实时绘图窗口，只运行不画图。",
            parent=self.root,
            default=messagebox.YES,
        )

    def apply_live_plotting(self, enable: bool) -> None:
        """按官方 *_win_flag 控制项开关实时绘图窗口，结果写进诊断面板。"""
        ok, detail = set_pgstar_live_windows(self.project_path, enable=enable)
        self.diagnostics.add(("✓ " if ok else "⚠ ") + detail)

    def action_restart(self) -> None:
        run_restart(self.project_path)
        self.refresh_project_tree()

    def action_clean(self) -> None:
        run_clean(self.project_path)
        self.refresh_project_tree()

    def action_make_video(self) -> bool:
        """启动视频合成（**非阻塞**，由 ``poll_video_task`` 轮询推进）。

        返回是否已成功启动任务。
        """
        prefix = simpledialog.askstring(
            "生成视频", "请输入图片前缀 (例如 hr):", initialvalue=self.settings.video_prefix
        )
        if not prefix:
            return False

        # 同一窗口只允许一个 ffmpeg：先把上一个收掉，否则第二个任务会覆盖
        # ``self._video_task``，第一个 ffmpeg 变成没人管的孤儿进程（旧 bug）。
        cancelled_previous = self.cancel_video_task()

        self.diagnostics.clear()
        self.show_diagnostics()
        if cancelled_previous:
            self.diagnostics.add("已取消上一个未完成的视频任务。")
        # 手册要求：pgstar 默认只画窗口、不落盘。先检查项目是否真的会写出图片，
        # 否则 ffmpeg 只会报"找不到输入"，用户无从下手。
        try:
            outputs = resolve_outputs(self.project_path)
            hint = pgstar_setup_hint(outputs)
            if hint:
                self.diagnostics.add(hint)
            if prefix != outputs.pgstar_prefix:
                self.diagnostics.add(
                    f"提示：inlist_pgstar 里的 HR_file_prefix 是 "
                    f"'{outputs.pgstar_prefix}'，与输入的 '{prefix}' 不一致，"
                    "可能匹配不到图片。"
                )
        except Exception:  # noqa: BLE001 - 提示失败不影响主流程
            logger.debug("解析 pgstar 输出约定失败", exc_info=True)
        self.diagnostics.add(f"正在生成视频，前缀: {prefix}...")

        task = MesaVideoTask(self.project_path, prefix, fps=self.settings.video_fps)
        if not task.start():
            self.diagnostics.add("× " + task.message)
            logger.error("视频任务启动失败: %s", task.message)
            return False

        self._video_task = task
        self._report_video_input(task)
        logger.info("已启动视频合成任务: prefix=%s fps=%s", prefix, self.settings.video_fps)
        self._schedule_video_poll()
        return True

    def _report_video_input(self, task: MesaVideoTask) -> None:
        """把匹配到的帧数（与帧序告警）写进诊断面板。"""
        self.diagnostics.add(f"{task.frames.describe()}")
        if task.warning:
            self.diagnostics.add("⚠ " + task.warning)

    def _schedule_video_poll(self) -> None:
        if self._video_poll_id is not None:
            # 撤掉尚未执行的那条轮询，避免出现两条轮询链
            try:
                self.root.after_cancel(self._video_poll_id)
            except tk.TclError:  # pragma: no cover
                pass
        self._video_poll_id = self.root.after(VIDEO_POLL_INTERVAL_MS, self.poll_video_task)

    def poll_video_task(self) -> str | None:
        """推进视频任务状态（Tk ``after`` 定时调用；测试中可直接调用）。

        返回当前状态；无任务时返回 None。
        """
        task = self._video_task
        if task is None:
            return None
        self._video_poll_id = None  # 本次回调已触发，定时器不再是"待执行"
        try:
            if not self.root.winfo_exists():
                return None
        except tk.TclError:  # pragma: no cover - 窗口已销毁
            return None

        state = task.poll()
        if not task.finished:
            self._schedule_video_poll()
            return state

        self.diagnostics.add(("✓ " if task.succeeded else "× ") + task.message)
        if task.succeeded:
            logger.info("视频生成完成: %s", task.message)
            self.refresh_project_tree()
        else:
            logger.error("视频生成未成功: %s", task.message)
        self._video_task = None
        self._video_poll_id = None
        return state

    def cancel_video_task(self) -> bool:
        task = self._video_task
        if task is None:
            return False
        cancelled = task.cancel()
        if self._video_poll_id is not None:
            try:
                self.root.after_cancel(self._video_poll_id)
            except tk.TclError:  # pragma: no cover
                pass
            self._video_poll_id = None
        self._video_task = None
        if not cancelled and task.finished:
            # 进程其实已经结束（只是还没被轮询到）：保住真实结局，别丢消息
            self.diagnostics.add(("✓ " if task.succeeded else "× ") + task.message)
        return cancelled

    def on_close(self) -> None:
        """关闭窗口：取消未完成的视频任务，避免留下孤儿 ffmpeg 进程。"""
        if self._video_poll_id is not None:
            try:
                self.root.after_cancel(self._video_poll_id)
            except tk.TclError:  # pragma: no cover
                pass
            self._video_poll_id = None
        if self._video_task is not None:
            self._video_task.cancel()
            self._video_task = None
        try:
            self.root.destroy()
        except tk.TclError:  # pragma: no cover - 已销毁
            pass

    def run(self) -> None:
        self.root.mainloop()


def start_ide(project_path: str) -> MESA_IDE:
    """打开编辑器窗口并进入主循环（与基线签名一致）。"""
    # 自带中文字体（界面 + 编辑器等宽）就位后再建窗：Tk 的 fontconfig 枚举发生在
    # 首次建窗时，所以这里必须先 ensure（幂等，失败不阻断）
    try:
        from core.fonts import ensure_bundled_fonts

        results = ensure_bundled_fonts()
        for result in results:
            if result.copied:
                logger.info("已安装自带中文字体: %s", result.target)
    except Exception:  # noqa: BLE001 - 字体不是启动的必要条件
        logger.warning("自带字体安装失败，界面中文可能显示为方框", exc_info=True)

    app = MESA_IDE(project_path)
    app.run()
    return app

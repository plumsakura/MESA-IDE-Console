import logging
import os
import tkinter as tk
from tkinter import ttk, messagebox
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

from core.fonts import bundled_font_source
from core.mesa.outputs import resolve_outputs
from core.mesa.reader import MesaLogDir, read_history

# 读取器选择：优先 mesa_reader（成熟，且会剔除 restart 产生的备份行），
# 环境里没有它时回退到自带纯标准库读取器 core.mesa.reader（离线/移植可用）。
try:
    import mesa_reader as mr
except ImportError:  # pragma: no cover - 取决于环境
    mr = None


def load_history(history_path: str):
    """读取 ``LOGS/history.data``（优先 mesa_reader）。"""
    if mr is not None:
        return mr.MesaData(history_path)
    return read_history(os.path.dirname(history_path))


def load_profile(logs_dir: str):
    """读取 ``LOGS`` 里最后一个剖面（优先 mesa_reader）。"""
    if mr is not None:
        return mr.MesaLogDir(logs_dir).profile_data()
    return MesaLogDir(logs_dir).profile_data()

logger = logging.getLogger(__name__)

# ================= 配置区：仅针对图表内容的清晰度优化 =================
# 注意：我们不在 main.py 开启全局 DPI 感知，而是手动提升 Matplotlib 的渲染密度
plt.rcParams['axes.unicode_minus'] = False  # 修复负号显示问题

# 自带中文字体（OFL）：即使系统一个中文字体都没有，图中的中文标题/坐标轴
# 也能正常显示（Tk 侧由 core.fonts.ensure_bundled_font 经 fontconfig 提供）
try:
    _bundled = bundled_font_source()
    if _bundled.is_file():
        from matplotlib import font_manager as _font_manager

        _font_manager.fontManager.addfont(str(_bundled))
        logger.info("已注册自带绘图字体: %s", _bundled.name)
except Exception:  # noqa: BLE001 - 字体注册失败不影响主流程
    logger.warning("注册自带绘图字体失败", exc_info=True)

# 字体回退链：先原实现偏好的 Arial（有它的机器视觉不变），再常见中文字体族。
# 缺了后半个链时，图中的中文标题/坐标轴会显示成方框。
plt.rcParams['font.sans-serif'] = [
    'Arial',
    'Helvetica',
    'Microsoft YaHei',
    'Noto Sans SC',
    'Noto Sans CJK SC',
    'Noto Sans CJK JP',
    'Source Han Sans SC',
    'WenQuanYi Micro Hei',
    'WenQuanYi Zen Hei',
    'Droid Sans Fallback',
    'SimHei',
    'DejaVu Sans',
]
plt.style.use('bmh')  # 使用一种清晰的科学绘图风格


class MesaPlotViewer:
    """
    独立的高清绘图查看器窗口。
    即使 IDE 界面模糊，这里的图表内部依然会保持高像素。
    """

    def __init__(self, title, fig):
        self.window = tk.Toplevel()
        self.window.title(title)
        self.window.geometry("850x650")

        # 将 Matplotlib 的 Figure 嵌入 Tkinter
        self.canvas = FigureCanvasTkAgg(fig, master=self.window)
        self.canvas.draw()

        # 添加标准工具栏（支持放大、缩小、高清保存图片）
        self.toolbar = NavigationToolbar2Tk(self.canvas, self.window)
        self.toolbar.update()

        # 布局：让画布填充整个窗口
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # 窗口关闭时关闭对应的 figure 释放内存
        self.window.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_close(self):
        plt.close('all')
        self.window.destroy()


# ================= 核心绘图功能：手动提升渲染 DPI =================

def plot_hr_diagram(project_path):
    """提取 history.data 绘制高清 HR 图（路径按 MESA 手册的 log_directory 解析）"""
    path = resolve_outputs(project_path).history_path
    if not os.path.exists(path):
        messagebox.showwarning("找不到数据", "未找到 history.data，请运行模拟后再试。")
        return

    try:
        h = load_history(path)
        logger.info("已读取 MESA history: %s", path)

        # --- 核心修改：设置 dpi=200 使图表内部保持极高清晰度 ---
        # figsize 稍微减小以防由于高 DPI 导致窗口初始过大
        fig = plt.figure(figsize=(6.5, 5), dpi=200, tight_layout=True)
        ax = fig.add_subplot(111)

        # 绘图：linewidth 设为 1.2 在 200 DPI 下非常锐利
        ax.plot(h.log_Teff, h.log_L, color='#1e6fb3', linewidth=1.2)

        # HR图标准配置
        ax.invert_xaxis()
        ax.set_xlabel(r'$\log_{10}(T_{eff}/K)$', fontsize=10)
        ax.set_ylabel(r'$\log_{10}(L/L_\odot)$', fontsize=10)
        ax.set_title(f"Hertzsprung-Russell Diagram", fontsize=12, fontweight='bold')

        ax.grid(True, linestyle=':', alpha=0.6)

        # 弹出查看器
        MesaPlotViewer("MESA 数据可视化 - HR图 (200 DPI)", fig)

    except Exception as e:
        logger.exception("解析 history.data 失败: %s", path)
        messagebox.showerror("绘图出错", f"解析数据失败: {e}")


def plot_rho_t_profile(project_path):
    """绘制内部密度-温度结构图 (高清版)"""
    logs_dir = resolve_outputs(project_path).log_dir
    try:
        p = load_profile(logs_dir)
        logger.info("已读取 MESA profile: %s (model %s)", logs_dir, p.model_number)

        # --- 核心修改：设置 dpi=200 ---
        fig = plt.figure(figsize=(6.5, 5), dpi=200, tight_layout=True)
        ax = fig.add_subplot(111)

        # 使用对数坐标绘制密度与温度关系
        ax.loglog(p.Rho, p.T, color='#d62728', linewidth=1.2)

        ax.set_xlabel(r'Density $\rho$ (g/cm$^3$)', fontsize=10)
        ax.set_ylabel(r'Temperature $T$ (K)', fontsize=10)
        ax.set_title(f"Internal structure (Model: {p.model_number})", fontsize=12, fontweight='bold')

        ax.grid(True, which="both", linestyle='--', alpha=0.4)

        # 弹出查看器
        MesaPlotViewer("MESA 数据可视化 - 内部结构 (200 DPI)", fig)

    except Exception as e:
        logger.exception("加载 Profile 数据失败: %s", logs_dir)
        messagebox.showerror("绘图出错", f"无法加载Profile数据: {e}")


if __name__ == "__main__":
    # 模块化设计，通常不直接运行此文件
    pass

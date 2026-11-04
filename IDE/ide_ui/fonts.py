"""界面字体解析（Tk 视图层）。

修复"中文显示成方框/乱码"的根因：原实现把界面字体写死为 `Helvetica`/`Arial`
（`main.py`）与 `YaHei`/`Consolas`（`ide_ui/*`）。在**没有这些字体也没有任何
中文字体**的 Linux 上，Tk 会退回到 `DejaVu Sans` —— 它没有 CJK 字形，于是所有
中文都变成方框。

本模块把"偏好 → 实际可用字体族"的解析独立出来，并遵循两条纪律：

1. 偏好表第一位是**自带字体**（Noto Sans SC / Noto Sans Mono CJK SC，安装器
   会装进用户字体目录），保证任何平台（含空白 WSL2）都能选中真能画中文的族；
2. Tk 的 ``actual('family')`` 会对**不存在的字体**回落到默认族，不能用它判断
   "是否存在"。因此判定分两步：先看族名是否在 ``tkfont.families()`` 里，再用
   "一个肯定不存在的名字" 取得默认回落族，要求候选族的 ``actual`` 与之不同。

字体偏好（纯数据）定义在 :mod:`core.config`，便于将来移植到其他语言/界面框架。
"""

from __future__ import annotations

import logging

from core.config import (
    DEFAULT_MONO_FONT_PREFERENCES,
    DEFAULT_UI_FONT_PREFERENCES,
)

logger = logging.getLogger(__name__)

#: 用一个几乎不可能存在的族名取得 Tk 的"默认回落族"
_PROBE_NAME = "__mesa_ide_probe_missing_font__"

#: 解析结果缓存（同一进程内字体集合不会变）
_resolved_ui_family: str | None = None
_resolved_mono_family: str | None = None


def _font_module():
    """取 ``tkinter.font``（局部导入，便于测试替换且不影响导入本模块）。"""
    from tkinter import font as font_module

    return font_module


def list_font_families(font_module) -> list[str]:
    """返回 Tk 可见的字体族名（保留系统原始大小写）。"""
    return [str(name) for name in font_module.families()]


def _fallback_families(font_module) -> set[str]:
    """Tk 对不存在字体名回落到哪个族（通常 1 个）。"""
    probe = font_module.Font(family=_PROBE_NAME, size=12)
    return {str(probe.actual("family")).lower()}


def resolve_family(font_module, preferences) -> str:
    """按偏好表返回第一个**真实存在**的字体族；都没有则返回 Tk 默认族。

    判定分两步，避免自欺：族名必须在 ``families()`` 里，且**不能**是 Tk 对不存在
    字体名的回落族（否则"随便给个名字也能 actual 出来"会被误判为存在）。
    """
    available = list_font_families(font_module)
    by_lower = {name.lower(): name for name in available}
    # 比较统一转小写：不同平台/后端回报的大小写并不一致
    fallbacks_lower = {name.lower() for name in _fallback_families(font_module)}
    for name in preferences:
        candidate = str(name).strip()
        if not candidate:
            continue
        lowered = candidate.lower()
        if lowered in by_lower and lowered not in fallbacks_lower:
            # 用系统里的**原始大小写**，避免把族名写歪
            return by_lower[lowered]

    # 没有命中：退回"系统上真实存在的无衬线族"，并给出明确警告
    chosen = next(
        (name for name in available if name.lower() not in fallbacks_lower),
        available[0] if available else "TkDefaultFont",
    )
    logger.warning(
        "偏好字体都不可用（%s），改用 %s；界面中文可能显示为方框 —— "
        "请安装中文字体（如 fonts-noto-cjk），或用 MESA_IDE_UI_FONT 指定可用字体",
        list(preferences),
        chosen,
    )
    return chosen


def ui_font_family(*, font_module=None, preferences=None) -> str:
    """界面正文字体族（只缓存"真实 Tk 模块 + 默认偏好"的结果）。"""
    global _resolved_ui_family
    cached = font_module is None and preferences is None
    if cached and _resolved_ui_family is not None:
        return _resolved_ui_family
    module = _font_module() if font_module is None else font_module
    family = resolve_family(
        module, DEFAULT_UI_FONT_PREFERENCES if preferences is None else preferences
    )
    if cached:
        _resolved_ui_family = family
    return family


def mono_font_family(*, font_module=None, preferences=None) -> str:
    """等宽字体族（编辑器/诊断列表/搜索结果）。"""
    global _resolved_mono_family
    cached = font_module is None and preferences is None
    if cached and _resolved_mono_family is not None:
        return _resolved_mono_family
    module = _font_module() if font_module is None else font_module
    family = resolve_family(
        module, DEFAULT_MONO_FONT_PREFERENCES if preferences is None else preferences
    )
    if cached:
        _resolved_mono_family = family
    return family


def reset_cache() -> None:
    """清空解析缓存（供测试与"运行期换字体"使用）。"""
    global _resolved_ui_family, _resolved_mono_family
    _resolved_ui_family = None
    _resolved_mono_family = None


def apply_to_root(root, *, preferences=None, mono_preferences=None) -> str:
    """把解析出的字体写到 Tk 命名字体上，返回正文族名。

    ``TkDefaultFont``/``TkTextFont``/``TkMenuFont``/``TkHeadingFont`` 覆盖大部分
    控件；``TkFixedFont`` 用于等宽场景。这样即使某个控件没有显式传 ``font=``，
    也能拿到有中文字形的族。
    """
    font_module = _font_module()
    family = ui_font_family(font_module=font_module, preferences=preferences)
    mono = mono_font_family(font_module=font_module, preferences=mono_preferences)

    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        try:
            font_module.nametofont(name).configure(family=family)
        except Exception:  # noqa: BLE001 - 缺少该命名字体时跳过
            logger.debug("命名字体 %s 不存在，跳过", name)
    try:
        font_module.nametofont("TkFixedFont").configure(family=mono)
    except Exception:  # noqa: BLE001
        logger.debug("命名字体 TkFixedFont 不存在，跳过")

    try:  # ttk 主题对按钮/标签另有一套字体，需一并覆盖
        import tkinter.ttk as ttk

        style = ttk.Style(root)
        for style_name in ("TButton", "TLabel", "TCheckbutton", "TRadiobutton",
                           "TNotebook.Tab", "TLabelframe.Label", "TEntry"):
            style.configure(style_name, font=(family, 10))
    except Exception:  # noqa: BLE001 - 无 ttk 主题时不影响主流程
        logger.debug("ttk 样式字体设置跳过", exc_info=True)
    return family

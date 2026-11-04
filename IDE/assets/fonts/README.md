# 自带字体资产：Noto Sans SC + Noto Sans Mono CJK SC（完整版）

本目录是 MESA IDE **自带的中文字体**，保证用户在没有安装任何中文字体的
系统上（空白 WSL2 / 最小化安装的 Linux / 容器 / 精简 Windows）也能正常
显示中文界面与编辑器内容。

## 内容

| 文件 | 说明 |
|---|---|
| `NotoSansSC-Regular.otf` | Noto Sans CJK SC Regular **完整版**（约 44,810 字形，16.4 MB） |
| `NotoSansMonoCJKsc-Regular.otf` | Noto Sans Mono CJK SC Regular **完整版**（等宽中文，约 44,810 字形，16.4 MB） |
| `OFL.txt` | SIL Open Font License 1.1（允许随软件免费分发） |

## 为什么用完整版而不是子集

早期版本随包携带的是约 5,200 字形的**子集**，导致两类显示问题：

1. 生僻汉字（如"瀚""澧"）与部分符号（✅ ❌ ↩ ✗ 等）显示为方框；
2. 编辑器（等宽字体）在无系统字体的机器上回退到不含 CJK 的字体，
   中文注释全部变方框。

完整版覆盖全部常用与生僻 CJK 字形，UI 字体与编辑器等宽字体各随一份，
任何用户项目里的中文注释都能正常显示。代价是发行包增大约 30 MB，
换来"空白 WSL2 装完即显示正常"。

## 来源与许可

- 原字体：Noto Sans CJK — `NotoSansCJK-Regular.ttc` 中的 SC 面
  （face 2 = Noto Sans CJK SC、face 7 = Noto Sans Mono CJK SC），
  来自 Ubuntu/Debian 软件包 `fonts-noto-cjk`，
  上游 <https://github.com/notofonts/noto-cjk>（SIL OFL 1.1）。
- 处理：用 fonttools 从 TTC 中提取 SC 面，并把族名规范为
  `Noto Sans SC`（与原子集版本保持一致，避免改代码）。

## 安装方式（运行时，无需管理员权限）

`core/fonts.py` 的 `ensure_bundled_fonts()` 会把本目录的字体复制到
**用户字体目录**（Linux: `$XDG_DATA_HOME/fonts` 或 `~/.local/share/fonts`；
macOS: `~/Library/Fonts`；Windows: `%LOCALAPPDATA%\Microsoft\Windows\Fonts`
并写入 HKCU 注册表），Linux 上再刷新 fontconfig 缓存（`fc-cache -f`）。
之后 Tk（fontconfig）与 matplotlib 都能识别字体族名
**`Noto Sans SC`** 与 **`Noto Sans Mono CJK SC`**。

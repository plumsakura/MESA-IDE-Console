# MESA 使用文档（26.4.1 英文原文 + 中文翻译）

本目录保存 **MESA 官方文档 "Using MESA"** 章节的**英文原文**与**简体中文翻译**，
供 MESA IDE 的开发与使用者离线查阅。

- 来源站点：<https://docs.mesastar.org/en/26.4.1/using_mesa.html>
- 文档版本：**MESA 26.4.1**
- 抓取时间：**2026-10-15 07:51（UTC+8）**
- 入口页：`using_mesa`（该页是索引页，正文只有 8 个链接，真正的章节在下列子页面）

> 注意：本机安装并验证过的是 **MESA 24.08.1**（见《重构进度》5.9），
> 而本目录抓取的是 **26.4.1** 的文档。两者在参数名与行为上可能有差异，
> 实际运行请以你安装的 MESA 版本自带的
> `$MESA_DIR/star/defaults/*.defaults` 与 `$MESA_DIR/docs/` 为准。

## 先看这个

- **[MESA与MESA-IDE功能速查.md](MESA与MESA-IDE功能速查.md)** —— 一页要点版：
  MESA 有哪些基础功能、MESA-IDE 有哪些功能、命令↔按钮对照表、限制与注意。

## 文件对照

| 页面（章节） | 英文原文（HTML，原样保存） | 英文可读版（Markdown） | 中文翻译 |
|---|---|---|---|
| Using MESA（入口索引） | [using_mesa.html](en/using_mesa.html) | [using_mesa.md](en/using_mesa.md) | [using_mesa.md](zh/using_mesa.md) |
| Running MESA（运行、重启、保存/载入模型） | [running.html](en/running.html) | [running.md](en/running.md) | [running.md](zh/running.md) |
| MESA output（输出文件与列控制） | [output.html](en/output.html) | [output.md](en/output.md) | [output.md](zh/output.md) |
| Using PGSTAR（绘图与图片输出） | [using_pgstar.html](en/using_pgstar.html) | [using_pgstar.md](en/using_pgstar.md) | [using_pgstar.md](zh/using_pgstar.md) |
| Building inlists（inlist 写法） | [building_inlists.html](en/building_inlists.html) | [building_inlists.md](en/building_inlists.md) | [building_inlists.md](zh/building_inlists.md) |
| Extending MESA（改 `run_star_extras.f90`） | [extending_mesa.html](en/extending_mesa.html) | [extending_mesa.md](en/extending_mesa.md) | [extending_mesa.md](zh/extending_mesa.md) |
| Troubleshooting（排错） | [troubleshooting.html](en/troubleshooting.html) | [troubleshooting.md](en/troubleshooting.md) | [troubleshooting.md](zh/troubleshooting.md) |
| Best practices（最佳实践） | [best_practices.html](en/best_practices.html) | [best_practices.md](en/best_practices.md) | [best_practices.md](zh/best_practices.md) |
| Just a Module（当作库使用） | [just_a_module.html](en/just_a_module.html) | [just_a_module.md](en/just_a_module.md) | [just_a_module.md](zh/just_a_module.md) |

## 目录结构

```
mesa使用文档/
├── README.md                 # 本文件：来源、对照表、约定与校验方法
├── en/                       # 英文：*.html 为官网页面原样保存；*.md 为抽取出的可读正文
├── zh/                       # 中文：与 en/*.md 一一对应的译文
└── tools/
    ├── html_to_md.py         # Sphinx 页面 → Markdown（仅标准库，无需 pandoc/bs4）
    └── verify_translation.py # 校验译文与原文的代码块/标题/链接/列表结构一致
```

## 翻译约定（重要）

1. **代码、命令、参数名、路径、URL 一律不翻译**，保持与原文逐字一致，例如
   `./mk`、`./rn`、`./re x208`、`./clean`、`MESA_DIR`、`LOGS`、`photos`、
   `history.data`、`profiles.index`、`inlist_project`、`pgstar_flag`、
   `HR_file_flag`、`.true.` 等；
2. 章节标题、正文、图注、提示框标题译为中文；结构（标题层级、列表、代码围栏、
   链接）与原文一一对应；
3. 术语第一次出现时可采用「中文（English）」形式，便于与官方文档对照；
4. **译文仅供参考**：若译文与英文原文冲突，**以英文原文为准**；涉及运行结果的
   细节请回到 `en/` 或官网核对。

## 重新生成与校验

```bash
cd IDE/mesa使用文档

# 1) 重新抓取英文页面（需联网）
base=https://docs.mesastar.org/en/26.4.1
for p in using_mesa using_mesa/running using_mesa/output using_mesa/using_pgstar \
         using_mesa/building_inlists using_mesa/extending_mesa \
         using_mesa/troubleshooting using_mesa/best_practices using_mesa/just_a_module; do
    curl -fsSL -o "en/$(basename $p).html" "$base/$p.html"
done

# 2) HTML → Markdown（英文可读版）
python3 tools/html_to_md.py en/*.html

# 3) 校验译文与原文结构一致（代码块/标题/链接/列表）
python3 tools/verify_translation.py
```

`verify_translation.py` 的硬检查：
- 每个 `en/*.md` 都有同名 `zh/*.md`；
- **代码围栏数量相同**（代码块必须原样保留）；
- **标题数量与层级序列相同**；
- **链接数量相同**（链接 target 不得丢失）；
- 列表项数量偏差 ≤ 5%；
- 另外会列出"疑似未翻译的英文整行"供人工复核（`--strict` 时视为失败）。

## 当前校验结果（2026-10-15）

```
$ python3 tools/verify_translation.py
✅ best_practices.md          en  513 行 → zh  517 行
✅ building_inlists.md        en  246 行 → zh  287 行
✅ extending_mesa.md          en  565 行 → zh  567 行
✅ just_a_module.md           en  213 行 → zh  216 行
✅ output.md                  en  252 行 → zh  249 行
✅ running.md                 en  528 行 → zh  531 行
✅ troubleshooting.md         en   32 行 → zh   34 行
✅ using_mesa.md              en   24 行 → zh   27 行
✅ using_pgstar.md            en  581 行 → zh  584 行

全部检查通过：代码块、标题、链接与列表结构与英文原文一致
```

另外逐块比对了代码内容：**9 篇共 121 个代码块，与英文原文逐字节一致**
（命令、namelist 片段、代码内英文注释均未被改动）；"疑似未翻译的英文整行"为 0 处。

英文 HTML 也已与官网二次下载做 `sha256` 比对，确认**逐字节一致**（抽样：`running.html`、`using_pgstar.html`）。

## 与本项目的关系

MESA IDE 的输出解析与操作流程就是按这套文档实现的，例如：

- `log_directory`（默认 `LOGS`）、`star_history_name`（默认 `history.data`）、
  `photo_directory`（默认 `photos`）、pgstar 的 `HR_file_dir`（默认 `png`）/
  `HR_file_prefix`（默认 `hr_`）等**都可以被用户改**，IDE 会从项目的 inlist 链里
  解析实际路径（实现见 `IDE/core/mesa/outputs.py`，验收记录见
  `IDE/开发文档/重构进度.md` 5.11）；
- `./re xNNN` 的快照名来自 `photos/`，IDE 会在重启对话框里列出可用快照并校验；
- pgstar 默认只画窗口、**不落盘**（`HR_file_flag` 默认 `.false.`），
  要出图必须显式打开并设置 `HR_file_interval`——IDE 在生成视频前会给出这段提示。

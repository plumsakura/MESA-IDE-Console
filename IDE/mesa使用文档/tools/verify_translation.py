#!/usr/bin/env python3
"""校验 ``zh/*.md`` 与 ``en/*.md`` 的结构一致性（仅标准库）。

用途：翻译是人工/模型产出，容易漏段落或改结构；本脚本给出**可复现的硬检查**：

1. 每个 ``en/<name>.md`` 都有对应 ``zh/<name>.md``；
2. **代码围栏数量相同**（```` ``` ```` 行数）——代码块必须一字不动地保留；
3. **标题数量与层级序列相同**（``#`` 的个数与顺序）；
4. **链接数量相同**（``](`` 出现次数）——链接 target 不得丢失；
5. 列表项数量偏差不超过 5%；
6. 抽查"疑似未翻译"：正文（跳过代码块/注释/链接/纯符号行）里长度 ≥ 40 字符且
   仅含 ASCII 字母与空格的整行，若超过阈值则告警（不视为失败，供人工复核）。

用法::

    python3 tools/verify_translation.py          # 全量检查，失败返回 1
    python3 tools/verify_translation.py --strict # 把"疑似未翻译"也当失败
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
EN_DIR = ROOT / "en"
ZH_DIR = ROOT / "zh"

ASCII_PROSE = re.compile(r"^[A-Za-z0-9 ,.;:()'\"!?/\-–—…&%$#*+<>=\[\]{}|~`^]{40,}$")
SKIP_PREFIXES = ("<!--", ">", "|", "```", "    ")


def _strip_fences(text: str) -> tuple[list[str], int]:
    """返回（代码块之外的行, 代码围栏数量）。"""
    outside: list[str] = []
    fences = 0
    in_code = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fences += 1
            in_code = not in_code
            continue
        if not in_code:
            outside.append(line)
    return outside, fences


def _headings(lines: list[str]) -> list[int]:
    return [len(match.group(1)) for line in lines if (match := re.match(r"^(#{1,6}) ", line))]


def _links(lines: list[str]) -> list[str]:
    return re.findall(r"\]\(([^)]+)\)", "\n".join(lines))


def _list_items(lines: list[str]) -> int:
    return sum(1 for line in lines if re.match(r"^\s*(?:[-*+]|\d+\.)\s+\S", line))


def _suspicious_untranslated(lines: list[str]) -> list[str]:
    out = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(SKIP_PREFIXES):
            continue
        if "](http" in stripped or stripped.startswith("!["):
            continue
        if ASCII_PROSE.match(stripped):
            out.append(stripped)
    return out


def check_pair(english: pathlib.Path, chinese: pathlib.Path, *, strict: bool) -> list[str]:
    problems: list[str] = []
    if not chinese.is_file():
        return [f"缺少译文: {chinese.name}"]

    en_text = english.read_text(encoding="utf-8")
    zh_text = chinese.read_text(encoding="utf-8")
    en_lines, en_fences = _strip_fences(en_text)
    zh_lines, zh_fences = _strip_fences(zh_text)

    if not zh_text.strip():
        problems.append("译文是空文件")
    if en_fences != zh_fences:
        problems.append(f"代码围栏数量不一致: en={en_fences} zh={zh_fences}")
    en_head, zh_head = _headings(en_lines), _headings(zh_lines)
    if en_head != zh_head:
        problems.append(f"标题结构不一致: en={en_head} zh={zh_head}")
    if len(_links(en_lines)) != len(_links(zh_lines)):
        problems.append(
            f"链接数量不一致: en={len(_links(en_lines))} zh={len(_links(zh_lines))}"
        )
    en_items, zh_items = _list_items(en_lines), _list_items(zh_lines)
    if en_items and abs(en_items - zh_items) > max(2, en_items * 0.05):
        problems.append(f"列表项数量偏差过大: en={en_items} zh={zh_items}")

    suspicious = _suspicious_untranslated(zh_lines)
    if suspicious:
        message = f"疑似未翻译的英文整行 {len(suspicious)} 处（例: {suspicious[0][:60]}…）"
        if strict:
            problems.append(message)
        else:
            print(f"  ⚠ {english.name}: {message}")
    return problems


def main(argv: list[str]) -> int:
    strict = "--strict" in argv
    if not EN_DIR.is_dir() or not ZH_DIR.is_dir():
        print(f"目录不存在: {EN_DIR} / {ZH_DIR}")
        return 2

    english_files = sorted(EN_DIR.glob("*.md"))
    if not english_files:
        print("en/ 下没有 .md 文件")
        return 2

    failures: list[str] = []
    print(f"检查 {len(english_files)} 个文件对（en/ ↔ zh/）\n")
    for english in english_files:
        chinese = ZH_DIR / english.name
        problems = check_pair(english, chinese, strict=strict)
        en_count = len(english.read_text(encoding="utf-8").splitlines())
        zh_count = len(chinese.read_text(encoding="utf-8").splitlines()) if chinese.is_file() else 0
        status = "✅" if not problems else "❌"
        print(f"{status} {english.name:26s} en {en_count:4d} 行 → zh {zh_count:4d} 行")
        for problem in problems:
            print(f"     - {problem}")
            failures.append(f"{english.name}: {problem}")

    print()
    if failures:
        print(f"失败 {len(failures)} 项（译文与英文原文结构必须一致）")
        return 1
    print("全部检查通过：代码块、标题、链接与列表结构与英文原文一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

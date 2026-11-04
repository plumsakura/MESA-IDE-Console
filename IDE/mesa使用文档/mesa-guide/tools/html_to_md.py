#!/usr/bin/env python3
"""把 Sphinx 生成的 MESA 文档页转成 Markdown（仅标准库，无需 pandoc/bs4）。

用途：``IDE/mesa使用文档/en/*.html``（官网 26.4.1 页面原样保存）→ ``en/*.md``，
作为翻译底稿与"英文原文"的可读版本。

只处理 Sphinx/RTD 主题里实际出现的结构：``<article>`` 正文、标题、段落、
列表、代码块（``div.highlight* > pre``）、表格、admonition、行内 ``code``、
链接与强调。转换是**尽力而为**：目标可读、可翻译，不追求像素级还原。

用法::

    python3 tools/html_to_md.py en/*.html        # 就地生成同名 .md
"""

from __future__ import annotations

import html
import pathlib
import re
import sys

BLOCK_TAGS = "p|div|section|article|li|ul|ol|table|thead|tbody|tr|td|th|pre|blockquote|dl|dt|dd|h1|h2|h3|h4|h5|h6|br|hr|figure|figcaption|span"


def _article(html_text: str) -> str:
    """取 <article> 正文；没有就退回 <body>。"""
    match = re.search(r"<article[^>]*>(.*?)</article>", html_text, re.S)
    if match:
        return match.group(1)
    match = re.search(r"<body[^>]*>(.*?)</body>", html_text, re.S)
    return match.group(1) if match else html_text


def _drop_noise(fragment: str) -> str:
    """去掉导航/页脚/脚本/锚点链接等非正文元素。"""
    fragment = re.sub(r"<(script|style|nav|footer|header)\b.*?</\1>", "", fragment, flags=re.S)
    # 标题上的 ¶ 永久链接
    fragment = re.sub(r'<a class="headerlink".*?</a>', "", fragment, flags=re.S)
    fragment = re.sub(r'<a class="reference internal nav-link".*?</a>', "", fragment, flags=re.S)
    return fragment


def _code_blocks(fragment: str) -> str:
    """``div.highlight*`` / ``pre`` → 围栏代码块；``<span class="pre">`` 去标签。"""

    def repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        inner = re.sub(r"<[^>]+>", "", inner)
        code = html.unescape(inner).strip("\n")
        return f"\n\n```\n{code}\n```\n\n"

    fragment = re.sub(
        r'<div class="highlight[^"]*"[^>]*>\s*<pre[^>]*>(.*?)</pre>\s*</div>',
        repl,
        fragment,
        flags=re.S,
    )
    fragment = re.sub(r"<pre[^>]*>(.*?)</pre>", repl, fragment, flags=re.S)
    return fragment


def _tables(fragment: str) -> str:
    """``<table>`` → 管道表格（首行为表头）。"""

    def repl(match: re.Match[str]) -> str:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", match.group(1), re.S)
        rendered: list[list[str]] = []
        for row in rows:
            cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S)
            rendered.append([_inline(cell).strip().replace("|", "\\|") for cell in cells])
        if not rendered:
            return ""
        width = max(len(row) for row in rendered)
        lines = []
        for index, row in enumerate(rendered):
            padded = row + [""] * (width - len(row))
            lines.append("| " + " | ".join(padded) + " |")
            if index == 0:
                lines.append("|" + "---|" * width)
        return "\n\n" + "\n".join(lines) + "\n\n"

    return re.sub(r"<table[^>]*>(.*?)</table>", repl, fragment, flags=re.S)


def _admonitions(fragment: str) -> str:
    """``div.admonition`` → 引用块（保留标题）。"""

    def repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        title = re.search(r'<p class="admonition-title">(.*?)</p>', inner, re.S)
        body = re.sub(r'<p class="admonition-title">.*?</p>', "", inner, flags=re.S)
        text = _inline(body).strip()
        text = re.sub(r"\n{2,}", "\n", text)
        head = f"**{_inline(title.group(1)).strip()}**\n" if title else ""
        quoted = "\n".join(f"> {line}" if line.strip() else ">" for line in (head + text).splitlines())
        return f"\n\n{quoted}\n\n"

    return re.sub(r'<div class="admonition[^"]*"[^>]*>(.*?)</div>\s*</div>', repl, fragment, flags=re.S)


def _headings(fragment: str) -> str:
    def repl(match: re.Match[str]) -> str:
        level = int(match.group(1))
        text = _inline(match.group(2)).strip()
        if not text:
            return ""
        return f"\n\n{'#' * level} {text}\n\n"

    return re.sub(r"<h([1-6])[^>]*>(.*?)</h\1>", repl, fragment, flags=re.S)


def _lists(fragment: str) -> str:
    fragment = re.sub(r"<li[^>]*>", "\n- ", fragment)
    fragment = re.sub(r"</li>", "", fragment)
    fragment = re.sub(r"</?(ul|ol)[^>]*>", "\n", fragment)
    return fragment


def _inline(fragment: str) -> str:
    """行内元素与实体。"""
    fragment = re.sub(r'<span class="pre">(.*?)</span>', r"`\1`", fragment, flags=re.S)
    fragment = re.sub(r"<code[^>]*>(.*?)</code>", r"`\1`", fragment, flags=re.S)
    fragment = re.sub(r"<strong[^>]*>(.*?)</strong>", r"**\1**", fragment, flags=re.S)
    fragment = re.sub(r"<em[^>]*>(.*?)</em>", r"*\1*", fragment, flags=re.S)
    fragment = re.sub(r'<a class="reference external"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"[\2](\1)", fragment, flags=re.S)
    fragment = re.sub(r'<a class="reference internal"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"[\2](\1)", fragment, flags=re.S)
    fragment = re.sub(r'<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"[\2](\1)", fragment, flags=re.S)
    fragment = re.sub(r"<img[^>]*alt=\"([^\"]*)\"[^>]*>", r"![\1]", fragment)
    fragment = re.sub(r"<br\s*/?>", "\n", fragment)
    fragment = re.sub(rf"</?(?:{BLOCK_TAGS})\b[^>]*>", "\n", fragment)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    return html.unescape(fragment)


def convert(html_text: str) -> str:
    fragment = _drop_noise(_article(html_text))
    fragment = _code_blocks(fragment)
    fragment = _tables(fragment)
    fragment = _admonitions(fragment)
    fragment = _headings(fragment)
    fragment = _lists(fragment)
    text = _inline(fragment)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"\n- \n", "\n", text)
    return text.strip() + "\n"


def main(argv: list[str]) -> int:
    targets = argv[1:]
    if not targets:
        print(__doc__)
        return 2
    for target in targets:
        source = pathlib.Path(target)
        markdown = convert(source.read_text(encoding="utf-8", errors="replace"))
        output = source.with_suffix(".md")
        output.write_text(markdown, encoding="utf-8")
        print(f"{source.name} → {output.name}（{len(markdown.splitlines())} 行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

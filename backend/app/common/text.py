"""通用文本处理。"""

from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")
_FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_ATX = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_QUOTE = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)
_BULLET = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_ORDERED = re.compile(r"^\s*\d+[.、)]\s+", re.MULTILINE)
_EMPHASIS = re.compile(r"[*_~]{1,3}")
_HTML = re.compile(r"<[^>]+>")

DEFAULT_SUMMARY_LIMIT = 160

# Markdown 表格行：`| 问题 | 原因 |`
_TABLE_ROW = re.compile(r"^\|.*\|$")
# 表格分隔行：`| --- | :--: |`
_TABLE_DELIMITER = re.compile(r"^[\s:|-]*$")


def _flatten_tables(text: str) -> str:
    """把表格压成一行可读文本。

    不去掉的话，摘要里会出现 `| 问题 | 原因 | | --- | --- |` 这种原始语法，
    在列表页非常难读。
    """
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if len(stripped) > 1 and stripped.startswith("|") and stripped.endswith("|"):
            inner = stripped[1:-1]
            if _TABLE_DELIMITER.match(inner):
                continue
            cells = [cell.strip() for cell in inner.split("|")]
            out.append(" · ".join(cell for cell in cells if cell))
        else:
            out.append(line)
    return "\n".join(out)


def summarize_markdown(text: str, limit: int = DEFAULT_SUMMARY_LIMIT) -> str:
    """生成 Markdown 摘要：去掉结构符号后截断。

    列表页只展示摘要，避免把完整答案全部下发（docs/03 第 4 节）。
    """
    if not text:
        return ""
    result = _FENCED_CODE.sub(" ", text)
    result = _INLINE_CODE.sub(r"\1", result)
    result = _IMAGE.sub(" ", result)
    result = _LINK.sub(r"\1", result)
    result = _flatten_tables(result)
    result = _ATX.sub("", result)
    result = _QUOTE.sub("", result)
    result = _BULLET.sub("", result)
    result = _ORDERED.sub("", result)
    result = _EMPHASIS.sub("", result)
    result = _HTML.sub(" ", result)
    result = _WHITESPACE.sub(" ", result).strip()
    if len(result) <= limit:
        return result
    return result[: limit - 1].rstrip() + "…"

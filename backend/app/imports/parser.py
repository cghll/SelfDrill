"""Markdown 语法树解析。

设计要点：

1. **只从 heading token 取标题**。markdown-it 已经保证 fenced code、HTML block
   里的 `#` 不会被解析成标题，所以这里不做任何全局正则切割（docs/04 第 2.2 节）。
2. **答案取原文切片**。答案范围用源文件行号切片，而不是重新渲染 token，
   这样代码块、表格、列表、图片和必要的 HTML 都能原样保留（FR-003）。
3. **边界取决于分类结果**。父题答案截止到「下一个题目」或「同级/更高级的分类标题」；
   更深的分类标题（例如「常见同步方式」）留在答案内部。
"""

from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass, field

from markdown_it import MarkdownIt

from app.common.errors import MarkdownParseFailedError
from app.imports import classifier as classifier_module
from app.imports.normalizer import normalize_title, strip_html, strip_markdown_inline

_md = MarkdownIt("commonmark")

_ATX_MARKER = re.compile(r"^\s{0,3}(#{1,6})\s*(.*?)\s*#*\s*$")
_HEADING_NUMBER = re.compile(
    r"^\s*(?:[（(]\s*\d+\s*[)）]|\d+\s*[.、)）]|[一二三四五六七八九十]+\s*[、.)）])\s*"
)
_WHITESPACE = re.compile(r"[ \t\u3000]+")


@dataclass
class Heading:
    index: int
    level: int
    raw_title: str
    inline_title: str
    title: str
    start_line: int  # 1-based，标题所在行
    end_line: int  # 1-based，标题所占最后一行
    body_start_line: int  # 1-based，标题之后第一行
    classification: str = "section"
    score: int = 0
    confidence: float = 0.0
    needs_review: bool = False
    reasons: list[str] = field(default_factory=list)
    section_path: list[str] = field(default_factory=list)
    answer_markdown: str = ""
    answer_end_line: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class ParsedDocument:
    source_filename: str
    source_hash: str
    line_count: int
    items: list[Heading]
    headings: list[Heading]
    warnings: list[str]


def parse_headings(text: str) -> list[Heading]:
    """从 Markdown 文本中提取全部标题（含行号信息）。"""
    lines = text.splitlines()
    try:
        tokens = _md.parse(text)
    except Exception as exc:  # pragma: no cover - markdown-it 极少抛异常
        raise MarkdownParseFailedError(f"Markdown 解析失败：{type(exc).__name__}") from exc

    headings: list[Heading] = []
    for position, token in enumerate(tokens):
        if token.type != "heading_open":
            continue
        line_map = token.map
        if not line_map:
            continue
        start_line, end_line = line_map[0] + 1, line_map[1]  # 转成 1-based 闭区间

        inline = tokens[position + 1] if position + 1 < len(tokens) else None
        inline_title = inline.content if inline is not None and inline.type == "inline" else ""

        raw_title = "\n".join(lines[line_map[0] : line_map[1]]).strip()
        title = clean_heading_title(raw_title, inline_title, token.tag)

        headings.append(
            Heading(
                index=len(headings),
                level=int(token.tag[1]),
                raw_title=raw_title,
                inline_title=inline_title,
                title=title,
                start_line=start_line,
                end_line=end_line,
                body_start_line=end_line + 1,
            )
        )
    return headings


def clean_heading_title(raw_title: str, inline_title: str, tag: str) -> str:
    """清理标题：去 # 标记、去 HTML、去行内标记、去开头序号。"""
    source = raw_title
    atx = _ATX_MARKER.match(source.splitlines()[0]) if source else None
    if atx and tag.startswith("h"):
        source = atx.group(2)
    elif "\n" in source:
        # Setext 标题：正文在第一行，第二行是 === 或 ---
        source = source.splitlines()[0]

    if not source.strip() and inline_title:
        source = inline_title

    result = html.unescape(strip_html(source))
    result = strip_markdown_inline(result)
    result = classifier_module.strip_heading_number(result)
    result = _WHITESPACE.sub(" ", result).strip()
    return result


def parse_document(
    text: str,
    *,
    source_filename: str,
    source_hash: str,
    max_seconds: float | None = None,
) -> ParsedDocument:
    """解析文档并产出题目候选列表。"""
    started = time.monotonic()
    lines = text.splitlines()

    headings = parse_headings(text)
    warnings: list[str] = []

    if not headings:
        warnings.append("文档中没有任何 Markdown 标题，无法识别题目")

    # 第一步：分类
    for heading in headings:
        if not heading.title:
            heading.classification = "section"
            heading.warnings.append("标题为空，已作为分类处理")
            continue
        result = classifier_module.classify(heading.title, heading.level)
        heading.classification = result.classification
        heading.score = result.score
        heading.confidence = result.confidence
        heading.needs_review = result.needs_review
        heading.reasons = result.reasons

    # 第二步：把「有正文的纯主题标题」升级为待确认
    # 面试文档里常见「JVM 内存结构」这类只有主题名词、却带完整答案的标题。
    # 直接当成分类会丢掉这段内容，所以交给用户确认，而不是静默丢弃。
    _promote_content_bearing_sections(headings, lines)

    # 第三步：章节路径（只记录被判定为分类的祖先标题）
    _assign_section_paths(headings)

    # 第四步：答案边界
    _assign_answer_ranges(headings, lines)

    if max_seconds is not None and time.monotonic() - started > max_seconds:
        raise MarkdownParseFailedError("Markdown 解析耗时超过限制")

    items = [
        heading
        for heading in headings
        if heading.classification in ("question", "needs_review")
    ]

    warnings.extend(_document_warnings(headings, lines))

    return ParsedDocument(
        source_filename=source_filename,
        source_hash=source_hash,
        line_count=len(lines),
        items=items,
        headings=headings,
        warnings=warnings,
    )


def _promote_content_bearing_sections(headings: list[Heading], lines: list[str]) -> None:
    """把「被判定为分类、但自己带着正文」的标题升级为待确认。

    「Redis 篇」「常见同步方式」这类结构标题即使有正文也不算题目；
    而「JVM 内存结构」这种纯主题名词标题带着答案时，几乎都是被漏掉的题目。
    """
    for index, heading in enumerate(headings):
        if heading.classification != "section" or not heading.title:
            continue
        if classifier_module.is_structural_heading(heading.title):
            continue
        if not _direct_body_text(headings, index, lines):
            continue
        heading.classification = "needs_review"
        heading.needs_review = True
        heading.reasons = [*heading.reasons, "分类标题但带有正文，升级为待确认"]
        heading.warnings.append("该标题更像主题分类，但下面有正文，请确认它是题目还是分类")


def _direct_body_text(headings: list[Heading], index: int, lines: list[str]) -> str:
    """标题「自己」的正文，遇到任意更深或同级的标题就停止。

    与 `_find_answer_end` 不同：这里判断的是这个标题有没有直属内容，
    子标题的内容不算它的直属正文，否则顶层标题会把整篇文档都算成自己的正文。
    """
    heading = headings[index]
    end_line = len(lines)
    if index + 1 < len(headings):
        end_line = headings[index + 1].start_line - 1
    if end_line < heading.body_start_line:
        return ""
    return "\n".join(lines[heading.body_start_line - 1 : end_line]).strip()


def _assign_section_paths(headings: list[Heading]) -> None:
    """章节路径 = 所有祖先标题（不论祖先被判为题目还是分类）。

    这与 docs/04 第 5 节的样例一致：示例里子题的 `section_path` 就是它的题目型
    父标题（`["反射是什么"]`）。稳定关联键因此会包含父题标题——父题改名会连带
    影响子题的 `stable_key`，这是当前既定语义，不是缺陷。
    """
    stack: list[Heading] = []
    for heading in headings:
        while stack and stack[-1].level >= heading.level:
            stack.pop()
        heading.section_path = [ancestor.title for ancestor in stack if ancestor.title]
        stack.append(heading)


def _assign_answer_ranges(headings: list[Heading], lines: list[str]) -> None:
    for index, heading in enumerate(headings):
        if heading.classification not in ("question", "needs_review"):
            heading.answer_markdown = ""
            heading.answer_end_line = heading.start_line
            continue

        end_line = _find_answer_end(headings, index, len(lines))
        body_start = heading.body_start_line
        if end_line < body_start:
            answer = ""
            heading.answer_end_line = heading.start_line
        else:
            answer = "\n".join(lines[body_start - 1 : end_line])
            heading.answer_end_line = end_line

        heading.answer_markdown = answer.strip("\n").rstrip()
        if not heading.answer_markdown.strip():
            heading.warnings.append(NO_ANSWER_WARNING)


def _find_answer_end(headings: list[Heading], index: int, total_lines: int) -> int:
    """答案截止行（1-based 闭区间）。

    终止条件：遇到下一个题目候选，或遇到同级/更高级的分类标题。
    更深的分类标题（答案内小标题）不会终止答案。
    """
    current = headings[index]
    for candidate in headings[index + 1 :]:
        if candidate.classification in ("question", "needs_review"):
            return candidate.start_line - 1
        if candidate.classification == "section" and candidate.level <= current.level:
            return candidate.start_line - 1
    return total_lines


NO_ANSWER_WARNING = "该题目没有识别到答案内容"


def recompute_answer_ranges(items: list[dict], lines: list[str]) -> list[dict]:
    """按各条目**当前**的分类重算答案边界（FR-005 人工修正边界）。

    用户在预览里把一个子标题标成「分类」时，它的正文应当并回父题答案；
    反过来把分类标成题目时，父题答案要相应缩短。解析阶段算出的边界此时已经过期，
    必须重算，否则「预览里看到的内容」和「确认后写进题库的内容」会不一致。

    原地更新 `items` 中受影响条目的答案字段，返回这些条目。
    """
    if not items:
        return []

    headings = [
        Heading(
            index=index,
            level=int(item.get("heading_level", 2)),
            raw_title=item.get("raw_title", ""),
            inline_title="",
            title=item.get("title", ""),
            start_line=int(item.get("source_anchor", {}).get("start_line", 1)),
            end_line=int(item.get("body_start_line", 1)) - 1,
            body_start_line=int(item.get("body_start_line", 1)),
            classification=item.get("classification", "section"),
        )
        for index, item in enumerate(items)
    ]

    _assign_answer_ranges(headings, lines)

    affected: list[dict] = []
    for item, heading in zip(items, headings):
        previous_answer = item.get("answer_markdown", "")
        previous_end = dict(item.get("source_anchor", {}))

        item["answer_markdown"] = heading.answer_markdown
        item["source_anchor"] = {
            **previous_end,
            "end_line": heading.answer_end_line or heading.start_line,
        }
        item["content_flags"] = detect_content_flags(heading.answer_markdown)

        # 「没有答案」这条警告要跟着重算结果走，其余警告保持原样
        warnings = [w for w in item.get("warnings", []) if w != NO_ANSWER_WARNING]
        if NO_ANSWER_WARNING in heading.warnings:
            warnings.append(NO_ANSWER_WARNING)
        item["warnings"] = warnings

        if (
            item["answer_markdown"] != previous_answer
            or item["source_anchor"] != previous_end
        ):
            affected.append(item)

    return affected


def _document_warnings(headings: list[Heading], lines: list[str]) -> list[str]:
    warnings: list[str] = []

    first_item = next(
        (h for h in headings if h.classification in ("question", "needs_review")), None
    )
    if first_item is not None and first_item.body_start_line > 1:
        preamble = "\n".join(lines[: first_item.body_start_line - 1]).strip()
        if preamble:
            warnings.append(
                f"第一个题目之前有 {first_item.body_start_line - 1} 行内容未归入任何题目"
            )

    orphan_lines = _count_orphan_lines(headings, lines)
    if orphan_lines:
        warnings.append(f"有 {orphan_lines} 行内容不属于任何题目（通常是章节引言）")

    if any(h.needs_review for h in headings):
        count = sum(1 for h in headings if h.needs_review)
        warnings.append(f"有 {count} 个标题无法高置信判断，需要在预览中确认")

    return warnings


def _count_orphan_lines(headings: list[Heading], lines: list[str]) -> int:
    """统计既不属于题目答案、也不在标题行上的非空行数。"""
    covered: set[int] = set()
    for heading in headings:
        covered.update(range(heading.start_line, heading.end_line + 1))
        if heading.classification in ("question", "needs_review"):
            covered.update(range(heading.start_line, heading.answer_end_line + 1))

    count = 0
    for line_number, line in enumerate(lines, start=1):
        if line_number in covered:
            continue
        if line.strip():
            count += 1
    return count


def to_preview_item_payload(heading: Heading, local_id: str) -> dict:
    """转成 docs/04 第 5 节的中间结构。"""
    return {
        "local_id": local_id,
        "title": heading.title,
        "raw_title": heading.raw_title,
        "heading_level": heading.level,
        "section_path": list(heading.section_path),
        "answer_markdown": heading.answer_markdown,
        "classification": heading.classification,
        "confidence": heading.confidence,
        "needs_review": heading.needs_review,
        "score": heading.score,
        "reasons": list(heading.reasons),
        "normalized_title": normalize_title(heading.title),
        # 供 patch 阶段重算答案边界使用，不对外暴露（PreviewItemOut 不包含该字段）
        "body_start_line": heading.body_start_line,
        "source_anchor": {
            "start_line": heading.start_line,
            "end_line": heading.answer_end_line or heading.start_line,
        },
        "content_flags": detect_content_flags(heading.answer_markdown),
        "warnings": list(heading.warnings),
    }


_FENCE = re.compile(r"^\s*(?:```|~~~)", re.MULTILINE)
_IMAGE_LINK = re.compile(r"!\[[^\]]*\]\(")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]\s+|\d+[.、)]\s+)", re.MULTILINE)
_RAW_HTML = re.compile(r"</?[A-Za-z][^>]*>")


def detect_content_flags(answer_markdown: str) -> dict[str, bool]:
    """预览需要告诉用户「代码块/图片/列表/表格/HTML 有没有被保留」（FR-005）。"""
    text = answer_markdown or ""
    return {
        "code_block": bool(_FENCE.search(text)),
        "image": bool(_IMAGE_LINK.search(text)),
        "table": bool(_TABLE_ROW.search(text)),
        "list": bool(_LIST_ITEM.search(text)),
        "html": bool(_RAW_HTML.search(text)),
    }

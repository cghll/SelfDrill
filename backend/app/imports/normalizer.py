"""标题与内容的规范化。

规范化同时用于两处：

- `stable_key`：判断「这是不是同一道题」，必须对展示层差异免疫。
- `content_hash`：判断「这道题的内容变了没有」，必须对排版差异免疫。

规范化后的结果仍保留「什么」「如何」等语义关键词，否则改名检测会失效。
"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata

# 行内 Markdown 强调标记：成对出现时才去掉，避免破坏 `int* p` 这类代码内容
_EMPHASIS_PATTERNS = (
    re.compile(r"\*\*\*(?=\S)(.+?)(?<=\S)\*\*\*", re.DOTALL),
    re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.DOTALL),
    re.compile(r"(?<![*\w])\*(?=\S)(.+?)(?<=\S)\*(?![*\w])", re.DOTALL),
    re.compile(r"___(?=\S)(.+?)(?<=\S)___", re.DOTALL),
    re.compile(r"__(?=\S)(.+?)(?<=\S)__", re.DOTALL),
    re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.DOTALL),
    re.compile(r"`([^`\n]+)`"),
)
_HTML_TAG = re.compile(r"<[^>]+>")
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_HEADING_MARKER = re.compile(r"^\s{0,3}#{1,6}\s*")
_LIST_MARKER = re.compile(
    # 序号后面不要求空格（「1.说说」很常见），但用负向断言避免吃掉「2.0 版本」这类版本号
    r"^\s*(?:[-*+]\s+|\d{1,3}\s*[.、)）](?!\d)\s*|[（(]\s*\d+\s*[)）]\s*"
    r"|[一二三四五六七八九十]+\s*[、.)）]\s*)",
    re.MULTILINE,
)
_WHITESPACE = re.compile(r"\s+")

# 代码必须先于 HTML 清洗被摘出来。`List<String>`、`Map<K, V>`、`a < b` 这类代码
# 片段会被 `_HTML_TAG` 当成标签整段删掉，导致「改了代码的答案」和原答案哈希相同，
# 更新被静默判定为「未变化」而丢弃。代码是内容，不是展示标记。
_FENCED_CODE = re.compile(r"(?ms)^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?^[ \t]*\1[ \t]*$")
_INLINE_CODE = re.compile(r"`[^`\n]+`")
_CODE_PLACEHOLDER = re.compile("\x00(\\d+)\x00")

# NFKC 已经处理了大部分全角字符，这里补齐中文标点
_PUNCTUATION_MAP = {
    "。": ".",
    "、": ",",
    "，": ",",
    "；": ";",
    "：": ":",
    "！": "!",
    "？": "?",
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
    "《": "<",
    "》": ">",
    "（": "(",
    "）": ")",
    "【": "[",
    "】": "]",
    "…": "...",
    "—": "-",
    "－": "-",
    "　": " ",
}


def strip_html(text: str) -> str:
    """去掉展示用 HTML 标签，保留标签内的文本。"""
    return _HTML_TAG.sub("", text)


def strip_markdown_inline(text: str) -> str:
    """去掉行内 Markdown 标记，保留可见文本。"""
    result = _LINK.sub(r"\1", text)
    for pattern in _EMPHASIS_PATTERNS:
        previous = None
        while previous != result:
            previous = result
            result = pattern.sub(r"\1", result)
    return result


def unify_punctuation(text: str) -> str:
    return "".join(_PUNCTUATION_MAP.get(char, char) for char in text)


def _protect_code(text: str) -> tuple[str, list[str]]:
    """把代码片段替换成占位符，返回 (带占位符的文本, 原始代码片段表)。

    存进占位符表的是**代码正文**（不含围栏/反引号），语言标记单独保留一行：
    - 反引号属于展示标记，标题里的 `` `HashMap` `` 必须和 `HashMap` 归一化到同一结果；
    - 正文必须逐字保留，否则 `List<String>` 会被 HTML 清洗删成 `List`，
      代码改动就再也无法被识别为「修改」。
    """
    stash: list[str] = []

    def stash_fenced(match: re.Match[str]) -> str:
        info = match.group(0).split("\n", 1)[0].strip().lstrip("`~").strip()
        body = match.group(0).split("\n", 1)[1] if "\n" in match.group(0) else ""
        # 去掉收尾的围栏行
        body = body.rsplit("\n", 1)[0] if "\n" in body else body
        stash.append(f"{info}\n{body}".strip("\n"))
        return f"\x00{len(stash) - 1}\x00"

    def stash_inline(match: re.Match[str]) -> str:
        stash.append(match.group(0)[1:-1])
        return f"\x00{len(stash) - 1}\x00"

    # 先围栏代码块，再行内代码：否则围栏的反引号会被行内规则先吃掉
    protected = _FENCED_CODE.sub(stash_fenced, text)
    protected = _INLINE_CODE.sub(stash_inline, protected)
    return protected, stash


def _restore_code(text: str, stash: list[str]) -> str:
    return _CODE_PLACEHOLDER.sub(lambda match: stash[int(match.group(1))], text)


def normalize_text(text: str, *, fold_case: bool = True) -> str:
    """通用规范化。

    `fold_case` 对标题为真（标题大小写不应影响同一性判定），对答案同样为真：
    `String` 与 `string` 的差异属于排版级差异，按文档要求折叠，
    宁可少报一次「修改」，也不要制造大量无意义的内容变更。

    唯一的例外是代码：代码块与行内代码先被摘出来，跳过 HTML/强调标记清洗，
    最后原样放回。否则 `List<String>` 会被当成 HTML 标签删成 `List`，
    代码改动就再也无法被识别为「修改」。
    """
    if not text:
        return ""
    result = unicodedata.normalize("NFKC", text)
    result = html.unescape(result)
    result, code_stash = _protect_code(result)
    result = strip_html(result)
    result = strip_markdown_inline(result)
    result = _HEADING_MARKER.sub("", result)
    result = _LIST_MARKER.sub("", result)
    result = unify_punctuation(result)
    result = _restore_code(result, code_stash)
    result = _WHITESPACE.sub(" ", result).strip()
    if fold_case:
        result = result.casefold()
    return result


def normalize_title(title: str) -> str:
    return normalize_text(title, fold_case=True)


def normalize_answer(answer_markdown: str) -> str:
    return normalize_text(answer_markdown, fold_case=True)


def normalize_section_path(section_path: list[str] | None) -> str:
    parts = [normalize_title(part) for part in (section_path or []) if part and part.strip()]
    return " / ".join(parts)


def compute_stable_key(title: str, section_path: list[str] | None) -> str:
    """稳定关联键：规范化标题 + 规范化章节路径。"""
    return f"{normalize_title(title)}|{normalize_section_path(section_path)}"


def compute_content_hash(title: str, answer_markdown: str) -> str:
    payload = f"{normalize_title(title)}\n{normalize_answer(answer_markdown)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def similarity(left: str, right: str) -> float:
    """标题相似度，用于「改名候选」的粗筛。

    使用字符级 Dice 系数：对中文标题比编辑距离更稳定，且不依赖分词。
    """
    a = normalize_title(left)
    b = normalize_title(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if len(a) < 2 or len(b) < 2:
        return 1.0 if a == b else 0.0
    bigrams_a = {a[i : i + 2] for i in range(len(a) - 1)}
    bigrams_b = {b[i : i + 2] for i in range(len(b) - 1)}
    if not bigrams_a or not bigrams_b:
        return 0.0
    overlap = len(bigrams_a & bigrams_b)
    return 2 * overlap / (len(bigrams_a) + len(bigrams_b))

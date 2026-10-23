"""阶段 3：Markdown 解析器测试。

覆盖 docs/04 第 8 节列出的解析器样例。
"""

from __future__ import annotations

from app.imports.parser import parse_document

SAMPLE = """\
# Java 面试复习

## 1.说说java中HashMap的原理

HashMap 基于数组 + 链表 + 红黑树实现。

```java
// ### 这是代码块里的假标题
int hash = key.hashCode();
```

### HashMap 的扩容机制是什么？

扩容时容量翻倍。

## 6.redis篇

Redis 是一个内存数据库。

### redis通常应用在哪些场景

缓存、分布式锁、计数器。

#### 面试官追问

##### 追问：为什么 Redis 用单线程还这么快？

因为基于内存与 IO 多路复用。

### 反射所能够提供的功能有哪些？

- 获取 Class 对象
- 获取构造器

#### 常见同步方式

| 方式 | 说明 |
| --- | --- |
| synchronized | 关键字 |

![示意图](https://example.com/a.png)

## 2.并发篇

### synchronized 和 ReentrantLock 的区别

两者在锁的粒度上不同。
"""


def _parse(text: str = SAMPLE):
    return parse_document(text, source_filename="java.md", source_hash="hash")


def _titles(text: str = SAMPLE) -> list[str]:
    return [item.title for item in _parse(text).items]


def _by_title(title: str, text: str = SAMPLE):
    for item in _parse(text).items:
        if item.title == title:
            return item
    raise AssertionError(f"未找到题目：{title}")


# --- 样例 1 / 2：二级标题直接作为题目、二级章节下的三级标题作为题目 ---


def test_h2_question_is_recognised() -> None:
    item = _by_title("说说java中HashMap的原理")
    assert item.classification == "question"
    assert item.level == 2


def test_h3_under_section_is_recognised() -> None:
    item = _by_title("redis通常应用在哪些场景")
    assert item.classification == "question"
    assert item.level == 3
    assert item.section_path == ["Java 面试复习", "redis篇"]


def test_section_path_includes_question_ancestors() -> None:
    """docs/04 第 5 节：子题的 section_path 就是它的**题目型**父标题。

    章节路径不是「只由分类标题组成」，而是标题树上的全部祖先。
    """
    child = _by_title("HashMap 的扩容机制是什么？")
    assert child.section_path == ["Java 面试复习", "说说java中HashMap的原理"]


# --- 样例 3：父题和子题同时是题目 ---


def test_parent_and_child_are_both_questions() -> None:
    titles = _titles()
    assert "说说java中HashMap的原理" in titles
    assert "HashMap 的扩容机制是什么？" in titles


def test_parent_answer_excludes_child_content() -> None:
    """父题答案必须截止到子题标题之前，不能把子题内容重复塞进父题。"""
    parent = _by_title("说说java中HashMap的原理")
    assert "扩容时容量翻倍" not in parent.answer_markdown
    assert "HashMap 基于数组" in parent.answer_markdown

    child = _by_title("HashMap 的扩容机制是什么？")
    assert "扩容时容量翻倍" in child.answer_markdown
    assert "HashMap 基于数组" not in child.answer_markdown


# --- 样例 4：分类标题不作为题目 ---


def test_category_headings_are_not_questions() -> None:
    titles = _titles()
    assert "redis篇" not in titles
    assert "并发篇" not in titles
    assert "Java 面试复习" not in titles


# --- 样例 5：单独「追问」不作为题目 ---


def test_plain_follow_up_heading_is_not_a_question() -> None:
    assert "面试官追问" not in _titles()


# --- 样例 6：具体的「追问：为什么……」作为题目 ---


def test_specific_follow_up_is_a_question() -> None:
    titles = _titles()
    assert "追问：为什么 Redis 用单线程还这么快？" in titles


# --- 样例 7：代码块中的假标题 ---


def test_code_fence_headings_are_ignored() -> None:
    titles = _titles()
    assert not any("假标题" in title for title in titles)
    assert len(_parse().headings) == 11


def test_code_block_is_preserved_in_answer() -> None:
    parent = _by_title("说说java中HashMap的原理")
    assert "```java" in parent.answer_markdown
    assert "int hash = key.hashCode();" in parent.answer_markdown


# --- 样例 8：HTML 标签包裹标题 ---


def test_html_wrapped_heading_is_cleaned() -> None:
    text = '## <font color="red">1.说说java中HashMap的原理</font>\n\n内容\n'
    parsed = parse_document(text, source_filename="a.md", source_hash="h")
    assert [item.title for item in parsed.items] == ["说说java中HashMap的原理"]
    assert parsed.items[0].raw_title.startswith('<font color="red">') or parsed.items[
        0
    ].raw_title.startswith("## <font")


def test_heading_keeps_raw_title() -> None:
    item = _by_title("说说java中HashMap的原理")
    assert item.raw_title.startswith("## 1.")


# --- 样例 9：序号、中文标点、英文缩写 ---


def test_heading_number_and_punctuation_are_cleaned() -> None:
    text = "## 1、HashMap 和 Hashtable 有什么区别？\n\n答案\n"
    parsed = parse_document(text, source_filename="a.md", source_hash="h")
    assert parsed.items[0].title == "HashMap 和 Hashtable 有什么区别？"


def test_full_width_numbering_is_cleaned() -> None:
    text = "## （1）HashMap 的负载因子是多少？\n\n答案\n"
    parsed = parse_document(text, source_filename="a.md", source_hash="h")
    assert parsed.items[0].title == "HashMap 的负载因子是多少？"


# --- 样例 10：图片、表格、列表、代码块保留在答案中 ---


def test_rich_content_is_preserved_in_answer() -> None:
    answer = _by_title("反射所能够提供的功能有哪些？").answer_markdown
    assert "- 获取 Class 对象" in answer
    assert "| 方式 | 说明 |" in answer
    assert "![示意图](https://example.com/a.png)" in answer
    assert "#### 常见同步方式" in answer  # 答案内小标题保留


# --- 结构信息 ---


def test_source_anchor_points_at_heading_and_answer_end() -> None:
    item = _by_title("redis通常应用在哪些场景")
    assert item.start_line > 0
    assert item.answer_end_line > item.start_line


def test_answer_range_stops_at_same_level_section() -> None:
    item = _by_title("HashMap 的扩容机制是什么？")
    assert "redis篇" not in item.answer_markdown
    assert "Redis 是一个内存数据库" not in item.answer_markdown


def test_document_without_headings_produces_warning() -> None:
    parsed = parse_document("就是一段普通文字\n", source_filename="a.md", source_hash="h")
    assert parsed.items == []
    assert any("没有任何 Markdown 标题" in warning for warning in parsed.warnings)


def test_needs_review_headings_are_reported() -> None:
    """纯主题名词标题带着正文时，不能静默当成分类丢掉内容。"""
    text = "# 顶层\n\n## JVM 内存结构\n\n堆、栈、方法区\n"
    parsed = parse_document(text, source_filename="a.md", source_hash="h")
    assert parsed.items[0].needs_review is True
    assert parsed.items[0].title == "JVM 内存结构"
    assert any("无法高置信判断" in warning for warning in parsed.warnings)


def test_structural_headings_are_not_promoted_to_review() -> None:
    """「Redis 篇」「常见同步方式」即使有正文也仍是结构标题。"""
    text = "# 顶层\n\n## redis篇\n\nRedis 是一个内存数据库。\n"
    parsed = parse_document(text, source_filename="a.md", source_hash="h")
    assert parsed.items == []
    assert all(not heading.needs_review for heading in parsed.headings)


def test_strong_ask_verb_title_is_a_question() -> None:
    text = "# 顶层\n\n## 谈谈你对 JVM 内存模型的理解\n\n答案\n"
    parsed = parse_document(text, source_filename="a.md", source_hash="h")
    assert parsed.items[0].classification == "question"


def test_item_without_answer_is_warned() -> None:
    text = "## HashMap 的原理是什么？\n\n## 下一个问题是什么？\n\n答案\n"
    parsed = parse_document(text, source_filename="a.md", source_hash="h")
    assert any("没有识别到答案" in warning for warning in parsed.items[0].warnings)


def test_setext_headings_are_supported() -> None:
    text = "HashMap 的原理是什么？\n===\n\n答案内容\n"
    parsed = parse_document(text, source_filename="a.md", source_hash="h")
    assert parsed.items[0].title == "HashMap 的原理是什么？"
    assert "答案内容" in parsed.items[0].answer_markdown

"""阶段 3：规范化与哈希稳定性测试。"""

from __future__ import annotations

from app.imports.normalizer import (
    compute_content_hash,
    compute_stable_key,
    normalize_answer,
    normalize_text,
    normalize_title,
    similarity,
    strip_markdown_inline,
)


def test_normalize_removes_html_and_emphasis() -> None:
    assert normalize_title('<font color="red">HashMap</font>') == "hashmap"
    assert normalize_title("**HashMap** 的原理") == "hashmap 的原理"
    assert normalize_title("`HashMap` 的原理") == "hashmap 的原理"
    assert normalize_title("[HashMap](https://x.com) 的原理") == "hashmap 的原理"


def test_normalize_removes_leading_numbering() -> None:
    assert normalize_title("1.说说 HashMap") == "说说 hashmap"
    assert normalize_title("（1）说说 HashMap") == "说说 hashmap"
    assert normalize_title("一、说说 HashMap") == "说说 hashmap"


def test_normalize_unifies_width_case_and_punctuation() -> None:
    assert normalize_title("ＨashMap") == normalize_title("HashMap")
    assert normalize_title("HashMap 是什么？") == normalize_title("hashmap 是什么?")


def test_normalize_keeps_semantic_words() -> None:
    """规范化不能把「什么」「如何」这类关键词吃掉，否则改名检测会失效。"""
    normalized = normalize_title("HashMap 的原理是什么？")
    assert "什么" in normalized
    assert "原理" in normalized


def test_normalize_collapses_whitespace() -> None:
    assert normalize_title("HashMap    的\n原理") == "hashmap 的 原理"


def test_emphasis_inside_code_is_not_destroyed() -> None:
    """`int* p` 这类内容不能被强调标记规则误伤。"""
    assert "int* p" in strip_markdown_inline("int* p")


def test_stable_key_uses_title_and_section_path() -> None:
    first = compute_stable_key("HashMap 的原理是什么？", ["Java 基础"])
    second = compute_stable_key("1.HashMap 的原理是什么？", ["Java 基础"])
    third = compute_stable_key("HashMap 的原理是什么？", ["Java 并发"])
    assert first == second
    assert first != third


def test_content_hash_is_stable_across_formatting() -> None:
    left = compute_content_hash("HashMap 的原理", "答案是 **数组 + 链表**")
    right = compute_content_hash("1.HashMap 的原理", "答案是 数组 + 链表")
    assert left == right


def test_content_hash_changes_with_content() -> None:
    left = compute_content_hash("HashMap 的原理", "数组 + 链表")
    right = compute_content_hash("HashMap 的原理", "数组 + 链表 + 红黑树")
    assert left != right


def test_content_hash_changes_with_title() -> None:
    left = compute_content_hash("HashMap 的原理", "答案")
    right = compute_content_hash("Hashtable 的原理", "答案")
    assert left != right


def test_identical_documents_hash_identically() -> None:
    """样例 11：重复导入完全相同的文件。"""
    title = "redis通常应用在哪些场景"
    answer = "缓存、分布式锁、计数器"
    assert compute_content_hash(title, answer) == compute_content_hash(title, answer)


def test_normalize_answer_keeps_structure_significant_text() -> None:
    answer = "```java\nint a = 1;\n```\n\n- 项目一\n"
    normalized = normalize_answer(answer)
    assert "int a = 1;" in normalized
    assert "项目一" in normalized


# --- 回归：代码是内容，不是展示标记 ---


def test_content_hash_changes_when_code_changes() -> None:
    """回归：`List<String>` 曾被 HTML 清洗当成标签删成 `List`。

    结果是「改了代码的答案」和原答案哈希相同，更新被静默判定为「未变化」而丢弃。
    泛型、比较运算符这类代码片段必须参与内容比较。
    """
    before = "```java\nList<String> values;\n```"
    after = "```java\nList<Integer> values;\n```"
    assert compute_content_hash("泛型的作用", before) != compute_content_hash("泛型的作用", after)


def test_content_hash_changes_when_comparison_code_changes() -> None:
    assert compute_content_hash("比较", "```c\nif (a < b) {}\n```") != compute_content_hash(
        "比较", "```c\nif (a > b) {}\n```"
    )


def test_normalize_answer_preserves_generics_verbatim() -> None:
    """泛型的尖括号必须活下来（大小写仍按既定语义折叠）。"""
    normalized = normalize_answer("```java\nMap<String, List<Integer>> map;\n```")
    assert "<string, list<integer>>" in normalized


def test_content_hash_ignores_inline_code_delimiters() -> None:
    """反引号是展示标记，`HashMap` 与 HashMap 必须等价。"""
    assert compute_content_hash("题", "用 `HashMap` 存") == compute_content_hash("题", "用 HashMap 存")


def test_similarity_scores() -> None:
    assert similarity("HashMap 的原理", "HashMap 的原理") == 1.0
    assert similarity("HashMap 的原理是什么", "HashMap 的实现原理是什么") > 0.6
    assert similarity("HashMap 的原理", "Redis 持久化机制") < 0.2


def test_normalize_text_handles_empty_input() -> None:
    assert normalize_text("") == ""
    assert normalize_title("   ") == ""

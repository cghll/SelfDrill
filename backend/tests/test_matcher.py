"""阶段 3：更新差异计算测试（纯函数层）。

覆盖 FR-006 的匹配优先级与 docs/04 第 6 节。
"""

from __future__ import annotations

from app.imports.matcher import (
    ExistingQuestion,
    IncomingQuestion,
    match_questions,
)
from app.imports.normalizer import compute_content_hash, compute_stable_key


def _existing(
    question_id: str,
    title: str,
    section_path: list[str],
    answer: str = "旧答案",
) -> ExistingQuestion:
    return ExistingQuestion(
        question_id=question_id,
        revision_id=f"rev-{question_id}",
        title=title,
        section_path=section_path,
        answer_markdown=answer,
        content_hash=compute_content_hash(title, answer),
        stable_key=compute_stable_key(title, section_path),
    )


def _incoming(
    local_id: str, title: str, section_path: list[str], answer: str = "旧答案"
) -> IncomingQuestion:
    return IncomingQuestion(
        local_id=local_id,
        title=title,
        section_path=section_path,
        answer_markdown=answer,
    )


def test_unchanged_question_is_matched() -> None:
    existing = [_existing("q1", "HashMap 的原理是什么？", ["Java 基础"])]
    incoming = [_incoming("n1", "HashMap 的原理是什么？", ["Java 基础"])]

    results, unmatched = match_questions(incoming, existing)
    assert results["n1"].action == "unchanged"
    assert results["n1"].matched_question_id == "q1"
    assert unmatched == []


def test_modified_answer_is_detected() -> None:
    existing = [_existing("q1", "HashMap 的原理是什么？", ["Java 基础"], "旧答案")]
    incoming = [_incoming("n1", "HashMap 的原理是什么？", ["Java 基础"], "新答案")]

    results, unmatched = match_questions(incoming, existing)
    assert results["n1"].action == "modified"
    assert results["n1"].matched_question_id == "q1"
    assert unmatched == []


def test_identical_reimport_produces_no_changes() -> None:
    """验收标准 4：完全重复导入不会新增重复题目。"""
    existing = [
        _existing("q1", "HashMap 的原理是什么？", ["Java 基础"]),
        _existing("q2", "redis通常应用在哪些场景", ["Redis 篇"]),
    ]
    incoming = [
        _incoming("n1", "1.HashMap 的原理是什么？", ["Java 基础"]),
        _incoming("n2", "redis通常应用在哪些场景", ["Redis 篇"]),
    ]

    results, unmatched = match_questions(incoming, existing)
    assert {result.action for result in results.values()} == {"unchanged"}
    assert unmatched == []


def test_new_question_is_added() -> None:
    existing = [_existing("q1", "HashMap 的原理是什么？", ["Java 基础"])]
    incoming = [
        _incoming("n1", "HashMap 的原理是什么？", ["Java 基础"]),
        _incoming("n2", "ConcurrentHashMap 如何保证线程安全？", ["Java 基础"]),
    ]

    results, _unmatched = match_questions(incoming, existing)
    assert results["n2"].action == "added"


def test_removed_question_is_reported_as_unmatched() -> None:
    existing = [
        _existing("q1", "HashMap 的原理是什么？", ["Java 基础"]),
        _existing("q2", "ArrayList 的扩容机制是什么？", ["Java 基础"]),
    ]
    incoming = [_incoming("n1", "HashMap 的原理是什么？", ["Java 基础"])]

    _results, unmatched = match_questions(incoming, existing)
    assert [item.question_id for item in unmatched] == ["q2"]


def test_renamed_title_is_ambiguous_not_silent() -> None:
    """验收标准 7：题目改名不能被静默当作删除加新增。"""
    existing = [_existing("q1", "HashMap 的底层原理是什么", ["Java 基础"])]
    incoming = [_incoming("n1", "HashMap 的底层实现原理是什么", ["Java 基础"])]

    results, unmatched = match_questions(incoming, existing)
    assert results["n1"].action == "ambiguous"
    assert results["n1"].matched_question_id is None
    assert results["n1"].candidates
    assert results["n1"].candidates[0]["question_id"] == "q1"
    # 匹配层不做取舍：旧题既没有被消费，也没有被静默删除，
    # 由 build_diff 把它标成「可能被改名」而不是「删除」。
    assert [item.question_id for item in unmatched] == ["q1"]


def test_title_change_across_different_section_is_not_a_candidate() -> None:
    existing = [_existing("q1", "HashMap 的底层原理是什么", ["Java 基础"])]
    incoming = [_incoming("n1", "HashMap 的底层实现原理是什么", ["Java 并发"])]

    results, unmatched = match_questions(incoming, existing)
    assert results["n1"].action == "added"
    assert [item.question_id for item in unmatched] == ["q1"]


def test_numbering_does_not_affect_matching() -> None:
    """原文序号只用于展示，不能作为匹配依据。"""
    existing = [_existing("q1", "说说 HashMap 的原理", ["Java 基础"])]
    incoming = [_incoming("n1", "12、说说 HashMap 的原理", ["Java 基础"])]

    results, _unmatched = match_questions(incoming, existing)
    assert results["n1"].action == "unchanged"


def test_moved_question_matches_by_title_even_if_section_changed() -> None:
    existing = [_existing("q1", "HashMap 的原理是什么？", ["Java 基础"])]
    incoming = [_incoming("n1", "HashMap 的原理是什么？", ["Java 集合"])]

    results, _unmatched = match_questions(incoming, existing)
    assert results["n1"].matched_question_id == "q1"


def test_two_new_questions_cannot_consume_the_same_old_question() -> None:
    """拆题场景：旧题只能被消费一次。"""
    existing = [_existing("q1", "HashMap 的原理是什么？", ["Java 基础"])]
    incoming = [
        _incoming("n1", "HashMap 的原理是什么？", ["Java 基础"]),
        _incoming("n2", "HashMap 的原理是什么？", ["Java 基础"]),
    ]

    results, _unmatched = match_questions(incoming, existing)
    matched = [r.matched_question_id for r in results.values() if r.matched_question_id]
    assert matched.count("q1") == 1


def test_structural_ambiguity_hints_at_renames() -> None:
    from app.imports.matcher import detect_structural_ambiguity

    incoming = [_incoming("n1", "HashMap 的底层实现原理是什么", ["Java 基础"])]
    unmatched = [_existing("q1", "HashMap 的底层原理是什么", ["Java 基础"])]

    hints = detect_structural_ambiguity(incoming, unmatched)
    assert hints["n1"][0]["question_id"] == "q1"

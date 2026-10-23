"""阶段 3：标题分类器测试。"""

from __future__ import annotations

import pytest

from app.imports.classifier import (
    classify,
    has_follow_up_prefix_with_content,
    is_answer_internal_heading,
    is_category_heading,
    is_generic_heading,
    is_structural_heading,
    strip_heading_number,
)


@pytest.mark.parametrize(
    ("title", "level"),
    [
        ("说说java中HashMap的原理", 2),
        ("HashMap 的扩容机制是什么？", 3),
        ("redis通常应用在哪些场景", 3),
        ("反射所能够提供的功能有哪些？", 3),
        ("synchronized 和 ReentrantLock 的区别", 3),
        ("ConcurrentHashMap 如何保证线程安全？", 3),
        ("为什么 MySQL 用 B+ 树？", 2),
        ("谈谈你对 JVM 内存模型的理解", 2),
        ("追问：为什么 Redis 用单线程还这么快？", 5),
    ],
)
def test_question_titles(title: str, level: int) -> None:
    result = classify(title, level)
    assert result.classification == "question", (title, result)


@pytest.mark.parametrize(
    ("title", "level"),
    [
        ("redis篇", 2),
        ("并发篇", 2),
        ("Docker 篇", 2),
        ("常见同步方式", 4),
        ("实现线程安全一般有四种思路", 4),
        ("线程不安全的根源", 4),
        ("评论区补充", 4),
        ("补充说明", 4),
        ("面试官追问", 4),
        ("追问", 4),
        ("Java 基础", 2),
        ("MySQL 索引", 3),
        ("目录", 2),
    ],
)
def test_section_titles(title: str, level: int) -> None:
    result = classify(title, level)
    assert result.classification == "section", (title, result)


def test_generic_heading_detection() -> None:
    assert is_generic_heading("追问") is True
    assert is_generic_heading("面试官追问") is True
    assert is_generic_heading(" 补充 ") is True
    # 带具体问题的追问不是泛化标题
    assert is_generic_heading("追问：为什么 Redis 用单线程还这么快？") is False
    # 「常见同步方式」属于答案内小标题，不是追问标记
    assert is_generic_heading("常见同步方式") is False
    assert is_answer_internal_heading("常见同步方式") is True
    assert is_answer_internal_heading("线程不安全的根源") is True


def test_structural_heading_detection() -> None:
    assert is_structural_heading("面试官追问") is True
    assert is_structural_heading("常见同步方式") is True
    assert is_structural_heading("redis篇") is True
    assert is_structural_heading("JVM 内存结构") is False
    assert is_category_heading("Docker 篇") is True
    assert is_category_heading("JVM 内存结构") is False


def test_follow_up_prefix_with_content() -> None:
    assert has_follow_up_prefix_with_content("追问：为什么 Redis 单线程还快？") is True
    assert has_follow_up_prefix_with_content("面试官追问 什么是 CAP") is True
    assert has_follow_up_prefix_with_content("追问") is False
    assert has_follow_up_prefix_with_content("补充说明") is False


def test_strip_heading_number() -> None:
    assert strip_heading_number("1.说说java中HashMap的原理") == "说说java中HashMap的原理"
    assert strip_heading_number("（1）HashMap 的原理") == "HashMap 的原理"
    assert strip_heading_number("1、HashMap 的原理") == "HashMap 的原理"
    assert strip_heading_number("一、HashMap 的原理") == "HashMap 的原理"
    # 技术名词里的数字不能被误删
    assert strip_heading_number("B+ 树是什么") == "B+ 树是什么"
    assert strip_heading_number("HTTP/2 有什么改进？") == "HTTP/2 有什么改进？"


def test_confidence_is_monotonic_in_score() -> None:
    high = classify("HashMap 的原理是什么？", 2)
    low = classify("常见同步方式", 4)
    assert high.confidence > low.confidence
    assert 0.0 <= low.confidence <= 1.0
    assert 0.0 <= high.confidence <= 1.0


def test_classification_reasons_are_explained() -> None:
    result = classify("HashMap 的原理是什么？", 2)
    assert result.reasons
    assert result.score >= 3

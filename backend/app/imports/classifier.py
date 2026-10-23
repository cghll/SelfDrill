"""标题分类启发式。

判定一个 Markdown 标题是「题目」「分类」还是「待确认」。

打分规则来自 docs/02 第 7.1 节与 docs/04 第 3 节，阈值经过样例校准：

- h2/h3 基础分 +1：文档里题目绝大多数出现在二三级标题。
- 问句词 +3：最可靠的题目信号。
- 问号 +2：显式疑问形式。
- 强提问动词（说说/介绍/解释/讲讲/谈谈）+3：祈使式提问。
- 弱主题词（原理/作用/区别/实现…）+1：单独出现不足以判定为题目。
- 无问号且无问句词 -2：陈述性标题，通常是答案内小标题。
- 以 篇/章/模块/目录/知识点 结尾 -4：主题分类。
- 泛化标题（追问/补充/评论区…）-5：结构标题，不是题面。

阈值：>=3 判为题目，1..2 进入待确认，<=0 判为分类。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal

Classification = Literal["question", "section", "needs_review"]

# 问句词：出现即强烈暗示这是一个问题
QUESTION_WORDS = (
    "什么",
    "为什么",
    "为何",
    "如何",
    "怎么",
    "怎样",
    "哪些",
    "哪种",
    "哪个",
    "哪里",
    "是否",
    "能否",
    "多少",
    "几种",
    "区别",
    "有什么",
)

# 强提问动词：祈使式提问，「说说 xxx」「介绍下 xxx」
STRONG_ASK_VERBS = ("说说", "介绍", "解释", "讲讲", "谈谈", "聊聊", "描述", "简述", "概述")

# 弱主题词：只有配合其他信号才说明是题目
WEAK_TOPIC_WORDS = (
    "原理",
    "特点",
    "作用",
    "用途",
    "场景",
    "对比",
    "支持",
    "实现",
    "解决",
    "保证",
    "使用",
    "配置",
    "优化",
    "设计",
    "机制",
    "流程",
    "过程",
)

# 主题分类后缀：「Redis 篇」「并发篇」
CATEGORY_SUFFIXES = ("篇", "章", "模块", "目录", "知识点")

# 泛化结构标题：单独的追问/补充标记，不是题面
GENERIC_HEADINGS = {
    "追问",
    "面试官追问",
    "追问补充",
    "补充",
    "评论区补充",
    "评论补充",
}

# 答案内小标题（docs/04 第 3.3 节）：默认保留在上级题目的答案里
ANSWER_INTERNAL_HEADINGS = {
    "常见同步方式",
    "实现线程安全一般有四种思路",
    "线程不安全的根源",
    "补充说明",
    "评论区补充",
    "补充",
}

# 「追问：为什么……」这类带具体问题的追问前缀
FOLLOW_UP_PREFIXES = ("面试官追问", "追问", "补充", "评论区补充", "评论补充")

QUESTION_MARKS = ("?", "？")

_QUESTION_THRESHOLD = 3
_REVIEW_THRESHOLD = 1

# 去掉标点后用于判断「是不是纯泛化词」
_PUNCT_ONLY = re.compile(r"[\s\W_]+", re.UNICODE)
_HEADING_NUMBER_PREFIX = re.compile(
    r"^\s*(?:[（(]\s*\d+\s*[)）]|\d+\s*[.、)）]|[一二三四五六七八九十]+\s*[、.)）])\s*"
)


@dataclass(frozen=True)
class ClassificationResult:
    classification: Classification
    score: int
    confidence: float
    needs_review: bool
    reasons: list[str]


def strip_heading_number(title: str) -> str:
    """去掉开头的序号，序号只用于展示，不能参与匹配。"""
    previous = None
    current = title
    while previous != current:
        previous = current
        current = _HEADING_NUMBER_PREFIX.sub("", current, count=1).strip()
    return current


def _compact(title: str) -> str:
    return _PUNCT_ONLY.sub("", title).lower()


def is_generic_heading(title: str) -> bool:
    """判断是否为纯泛化结构标题。

    「追问」是结构标题，但「追问：为什么 HashMap 线程不安全」不是——
    后者带了具体问题，按题目处理。
    """
    compact = _compact(title)
    if not compact:
        return False
    return compact in {_compact(item) for item in GENERIC_HEADINGS}


def is_answer_internal_heading(title: str) -> bool:
    """判断是否为答案内小标题（docs/04 第 3.3 节）。"""
    compact = _compact(title)
    if not compact:
        return False
    return compact in {_compact(item) for item in ANSWER_INTERNAL_HEADINGS}


def is_category_heading(title: str) -> bool:
    """「Redis 篇」「并发模块」这类主题分类标题。"""
    return title.endswith(CATEGORY_SUFFIXES)


def is_structural_heading(title: str) -> bool:
    """结构标题：无论有没有正文，都不应该升级为待确认题目。"""
    return is_generic_heading(title) or is_answer_internal_heading(title) or is_category_heading(title)


def has_follow_up_prefix_with_content(title: str) -> bool:
    """标题以追问/补充类前缀开头，且后面跟了具体问题。

    「追问」「面试官追问」「补充说明」是结构标题；
    「追问：为什么 Redis 用单线程还这么快？」是题目。
    """
    if is_generic_heading(title):
        return False

    stripped = title.strip()
    for prefix in FOLLOW_UP_PREFIXES:
        if not stripped.startswith(prefix):
            continue
        remainder = stripped[len(prefix) :].lstrip()
        if not remainder:
            continue
        # 要求有分隔符（「追问：」「追问 」），或剩余部分本身带疑问信号
        separator_follows = stripped[len(prefix) : len(prefix) + 1] in ("：", ":", "，", ",", "、", " ", "\u3000")
        has_question_signal = any(word in remainder for word in QUESTION_WORDS) or any(
            mark in remainder for mark in QUESTION_MARKS
        )
        if separator_follows or has_question_signal:
            return True
    return False


def score_title(title: str, level: int) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    if level in (2, 3):
        score += 1
        reasons.append("h2/h3 基础分 +1")

    if any(word in title for word in QUESTION_WORDS):
        score += 3
        reasons.append("问句词 +3")

    if any(mark in title for mark in QUESTION_MARKS):
        score += 2
        reasons.append("问号 +2")

    if any(verb in title for verb in STRONG_ASK_VERBS):
        score += 3
        reasons.append("强提问动词 +3")

    if any(word in title for word in WEAK_TOPIC_WORDS):
        score += 2
        reasons.append("问题动作词 +2")

    has_interrogative = any(word in title for word in QUESTION_WORDS) or any(
        mark in title for mark in QUESTION_MARKS
    )
    has_strong_ask = any(verb in title for verb in STRONG_ASK_VERBS)
    # 祈使式提问（「说说 xxx」「谈谈你对 xxx 的理解」）本身就是疑问意图，
    # 不能再按陈述性标题扣分。
    if not has_interrogative and not has_strong_ask:
        score -= 2
        reasons.append("陈述性标题 -2")

    if title.endswith(CATEGORY_SUFFIXES):
        score -= 4
        reasons.append("主题分类后缀 -4")

    if is_generic_heading(title):
        score -= 5
        reasons.append("泛化结构标题 -5")
    elif has_follow_up_prefix_with_content(title):
        score += 2
        reasons.append("追问前缀带具体问题 +2")

    return score, reasons


def classify(title: str, level: int) -> ClassificationResult:
    score, reasons = score_title(title, level)

    if is_generic_heading(title):
        classification: Classification = "section"
    elif score >= _QUESTION_THRESHOLD:
        classification = "question"
    elif score >= _REVIEW_THRESHOLD:
        classification = "needs_review"
    else:
        classification = "section"

    confidence = _sigmoid((score - 2.5) / 1.5)
    return ClassificationResult(
        classification=classification,
        score=score,
        confidence=round(confidence, 2),
        needs_review=classification == "needs_review",
        reasons=reasons,
    )


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))

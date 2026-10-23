"""阶段 8：真实样例文件的端到端测试。

使用 `samples/` 下的真实 Markdown 文档，走完整流程：
登录 → 建库 → 首次导入预览 → 确认 → 刷题（reveal/advance/完成）
→ 更新导入（新增/修改/删除/歧义）→ 确认新版本 → 新一轮使用新版本。

这是对整个产品闭环的回归测试，任何一环退化都会在这里暴露。
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SAMPLES = Path(__file__).resolve().parent.parent.parent / "samples"
V1_FILE = SAMPLES / "java热门面试.md"
V2_FILE = SAMPLES / "java热门面试-v2.md"

# v1 识别出的题目（h1 文档标题进入待确认，其余为高置信题目）
V1_QUESTION_COUNT = 13
V1_NEEDS_REVIEW_COUNT = 1


def _upload(client: TestClient, bank_id: str, path: Path):
    data = path.read_bytes()
    return client.post(
        f"/api/v1/banks/{bank_id}/imports/preview",
        files={"file": (path.name, io.BytesIO(data), "text/markdown")},
    )


def _confirm(client: TestClient, preview_id: str, **payload):
    body = {
        "accepted_preview_item_ids": [],
        "resolved_ambiguities": [],
        "confirmed_deleted_question_ids": [],
    }
    body.update(payload)
    return client.post(f"/api/v1/imports/{preview_id}/confirm", json=body)


def _high_confidence_ids(body: dict) -> list[str]:
    return [
        item["preview_item_id"]
        for item in body["items"]
        if item["classification"] == "question"
    ]


@pytest.fixture()
def samples_available() -> None:
    if not V1_FILE.exists() or not V2_FILE.exists():
        pytest.skip("缺少 samples/ 样例文件")


def test_parser_handles_real_sample(samples_available: None) -> None:
    """真实文档的解析结果必须与设计预期一致。"""
    from app.imports.normalizer import sha256_hex
    from app.imports.parser import parse_document

    raw = V1_FILE.read_bytes()
    parsed = parse_document(
        raw.decode("utf-8"),
        source_filename=V1_FILE.name,
        source_hash=sha256_hex(raw),
    )

    by_title = {heading.title: heading for heading in parsed.headings}

    # 代码块里的 static final 不能被当成标题
    assert not any("TREEIFY_THRESHOLD" in title for title in by_title)

    # 分类标题不是题目
    assert by_title["redis篇"].classification == "section"
    assert by_title["并发篇"].classification == "section"
    assert by_title["反射篇"].classification == "section"

    # 单独「面试官追问」是结构标题
    assert by_title["面试官追问"].classification == "section"

    # 带具体问题的追问是题目
    assert by_title["追问：为什么 Redis 用单线程还这么快？"].classification == "question"
    assert by_title["追问：Redis 6.0 为什么引入多线程？"].classification == "question"

    # 答案内小标题保留在答案里，不作为题目
    assert by_title["常见同步方式"].classification == "section"
    assert by_title["线程不安全的根源"].classification == "section"
    assert by_title["补充说明"].classification == "section"

    # 父题答案不含子题内容
    parent = by_title["说说java中HashMap的原理"]
    assert "扩容触发条件" not in parent.answer_markdown
    assert "TREEIFY_THRESHOLD" in parent.answer_markdown

    # 子题答案独立
    child = by_title["HashMap 的扩容机制是什么？"]
    assert "扩容触发条件" in child.answer_markdown

    # 代码块、表格、图片、列表都保留在答案中
    assert "```java" in parent.answer_markdown
    assert "| 参数 | 默认值 | 说明 |" in child.answer_markdown
    assert "![扩容示意图](https://example.com/hashmap-resize.png)" in child.answer_markdown

    reflect = by_title["反射所能够提供的功能有哪些？"]
    assert "- 在运行时获取类的 `Class` 对象" in reflect.answer_markdown
    assert "```java" in reflect.answer_markdown


def test_full_flow_first_import_to_round_completion(
    auth_client: TestClient, samples_available: None
) -> None:
    """端到端主流程。"""
    # 1. 建库
    bank = auth_client.post(
        "/api/v1/banks",
        json={"name": "Java 热门面试", "description": "Java、Redis、并发和中间件"},
    ).json()
    bank_id = bank["id"]

    # 2. 首次导入预览
    preview = _upload(auth_client, bank_id, V1_FILE)
    assert preview.status_code == 201, preview.text
    body = preview.json()

    assert body["mode"] == "create"
    assert body["source_filename"] == V1_FILE.name
    assert body["summary"]["high_confidence"] == V1_QUESTION_COUNT
    assert body["summary"]["needs_review"] == V1_NEEDS_REVIEW_COUNT
    assert body["diff"]["added"] == V1_QUESTION_COUNT + V1_NEEDS_REVIEW_COUNT

    # 3. 把文档标题标为分类，确认全部导入
    doc_title = next(
        item for item in body["items"] if item["title"] == "Java 热门面试题整理"
    )
    auth_client.patch(
        f"/api/v1/imports/{body['preview_id']}/items/{doc_title['preview_item_id']}",
        json={"classification": "section"},
    )

    accepted = _high_confidence_ids(body)
    result = _confirm(
        auth_client, body["preview_id"], accepted_preview_item_ids=accepted
    )
    assert result.status_code == 201, result.text
    confirmed = result.json()
    assert confirmed["version_number"] == 1
    assert confirmed["changes"]["added"] == V1_QUESTION_COUNT

    # 4. 题库状态
    detail = auth_client.get(f"/api/v1/banks/{bank_id}").json()
    assert detail["question_count"] == V1_QUESTION_COUNT
    assert detail["current_version"] == 1

    # 5. 开始轮次
    round_response = auth_client.post(
        f"/api/v1/banks/{bank_id}/rounds", json={"restart": False}
    )
    assert round_response.status_code == 201, round_response.text
    round_body = round_response.json()
    round_id = round_body["id"]
    assert round_body["total_count"] == V1_QUESTION_COUNT

    # 6. 走完一轮，记录每道题的标题
    seen_titles: list[str] = []
    version = round_body["progress_version"]

    current = round_body
    while current["status"] == "in_progress":
        item = current["current_item"]
        seen_titles.append(item["question"]["title"])

        # 答案默认隐藏
        assert item["answer"] is None
        assert item["answer_revealed"] is False

        # 查看答案
        revealed = auth_client.post(f"/api/v1/rounds/{round_id}/reveal").json()
        assert revealed["answer_revealed"] is True
        assert revealed["answer"]

        # 下一题
        current = auth_client.post(
            f"/api/v1/rounds/{round_id}/advance",
            json={
                "expected_progress_version": version,
                "idempotency_key": f"step-{version}",
            },
        ).json()
        version = current["progress_version"]

    # 每题恰好一次
    assert len(seen_titles) == V1_QUESTION_COUNT
    assert len(set(seen_titles)) == V1_QUESTION_COUNT
    assert current["status"] == "completed"
    assert current["completed_at"] is not None

    # 7. 完成后可以从题库开始下一轮
    next_round = auth_client.post(
        f"/api/v1/banks/{bank_id}/rounds", json={"restart": False}
    ).json()
    assert next_round["round_number"] == 2
    assert next_round["total_count"] == V1_QUESTION_COUNT


def test_full_flow_update_import(auth_client: TestClient, samples_available: None) -> None:
    """端到端更新流程：新增 / 修改 / 删除 / 歧义 / 版本切换。"""
    bank_id = auth_client.post("/api/v1/banks", json={"name": "Java 热门面试"}).json()["id"]

    # --- 首次导入 ---
    first = _upload(auth_client, bank_id, V1_FILE).json()
    doc_title = next(i for i in first["items"] if i["title"] == "Java 热门面试题整理")
    auth_client.patch(
        f"/api/v1/imports/{first['preview_id']}/items/{doc_title['preview_item_id']}",
        json={"classification": "section"},
    )
    accepted = _high_confidence_ids(first)
    assert _confirm(
        auth_client, first["preview_id"], accepted_preview_item_ids=accepted
    ).status_code == 201

    def question_ids() -> dict[str, str]:
        page = auth_client.get(
            f"/api/v1/banks/{bank_id}/questions", params={"page_size": 200}
        ).json()
        return {item["title"]: item["question_id"] for item in page["items"]}

    before = question_ids()
    assert len(before) == V1_QUESTION_COUNT

    # --- 更新导入 ---
    second = _upload(auth_client, bank_id, V2_FILE).json()
    assert second["mode"] == "update"

    # 文档标题（h1）带引言，属于低置信项，每次导入都会再次进入待确认列表。
    # 这是 FR-004 的既定行为：无法高置信判断的标题必须交给用户确认，
    # 而不是被系统静默归类；不放进 accepted 列表就等于明确放弃它。
    doc_title_v2 = next(i for i in second["items"] if i["title"] == "Java 热门面试题整理")
    assert doc_title_v2["classification"] == "needs_review"

    # 新增 = 新题 1 道 + 待确认的文档标题 1 项
    assert second["diff"]["added"] == 2
    # 两道题的答案被修改
    assert second["diff"]["modified"] == 2
    # 其余保持不变
    assert second["diff"]["unchanged"] == V1_QUESTION_COUNT - 2

    by_title = {item["title"]: item for item in second["items"]}
    assert by_title["HashMap 和 Hashtable 有什么区别？"]["action"] == "added"
    assert by_title["HashMap 的扩容机制是什么？"]["action"] == "modified"
    assert by_title["ConcurrentHashMap 如何保证线程安全？"]["action"] == "modified"
    assert by_title["什么是 AQS？"]["action"] == "unchanged"

    # --- 确认更新 ---
    accepted_second = _high_confidence_ids(second)
    result = _confirm(
        auth_client, second["preview_id"], accepted_preview_item_ids=accepted_second
    )
    assert result.status_code == 201, result.text
    confirmed = result.json()
    assert confirmed["version_number"] == 2
    assert confirmed["changes"]["added"] == 1
    assert confirmed["changes"]["modified"] == 2

    # --- 版本切换与题目身份保持 ---
    detail = auth_client.get(f"/api/v1/banks/{bank_id}").json()
    assert detail["current_version"] == 2
    assert detail["question_count"] == V1_QUESTION_COUNT + 1

    versions = {
        version["version_number"]: version
        for version in auth_client.get(f"/api/v1/banks/{bank_id}/versions").json()
    }
    assert versions[1]["status"] == "superseded"
    assert versions[2]["status"] == "active"

    after = question_ids()
    # 未变化的题目必须复用同一个 question_id
    assert after["什么是 AQS？"] == before["什么是 AQS？"]
    # 被修改的题目身份也不变
    assert after["HashMap 的扩容机制是什么？"] == before["HashMap 的扩容机制是什么？"]
    # 新题是全新身份
    assert after["HashMap 和 Hashtable 有什么区别？"] not in before.values()

    # 修改后的答案确实生效
    page = auth_client.get(
        f"/api/v1/banks/{bank_id}/questions", params={"page_size": 200}
    ).json()
    changed = next(i for i in page["items"] if i["title"] == "HashMap 的扩容机制是什么？")
    assert "JDK 8 之后不再需要重新计算 hash" in changed["answer_summary"]


def test_round_created_before_update_still_uses_old_version(
    auth_client: TestClient, samples_available: None
) -> None:
    """docs/04 第 7 节：轮次 R1 固定使用 V1，题库更新到 V2 后 R1 不受影响。"""
    bank_id = auth_client.post("/api/v1/banks", json={"name": "Java 热门面试"}).json()["id"]

    first = _upload(auth_client, bank_id, V1_FILE).json()
    doc_title = next(i for i in first["items"] if i["title"] == "Java 热门面试题整理")
    auth_client.patch(
        f"/api/v1/imports/{first['preview_id']}/items/{doc_title['preview_item_id']}",
        json={"classification": "section"},
    )
    _confirm(
        auth_client,
        first["preview_id"],
        accepted_preview_item_ids=_high_confidence_ids(first),
    )

    # R1 在 V1 上开始
    round_body = auth_client.post(
        f"/api/v1/banks/{bank_id}/rounds", json={"restart": False}
    ).json()
    round_id = round_body["id"]
    v1_id = round_body["bank_version_id"]

    # 题库更新到 V2
    second = _upload(auth_client, bank_id, V2_FILE).json()
    assert _confirm(
        auth_client,
        second["preview_id"],
        accepted_preview_item_ids=_high_confidence_ids(second),
    ).status_code == 201

    # R1 仍然使用 V1，题目数不变
    still = auth_client.get(f"/api/v1/rounds/{round_id}").json()
    assert still["bank_version_id"] == v1_id
    assert still["total_count"] == V1_QUESTION_COUNT

    # 继续推进 R1 依然正常
    advanced = auth_client.post(
        f"/api/v1/rounds/{round_id}/advance",
        json={"expected_progress_version": still["progress_version"]},
    )
    assert advanced.status_code == 200
    assert advanced.json()["bank_version_id"] == v1_id

    # 放弃 R1 后开新一轮，才使用 V2
    auth_client.post(f"/api/v1/rounds/{round_id}/abandon")
    fresh = auth_client.post(
        f"/api/v1/banks/{bank_id}/rounds", json={"restart": False}
    ).json()
    assert fresh["bank_version_id"] != v1_id
    assert fresh["total_count"] == V1_QUESTION_COUNT + 1


def test_deletion_of_question_requires_explicit_confirmation(
    auth_client: TestClient, samples_available: None, tmp_path: Path
) -> None:
    """真实样例上的删除流程：未确认 → 409，确认后新版本少一道题。"""
    bank_id = auth_client.post("/api/v1/banks", json={"name": "Java 热门面试"}).json()["id"]

    first = _upload(auth_client, bank_id, V1_FILE).json()
    doc_title = next(i for i in first["items"] if i["title"] == "Java 热门面试题整理")
    auth_client.patch(
        f"/api/v1/imports/{first['preview_id']}/items/{doc_title['preview_item_id']}",
        json={"classification": "section"},
    )
    _confirm(
        auth_client,
        first["preview_id"],
        accepted_preview_item_ids=_high_confidence_ids(first),
    )

    # 删掉 AQS 那一节
    text = V1_FILE.read_text(encoding="utf-8")
    start = text.index("### 什么是 AQS？")
    end = text.index("## 3.redis篇")
    shortened = text[:start] + text[end:]
    shortened_file = tmp_path / "java热门面试-删减.md"
    shortened_file.write_text(shortened, encoding="utf-8")

    body = _upload(auth_client, bank_id, shortened_file).json()
    assert len(body["deleted_items"]) == 1
    deleted = body["deleted_items"][0]
    assert deleted["title"] == "什么是 AQS？"

    # 未确认删除 → 409，题库不变
    blocked = _confirm(
        auth_client, body["preview_id"], accepted_preview_item_ids=_high_confidence_ids(body)
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "IMPORT_CONFIRMATION_REQUIRED"
    assert auth_client.get(f"/api/v1/banks/{bank_id}").json()["current_version"] == 1

    # 确认删除 → 新版本少一道题
    result = _confirm(
        auth_client,
        body["preview_id"],
        accepted_preview_item_ids=_high_confidence_ids(body),
        confirmed_deleted_question_ids=[deleted["question_id"]],
    )
    assert result.status_code == 201, result.text
    assert result.json()["changes"]["deleted"] == 1

    detail = auth_client.get(f"/api/v1/banks/{bank_id}").json()
    assert detail["question_count"] == V1_QUESTION_COUNT - 1

    page = auth_client.get(
        f"/api/v1/banks/{bank_id}/questions", params={"page_size": 200}
    ).json()
    assert "什么是 AQS？" not in {item["title"] for item in page["items"]}


def test_round_has_every_question_exactly_once_over_many_rounds(
    auth_client: TestClient, samples_available: None
) -> None:
    """验收标准 8：多轮重复抽取，每轮内部不重不漏。"""
    from app.db.models import RoundItem
    from app.db.session import get_session_factory

    bank_id = auth_client.post("/api/v1/banks", json={"name": "Java 热门面试"}).json()["id"]
    first = _upload(auth_client, bank_id, V1_FILE).json()
    doc_title = next(i for i in first["items"] if i["title"] == "Java 热门面试题整理")
    auth_client.patch(
        f"/api/v1/imports/{first['preview_id']}/items/{doc_title['preview_item_id']}",
        json={"classification": "section"},
    )
    _confirm(
        auth_client,
        first["preview_id"],
        accepted_preview_item_ids=_high_confidence_ids(first),
    )

    revision_sets: list[set[str]] = []
    orders: list[tuple[str, ...]] = []

    for _ in range(5):
        round_id = auth_client.post(
            f"/api/v1/banks/{bank_id}/rounds", json={"restart": True}
        ).json()["id"]
        with get_session_factory()() as session:
            items = (
                session.query(RoundItem)
                .filter_by(round_id=round_id)
                .order_by(RoundItem.position)
                .all()
            )
            revision_sets.append({item.question_revision_id for item in items})
            orders.append(tuple(item.question_revision_id for item in items))

    # 集合完全一致，且每题恰好一次
    assert all(len(item) == V1_QUESTION_COUNT for item in revision_sets)
    assert all(item == revision_sets[0] for item in revision_sets)
    # 顺序确实被打乱过
    assert len(set(orders)) > 1

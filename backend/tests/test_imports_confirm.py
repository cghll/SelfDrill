"""阶段 4：更新确认与版本切换测试。

覆盖 FR-006、验收标准 3/4/5/6/7 以及 docs/04 第 7 节的版本与轮次关系。
"""

from __future__ import annotations

import io

from fastapi.testclient import TestClient

BASE_DOC = """\
# Java 面试复习

## 说说java中HashMap的原理

HashMap 基于数组 + 链表 + 红黑树。

## redis通常应用在哪些场景

缓存、分布式锁、计数器。

## 反射所能够提供的功能有哪些？

- 获取 Class 对象
"""


def _create_bank(client: TestClient, name: str = "Java 热门面试") -> str:
    response = client.post("/api/v1/banks", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _upload(client: TestClient, bank_id: str, content: str, filename: str = "java.md"):
    response = client.post(
        f"/api/v1/banks/{bank_id}/imports/preview",
        files={"file": (filename, io.BytesIO(content.encode("utf-8")), "text/markdown")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _confirm(client: TestClient, preview_id: str, **payload):
    body = {
        "accepted_preview_item_ids": [],
        "resolved_ambiguities": [],
        "confirmed_deleted_question_ids": [],
    }
    body.update(payload)
    return client.post(f"/api/v1/imports/{preview_id}/confirm", json=body)


def _item(body: dict, title: str) -> dict:
    return next(item for item in body["items"] if item["title"] == title)


def _all_question_ids(body: dict) -> list[str]:
    return [
        item["preview_item_id"]
        for item in body["items"]
        if item["classification"] == "question"
    ]


def _question_id(client: TestClient, bank_id: str, title: str) -> str:
    page = client.get(
        f"/api/v1/banks/{bank_id}/questions", params={"page_size": 200}
    ).json()
    return next(item["question_id"] for item in page["items"] if item["title"] == title)


def _import_base(client: TestClient, bank_id: str) -> dict:
    body = _upload(client, bank_id, BASE_DOC)
    response = _confirm(client, body["preview_id"])
    assert response.status_code == 201, response.text
    return body


# --- 首次导入 ---


def test_first_import_creates_version_one(auth_client: TestClient) -> None:
    bank_id = _create_bank(auth_client)
    body = _upload(auth_client, bank_id, BASE_DOC)
    response = _confirm(auth_client, body["preview_id"])
    assert response.status_code == 201, response.text

    result = response.json()
    assert result["bank_id"] == bank_id
    assert result["version_number"] == 1
    assert result["changes"]["added"] == 3
    assert result["changes"]["modified"] == 0
    assert result["changes"]["deleted"] == 0

    detail = auth_client.get(f"/api/v1/banks/{bank_id}").json()
    assert detail["question_count"] == 3
    assert detail["current_version"] == 1

    versions = auth_client.get(f"/api/v1/banks/{bank_id}/versions").json()
    assert len(versions) == 1
    assert versions[0]["status"] == "active"


def test_first_import_creates_stable_question_identity(auth_client: TestClient) -> None:
    bank_id = _create_bank(auth_client)
    _import_base(auth_client, bank_id)
    page = auth_client.get(f"/api/v1/banks/{bank_id}/questions").json()
    assert page["total"] == 3
    ids = {item["question_id"] for item in page["items"]}
    assert len(ids) == 3


def test_confirm_twice_is_rejected(auth_client: TestClient) -> None:
    """预览确认后即被消费，避免重复创建版本。"""
    bank_id = _create_bank(auth_client)
    body = _upload(auth_client, bank_id, BASE_DOC)
    assert _confirm(auth_client, body["preview_id"]).status_code == 201
    assert _confirm(auth_client, body["preview_id"]).status_code == 404
    assert len(auth_client.get(f"/api/v1/banks/{bank_id}/versions").json()) == 1


def test_confirm_requires_login(client: TestClient) -> None:
    response = client.post("/api/v1/imports/any-preview/confirm", json={})
    assert response.status_code == 401


def test_confirm_unknown_preview_returns_404(auth_client: TestClient) -> None:
    response = _confirm(auth_client, "00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


# --- 重复导入 ---


def test_identical_reimport_creates_no_duplicates(auth_client: TestClient) -> None:
    """验收标准 4：完全重复导入不会新增重复题目。"""
    bank_id = _create_bank(auth_client)
    _import_base(auth_client, bank_id)

    body = _upload(auth_client, bank_id, BASE_DOC)
    assert body["mode"] == "update"
    assert body["diff"]["unchanged"] == 3
    assert body["diff"]["added"] == 0
    assert body["deleted_items"] == []

    result = _confirm(auth_client, body["preview_id"]).json()
    assert result["version_number"] == 2
    assert result["changes"]["unchanged"] == 3
    assert result["changes"]["added"] == 0

    detail = auth_client.get(f"/api/v1/banks/{bank_id}").json()
    assert detail["question_count"] == 3


def test_reimport_keeps_question_identity(auth_client: TestClient) -> None:
    """未变化的题目必须复用同一个 question_id，否则历史进度会错位。"""
    bank_id = _create_bank(auth_client)
    _import_base(auth_client, bank_id)
    before = _question_id(auth_client, bank_id, "说说java中HashMap的原理")

    body = _upload(auth_client, bank_id, BASE_DOC)
    _confirm(auth_client, body["preview_id"])

    assert _question_id(auth_client, bank_id, "说说java中HashMap的原理") == before


def test_modified_answer_is_the_only_change(auth_client: TestClient) -> None:
    """验收标准 5：修改一道题的答案后，更新预览只把该题标记为修改。"""
    bank_id = _create_bank(auth_client)
    _import_base(auth_client, bank_id)

    updated = BASE_DOC.replace("缓存、分布式锁、计数器。", "缓存、分布式锁、计数器、限流。")
    body = _upload(auth_client, bank_id, updated)

    assert body["diff"]["modified"] == 1
    assert body["diff"]["unchanged"] == 2
    assert body["diff"]["added"] == 0

    modified = _item(body, "redis通常应用在哪些场景")
    assert modified["action"] == "modified"

    result = _confirm(auth_client, body["preview_id"]).json()
    assert result["changes"]["modified"] == 1
    assert result["changes"]["unchanged"] == 2


def test_old_version_is_superseded(auth_client: TestClient) -> None:
    bank_id = _create_bank(auth_client)
    _import_base(auth_client, bank_id)
    body = _upload(auth_client, bank_id, BASE_DOC.replace("红黑树", "红黑树和链表"))
    _confirm(auth_client, body["preview_id"])

    versions = auth_client.get(f"/api/v1/banks/{bank_id}/versions").json()
    by_number = {version["version_number"]: version for version in versions}
    assert by_number[1]["status"] == "superseded"
    assert by_number[2]["status"] == "active"


def test_new_question_is_added(auth_client: TestClient) -> None:
    """验收标准 6：新增题目可以在确认前被用户看到。"""
    bank_id = _create_bank(auth_client)
    _import_base(auth_client, bank_id)

    extended = BASE_DOC + "\n## ConcurrentHashMap 如何保证线程安全？\n\n分段锁与 CAS。\n"
    body = _upload(auth_client, bank_id, extended)
    assert body["diff"]["added"] == 1

    result = _confirm(auth_client, body["preview_id"]).json()
    assert result["changes"]["added"] == 1
    assert auth_client.get(f"/api/v1/banks/{bank_id}").json()["question_count"] == 4


# --- 删除需要显式确认 ---


def test_deletion_requires_confirmation(auth_client: TestClient) -> None:
    bank_id = _create_bank(auth_client)
    _import_base(auth_client, bank_id)

    shortened = BASE_DOC.replace(
        "## redis通常应用在哪些场景\n\n缓存、分布式锁、计数器。\n\n", ""
    )
    body = _upload(auth_client, bank_id, shortened)
    assert len(body["deleted_items"]) == 1

    # 未确认删除 → 409
    response = _confirm(auth_client, body["preview_id"])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IMPORT_CONFIRMATION_REQUIRED"

    # 题库仍然停留在版本 1
    detail = auth_client.get(f"/api/v1/banks/{bank_id}").json()
    assert detail["current_version"] == 1
    assert detail["question_count"] == 3


def test_confirmed_deletion_removes_question_from_new_version(auth_client: TestClient) -> None:
    bank_id = _create_bank(auth_client)
    _import_base(auth_client, bank_id)

    shortened = BASE_DOC.replace(
        "## redis通常应用在哪些场景\n\n缓存、分布式锁、计数器。\n\n", ""
    )
    body = _upload(auth_client, bank_id, shortened)
    deleted_id = body["deleted_items"][0]["question_id"]

    response = _confirm(
        auth_client,
        body["preview_id"],
        confirmed_deleted_question_ids=[deleted_id],
    )
    assert response.status_code == 201, response.text
    assert response.json()["changes"]["deleted"] == 1

    page = auth_client.get(
        f"/api/v1/banks/{bank_id}/questions", params={"page_size": 200}
    ).json()
    assert page["total"] == 2
    assert all(item["question_id"] != deleted_id for item in page["items"])


# --- 改名 / 歧义 ---


def test_rename_requires_resolution(auth_client: TestClient) -> None:
    """验收标准 7：题目改名不能被系统静默当作删除加新增。"""
    bank_id = _create_bank(auth_client)
    _import_base(auth_client, bank_id)

    renamed = BASE_DOC.replace(
        "## 说说java中HashMap的原理", "## 说说java中HashMap的实现原理"
    )
    body = _upload(auth_client, bank_id, renamed)

    item = _item(body, "说说java中HashMap的实现原理")
    assert item["action"] == "ambiguous"
    assert item["candidates"], "改名必须给出候选旧题"
    assert item["matched_question_id"] is None

    response = _confirm(auth_client, body["preview_id"])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IMPORT_CONFIRMATION_REQUIRED"


def test_rename_resolved_as_match_existing(auth_client: TestClient) -> None:
    bank_id = _create_bank(auth_client)
    _import_base(auth_client, bank_id)
    original_id = _question_id(auth_client, bank_id, "说说java中HashMap的原理")

    renamed = BASE_DOC.replace(
        "## 说说java中HashMap的原理", "## 说说java中HashMap的实现原理"
    )
    body = _upload(auth_client, bank_id, renamed)
    item = _item(body, "说说java中HashMap的实现原理")
    candidate_id = item["candidates"][0]["question_id"]
    assert candidate_id == original_id

    response = _confirm(
        auth_client,
        body["preview_id"],
        accepted_preview_item_ids=_all_question_ids(body),
        resolved_ambiguities=[
            {
                "preview_item_id": item["preview_item_id"],
                "decision": "match_existing",
                "question_id": candidate_id,
            }
        ],
    )
    assert response.status_code == 201, response.text

    # 身份保持不变，只是标题更新
    assert _question_id(auth_client, bank_id, "说说java中HashMap的实现原理") == original_id
    page = auth_client.get(
        f"/api/v1/banks/{bank_id}/questions", params={"page_size": 200}
    ).json()
    assert page["total"] == 3


def test_rename_resolved_as_new_question(auth_client: TestClient) -> None:
    bank_id = _create_bank(auth_client)
    _import_base(auth_client, bank_id)
    original_id = _question_id(auth_client, bank_id, "说说java中HashMap的原理")

    renamed = BASE_DOC.replace(
        "## 说说java中HashMap的原理", "## 说说java中HashMap的实现原理"
    )
    body = _upload(auth_client, bank_id, renamed)
    item = _item(body, "说说java中HashMap的实现原理")
    old_item = body["deleted_items"][0]

    response = _confirm(
        auth_client,
        body["preview_id"],
        accepted_preview_item_ids=_all_question_ids(body),
        resolved_ambiguities=[
            {"preview_item_id": item["preview_item_id"], "decision": "create_new"}
        ],
        confirmed_deleted_question_ids=[old_item["question_id"]],
    )
    assert response.status_code == 201, response.text

    page = auth_client.get(
        f"/api/v1/banks/{bank_id}/questions", params={"page_size": 200}
    ).json()
    assert page["total"] == 3
    new_id = _question_id(auth_client, bank_id, "说说java中HashMap的实现原理")
    assert new_id != original_id


def test_rename_resolved_as_keep_existing(auth_client: TestClient) -> None:
    """docs/04 6.3：保留旧题并忽略新内容。"""
    bank_id = _create_bank(auth_client)
    _import_base(auth_client, bank_id)

    renamed = BASE_DOC.replace(
        "## 说说java中HashMap的原理\n\nHashMap 基于数组 + 链表 + 红黑树。",
        "## 说说java中HashMap的实现原理\n\n完全不同的新内容。",
    )
    body = _upload(auth_client, bank_id, renamed)
    item = _item(body, "说说java中HashMap的实现原理")
    candidate_id = item["candidates"][0]["question_id"]

    response = _confirm(
        auth_client,
        body["preview_id"],
        accepted_preview_item_ids=_all_question_ids(body),
        resolved_ambiguities=[
            {
                "preview_item_id": item["preview_item_id"],
                "decision": "keep_existing",
                "question_id": candidate_id,
            }
        ],
    )
    assert response.status_code == 201, response.text

    page = auth_client.get(
        f"/api/v1/banks/{bank_id}/questions", params={"page_size": 200}
    ).json()
    titles = [entry["title"] for entry in page["items"]]
    assert "说说java中HashMap的原理" in titles
    assert "说说java中HashMap的实现原理" not in titles
    assert page["total"] == 3


# --- 待确认项必须处理 ---


def test_needs_review_item_requires_decision(auth_client: TestClient) -> None:
    bank_id = _create_bank(auth_client)
    doc = "# 顶层\n\n## JVM 内存结构\n\n堆、栈、方法区\n"
    body = _upload(auth_client, bank_id, doc)
    item = _item(body, "JVM 内存结构")
    assert item["classification"] == "needs_review"

    response = _confirm(
        auth_client, body["preview_id"], accepted_preview_item_ids=[item["preview_item_id"]]
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IMPORT_CONFIRMATION_REQUIRED"

    # 用户确认为题目后即可导入
    auth_client.patch(
        f"/api/v1/imports/{body['preview_id']}/items/{item['preview_item_id']}",
        json={"classification": "question"},
    )
    response = _confirm(
        auth_client, body["preview_id"], accepted_preview_item_ids=[item["preview_item_id"]]
    )
    assert response.status_code == 201, response.text
    assert response.json()["changes"]["added"] == 1


def test_excluded_needs_review_item_is_skipped(auth_client: TestClient) -> None:
    """不把低置信标题放进 accepted 列表，等于明确放弃它。"""
    bank_id = _create_bank(auth_client)
    doc = "# 顶层\n\n## JVM 内存结构\n\n堆、栈、方法区\n"
    body = _upload(auth_client, bank_id, doc)
    section_item = _item(body, "顶层")
    assert section_item["classification"] == "section"

    response = _confirm(
        auth_client,
        body["preview_id"],
        accepted_preview_item_ids=[section_item["preview_item_id"]],
    )
    assert response.status_code == 201
    assert response.json()["changes"]["added"] == 0


def test_accepted_ids_limit_the_import(auth_client: TestClient) -> None:
    bank_id = _create_bank(auth_client)
    body = _upload(auth_client, bank_id, BASE_DOC)
    only = _item(body, "redis通常应用在哪些场景")

    response = _confirm(
        auth_client, body["preview_id"], accepted_preview_item_ids=[only["preview_item_id"]]
    )
    assert response.status_code == 201
    assert response.json()["changes"]["added"] == 1
    assert auth_client.get(f"/api/v1/banks/{bank_id}").json()["question_count"] == 1


# --- 版本与轮次关系 ---


def test_old_round_keeps_using_old_version(auth_client: TestClient) -> None:
    """docs/04 第 7 节：轮次 R1 创建于 V1，题库更新到 V2 后 R1 仍读 V1。"""
    from app.db.models import QuestionRevision, Round, RoundItem
    from app.db.session import get_session_factory

    bank_id = _create_bank(auth_client)
    _import_base(auth_client, bank_id)

    # 直接建一个引用 V1 的轮次，模拟「更新发生在轮次进行中」
    with get_session_factory()() as session:
        version = session.query(QuestionRevision).all()
        from app.db.models import BankVersion, QuestionBank, Round as RoundModel

        bank = session.get(QuestionBank, bank_id)
        v1 = session.get(BankVersion, bank.current_version_id)
        round_obj = RoundModel(
            bank_id=bank_id, bank_version_id=v1.id, round_number=1, status="in_progress"
        )
        session.add(round_obj)
        session.flush()
        revision_ids = [r.id for r in version if r.bank_version_id == v1.id]
        for position, revision_id in enumerate(revision_ids):
            session.add(
                RoundItem(round_id=round_obj.id, question_revision_id=revision_id, position=position)
            )
        session.commit()
        round_id = round_obj.id
        v1_id = v1.id

    body = _upload(auth_client, bank_id, BASE_DOC.replace("红黑树", "红黑树 + 链表"))
    assert _confirm(auth_client, body["preview_id"]).status_code == 201

    with get_session_factory()() as session:
        round_obj = session.get(Round, round_id)
        assert round_obj.bank_version_id == v1_id
        items = session.query(RoundItem).filter_by(round_id=round_id).all()
        assert len(items) == 3
        for item in items:
            revision = session.get(QuestionRevision, item.question_revision_id)
            assert revision.bank_version_id == v1_id


def test_import_failure_does_not_change_current_version(auth_client: TestClient) -> None:
    """NFR-002：确认失败时旧版本继续可用。"""
    bank_id = _create_bank(auth_client)
    _import_base(auth_client, bank_id)

    renamed = BASE_DOC.replace(
        "## 说说java中HashMap的原理", "## 说说java中HashMap的实现原理"
    )
    body = _upload(auth_client, bank_id, renamed)
    assert _confirm(auth_client, body["preview_id"]).status_code == 409

    detail = auth_client.get(f"/api/v1/banks/{bank_id}").json()
    assert detail["current_version"] == 1
    assert detail["question_count"] == 3


def test_cannot_confirm_other_users_preview(client: TestClient, auth_client) -> None:
    from app.common.security import hash_password
    from app.db.models import User
    from app.db.session import get_session_factory

    bank_id = _create_bank(auth_client)
    body = _upload(auth_client, bank_id, BASE_DOC)

    with get_session_factory()() as session:
        session.add(User(username="intruder", password_hash=hash_password("pw123456")))
        session.commit()

    client.post("/api/v1/auth/login", json={"username": "intruder", "password": "pw123456"})
    assert _confirm(client, body["preview_id"]).status_code == 404


# --- 回归：静默丢数据 / 静默删除 ---


def test_stale_preview_is_rejected_instead_of_dropping_new_questions(
    auth_client: TestClient,
) -> None:
    """回归：基于旧版本的预览曾经可以确认，把中间那次导入新增的题静默丢掉。

    预览里的 diff 是相对「生成预览时的 current_version」算的。中间又导入过一次之后，
    这份 diff 已经对不上题库现状，直接确认会用旧内容覆盖新版本。
    """
    bank_id = _create_bank(auth_client)
    _import_base(auth_client, bank_id)

    stale = _upload(auth_client, bank_id, BASE_DOC)
    newer = _upload(
        auth_client,
        bank_id,
        BASE_DOC + "\n## JVM 内存结构介绍\n\n堆、栈、方法区。\n",
    )
    assert _confirm(auth_client, newer["preview_id"]).status_code == 201

    response = _confirm(auth_client, stale["preview_id"])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IMPORT_PREVIEW_EXPIRED"

    page = auth_client.get(
        f"/api/v1/banks/{bank_id}/questions", params={"page_size": 100}
    ).json()
    assert page["total"] == 4


def test_excluding_an_existing_question_requires_delete_confirmation(
    auth_client: TestClient,
) -> None:
    """回归：不勾选一道已存在的题，曾经等于静默把它删掉。

    排除是一等公民的操作，和「文档里消失的题」一样属于删除，必须显式确认。
    """
    bank_id = _create_bank(auth_client)
    first = _upload(auth_client, bank_id, BASE_DOC)
    assert _confirm(auth_client, first["preview_id"]).status_code == 201

    second = _upload(auth_client, bank_id, BASE_DOC)
    kept = _item(second, "redis通常应用在哪些场景")["preview_item_id"]

    response = _confirm(auth_client, second["preview_id"], accepted_preview_item_ids=[kept])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IMPORT_CONFIRMATION_REQUIRED"

    # 明确确认删除之后才允许提交，且题目数确实减少
    page = auth_client.get(
        f"/api/v1/banks/{bank_id}/questions", params={"page_size": 100}
    ).json()
    others = [item["question_id"] for item in page["items"] if "redis" not in item["title"]]
    assert len(others) == 2

    response = _confirm(
        auth_client,
        second["preview_id"],
        accepted_preview_item_ids=[kept],
        confirmed_deleted_question_ids=others,
    )
    assert response.status_code == 201, response.text
    assert auth_client.get(f"/api/v1/banks/{bank_id}").json()["question_count"] == 1


# --- 回归：人工修正分类后答案边界必须重算 ---


def test_reclassifying_child_as_section_merges_body_into_parent(
    auth_client: TestClient,
) -> None:
    """回归：把子标题标为「分类」后父题边界不重算，正文在确认后丢失。

    FR-005 要求用户能修正题目边界。既然修正了，答案就必须跟着重算，
    否则「预览里看到的」和「落库的」不一致。
    """
    bank_id = _create_bank(auth_client)
    doc = (
        "## HashMap 的原理是什么？\n\n父题第一段。\n\n"
        "### 为什么使用红黑树？\n\n子章节重要正文。\n\n"
        "## Redis 的作用是什么？\n\n缓存。\n"
    )
    body = _upload(auth_client, bank_id, doc)
    child = _item(body, "为什么使用红黑树？")
    parent = _item(body, "HashMap 的原理是什么？")
    assert "子章节重要正文" not in parent["answer_markdown"]

    response = auth_client.patch(
        f"/api/v1/imports/{body['preview_id']}/items/{child['preview_item_id']}",
        json={"classification": "section"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    # 被 patch 的条目字段仍然在顶层，兼容既有调用方
    assert payload["classification"] == "section"
    assert payload["action"] == "ignored"

    # 受联动的父题必须一起返回，前端才能同步
    affected = {item["preview_item_id"]: item for item in payload["affected_items"]}
    assert parent["preview_item_id"] in affected
    assert "子章节重要正文" in affected[parent["preview_item_id"]]["answer_markdown"]

    assert _confirm(auth_client, body["preview_id"]).status_code == 201
    page = auth_client.get(
        f"/api/v1/banks/{bank_id}/questions", params={"page_size": 100}
    ).json()
    stored = next(item for item in page["items"] if "HashMap" in item["title"])
    assert "子章节重要正文" in stored["answer_summary"]


def test_manual_answer_edit_survives_later_classification_change(
    auth_client: TestClient,
) -> None:
    """手工改过的答案不能被后续的边界重算覆盖。"""
    bank_id = _create_bank(auth_client)
    doc = (
        "## HashMap 的原理是什么？\n\n原始答案。\n\n"
        "### 为什么使用红黑树？\n\n子章节正文。\n\n"
        "## Redis 的作用是什么？\n\n缓存。\n"
    )
    body = _upload(auth_client, bank_id, doc)
    parent = _item(body, "HashMap 的原理是什么？")
    child = _item(body, "为什么使用红黑树？")

    auth_client.patch(
        f"/api/v1/imports/{body['preview_id']}/items/{parent['preview_item_id']}",
        json={"answer_markdown": "我手写的答案。"},
    )
    response = auth_client.patch(
        f"/api/v1/imports/{body['preview_id']}/items/{child['preview_item_id']}",
        json={"classification": "section"},
    )
    assert response.status_code == 200

    assert _confirm(auth_client, body["preview_id"]).status_code == 201
    page = auth_client.get(
        f"/api/v1/banks/{bank_id}/questions", params={"page_size": 100}
    ).json()
    stored = next(item for item in page["items"] if "HashMap" in item["title"])
    assert "我手写的答案" in stored["answer_summary"]

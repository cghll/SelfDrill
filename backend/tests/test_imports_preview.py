"""阶段 3：导入预览接口测试。"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

SAMPLE_MD = """\
# Java 面试复习

## 1.说说java中HashMap的原理

HashMap 基于数组 + 链表 + 红黑树。

```java
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

#### 常见同步方式

| 方式 | 说明 |
| --- | --- |
| synchronized | 关键字 |

![示意图](https://example.com/a.png)
"""

EXPECTED_CANDIDATE_COUNT = 5


def _create_bank(client: TestClient, name: str = "Java 热门面试") -> str:
    response = client.post("/api/v1/banks", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _upload(client: TestClient, bank_id: str, content: str | bytes, filename: str = "java.md"):
    data = content.encode("utf-8") if isinstance(content, str) else content
    return client.post(
        f"/api/v1/banks/{bank_id}/imports/preview",
        files={"file": (filename, io.BytesIO(data), "text/markdown")},
    )


def test_preview_requires_login(client: TestClient) -> None:
    response = client.post(
        "/api/v1/banks/some-bank/imports/preview",
        files={"file": ("a.md", io.BytesIO(b"# x"), "text/markdown")},
    )
    assert response.status_code == 401


def test_preview_recognises_questions(auth_client: TestClient) -> None:
    bank_id = _create_bank(auth_client)
    response = _upload(auth_client, bank_id, SAMPLE_MD)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["mode"] == "create"
    assert body["source_filename"] == "java.md"
    assert len(body["source_hash"]) == 64
    assert body["summary"]["total_candidates"] == EXPECTED_CANDIDATE_COUNT

    titles = [item["title"] for item in body["items"] if item["classification"] != "section"]
    assert "说说java中HashMap的原理" in titles
    assert "redis通常应用在哪些场景" in titles
    assert "追问：为什么 Redis 用单线程还这么快？" in titles
    assert "redis篇" not in titles
    assert "面试官追问" not in titles


def test_preview_marks_all_items_added_on_first_import(auth_client: TestClient) -> None:
    bank_id = _create_bank(auth_client)
    body = _upload(auth_client, bank_id, SAMPLE_MD).json()
    assert body["diff"]["added"] == EXPECTED_CANDIDATE_COUNT
    assert body["diff"]["modified"] == 0
    assert body["deleted_items"] == []
    candidates = [item for item in body["items"] if item["classification"] != "section"]
    assert all(item["action"] == "added" for item in candidates)


def test_preview_reports_content_flags(auth_client: TestClient) -> None:
    """FR-005：预览要说明代码块、图片、列表、表格是否被保留。"""
    bank_id = _create_bank(auth_client)
    body = _upload(auth_client, bank_id, SAMPLE_MD).json()
    by_title = {item["title"]: item for item in body["items"]}

    parent = by_title["说说java中HashMap的原理"]
    assert parent["content_flags"]["code_block"] is True

    reflect = by_title["反射所能够提供的功能有哪些？"]
    assert reflect["content_flags"]["list"] is True
    assert reflect["content_flags"]["table"] is True
    assert reflect["content_flags"]["image"] is True


def test_preview_includes_source_anchors(auth_client: TestClient) -> None:
    bank_id = _create_bank(auth_client)
    body = _upload(auth_client, bank_id, SAMPLE_MD).json()
    parent = next(i for i in body["items"] if i["title"] == "说说java中HashMap的原理")
    assert parent["source_anchor"]["start_line"] == 3
    assert parent["source_anchor"]["end_line"] > parent["source_anchor"]["start_line"]


def test_preview_includes_section_paths(auth_client: TestClient) -> None:
    bank_id = _create_bank(auth_client)
    body = _upload(auth_client, bank_id, SAMPLE_MD).json()
    redis = next(i for i in body["items"] if i["title"] == "redis通常应用在哪些场景")
    assert redis["section_path"] == ["Java 面试复习", "redis篇"]


def test_preview_does_not_modify_bank(auth_client: TestClient) -> None:
    """预览阶段不能写题库数据（导入失败不得影响当前版本）。"""
    bank_id = _create_bank(auth_client)
    _upload(auth_client, bank_id, SAMPLE_MD)
    detail = auth_client.get(f"/api/v1/banks/{bank_id}").json()
    assert detail["question_count"] == 0
    assert detail["current_version"] is None
    assert auth_client.get(f"/api/v1/banks/{bank_id}/versions").json() == []


def test_preview_rejects_non_markdown_extension(auth_client: TestClient) -> None:
    bank_id = _create_bank(auth_client)
    response = _upload(auth_client, bank_id, SAMPLE_MD, filename="java.pdf")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_preview_rejects_unsupported_content_type(auth_client: TestClient) -> None:
    bank_id = _create_bank(auth_client)
    response = auth_client.post(
        f"/api/v1/banks/{bank_id}/imports/preview",
        files={"file": ("java.md", io.BytesIO(b"# x"), "application/pdf")},
    )
    assert response.status_code == 415


def test_preview_rejects_oversized_file(auth_client: TestClient) -> None:
    from app.config import get_settings

    settings = get_settings()
    original = settings.max_upload_size
    settings.max_upload_size = 32
    try:
        bank_id = _create_bank(auth_client)
        response = _upload(auth_client, bank_id, SAMPLE_MD)
    finally:
        settings.max_upload_size = original

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_preview_rejects_non_utf8_file(auth_client: TestClient) -> None:
    bank_id = _create_bank(auth_client)
    response = _upload(auth_client, bank_id, b"# \xff\xfe\x00 invalid")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MARKDOWN_PARSE_FAILED"


def test_preview_accepts_utf8_bom(auth_client: TestClient) -> None:
    bank_id = _create_bank(auth_client)
    response = _upload(auth_client, bank_id, "\ufeff" + SAMPLE_MD)
    assert response.status_code == 201
    titles = [item["title"] for item in response.json()["items"]]
    assert "说说java中HashMap的原理" in titles


def test_preview_stores_source_file_by_hash(auth_client: TestClient) -> None:
    from app.config import get_settings

    bank_id = _create_bank(auth_client)
    body = _upload(auth_client, bank_id, SAMPLE_MD).json()
    stored = get_settings().upload_path / f"{body['source_hash']}.md"
    assert stored.exists()
    assert stored.read_text(encoding="utf-8") == SAMPLE_MD


def test_preview_for_other_users_bank_is_not_found(client: TestClient, auth_client) -> None:
    from app.common.security import hash_password
    from app.db.models import User
    from app.db.session import get_session_factory

    bank_id = _create_bank(auth_client)
    with get_session_factory()() as session:
        session.add(User(username="intruder", password_hash=hash_password("pw123456")))
        session.commit()

    client.post("/api/v1/auth/login", json={"username": "intruder", "password": "pw123456"})
    assert _upload(client, bank_id, SAMPLE_MD).status_code == 404


# --- PATCH 预览项 ---


def test_patch_preview_item_title(auth_client: TestClient) -> None:
    bank_id = _create_bank(auth_client)
    body = _upload(auth_client, bank_id, SAMPLE_MD).json()
    item = next(i for i in body["items"] if i["title"] == "redis通常应用在哪些场景")

    response = auth_client.patch(
        f"/api/v1/imports/{body['preview_id']}/items/{item['preview_item_id']}",
        json={"title": "Redis 通常应用在哪些场景？"},
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Redis 通常应用在哪些场景？"


def test_patch_preview_item_to_section(auth_client: TestClient) -> None:
    bank_id = _create_bank(auth_client)
    body = _upload(auth_client, bank_id, SAMPLE_MD).json()
    item = next(i for i in body["items"] if i["title"] == "redis通常应用在哪些场景")

    response = auth_client.patch(
        f"/api/v1/imports/{body['preview_id']}/items/{item['preview_item_id']}",
        json={"classification": "section"},
    )
    assert response.status_code == 200
    assert response.json()["classification"] == "section"
    assert response.json()["action"] == "ignored"


def test_patch_promotes_section_to_question(auth_client: TestClient) -> None:
    """FR-005：用户可以把标题标记为题目（例如答案内小标题）。"""
    bank_id = _create_bank(auth_client)
    body = _upload(auth_client, bank_id, SAMPLE_MD).json()
    item = next(i for i in body["items"] if i["title"] == "常见同步方式")

    response = auth_client.patch(
        f"/api/v1/imports/{body['preview_id']}/items/{item['preview_item_id']}",
        json={"classification": "question"},
    )
    assert response.status_code == 200
    assert response.json()["action"] == "added"


def test_patch_preview_item_answer(auth_client: TestClient) -> None:
    bank_id = _create_bank(auth_client)
    body = _upload(auth_client, bank_id, SAMPLE_MD).json()
    item = next(i for i in body["items"] if i["title"] == "说说java中HashMap的原理")

    response = auth_client.patch(
        f"/api/v1/imports/{body['preview_id']}/items/{item['preview_item_id']}",
        json={"answer_markdown": "只有这一段是答案。"},
    )
    assert response.status_code == 200
    assert response.json()["answer_markdown"] == "只有这一段是答案。"
    assert response.json()["answer_summary"] == "只有这一段是答案。"


def test_patch_rejects_blank_title(auth_client: TestClient) -> None:
    bank_id = _create_bank(auth_client)
    body = _upload(auth_client, bank_id, SAMPLE_MD).json()
    item = body["items"][0]
    response = auth_client.patch(
        f"/api/v1/imports/{body['preview_id']}/items/{item['preview_item_id']}",
        json={"title": "   "},
    )
    assert response.status_code == 400


def test_patch_unknown_item_returns_404(auth_client: TestClient) -> None:
    bank_id = _create_bank(auth_client)
    body = _upload(auth_client, bank_id, SAMPLE_MD).json()
    response = auth_client.patch(
        f"/api/v1/imports/{body['preview_id']}/items/node-999",
        json={"title": "x"},
    )
    assert response.status_code == 404


def test_patch_unknown_preview_returns_404(auth_client: TestClient) -> None:
    response = auth_client.patch(
        "/api/v1/imports/00000000-0000-0000-0000-000000000000/items/node-001",
        json={"title": "x"},
    )
    assert response.status_code == 404


def test_expired_preview_returns_conflict(auth_client: TestClient) -> None:
    from app.common.timeutil import utcnow
    from app.db.models import ImportPreview
    from app.db.session import get_session_factory

    bank_id = _create_bank(auth_client)
    body = _upload(auth_client, bank_id, SAMPLE_MD).json()

    with get_session_factory()() as session:
        preview = session.get(ImportPreview, body["preview_id"])
        preview.expires_at = utcnow().replace(year=2020)
        session.commit()

    response = auth_client.patch(
        f"/api/v1/imports/{body['preview_id']}/items/node-001", json={"title": "x"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IMPORT_PREVIEW_EXPIRED"


@pytest.mark.parametrize("filename", ["a.md", "a.MD", "a.markdown"])
def test_accepted_filenames(auth_client: TestClient, filename: str) -> None:
    bank_id = _create_bank(auth_client)
    assert _upload(auth_client, bank_id, SAMPLE_MD, filename=filename).status_code == 201

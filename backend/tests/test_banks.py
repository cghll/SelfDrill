"""阶段 2：题库与题库版本接口测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.common.text import summarize_markdown as summarize_answer


def _create_bank(client: TestClient, name: str = "Java 热门面试") -> dict:
    response = client.post(
        "/api/v1/banks", json={"name": name, "description": "Java、Redis、并发"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_banks_require_login(client: TestClient) -> None:
    assert client.get("/api/v1/banks").status_code == 401
    assert client.post("/api/v1/banks", json={"name": "x"}).status_code == 401


def test_create_and_list_banks(auth_client: TestClient) -> None:
    created = _create_bank(auth_client)
    assert created["name"] == "Java 热门面试"
    assert created["question_count"] == 0
    assert created["current_version"] is None
    assert created["current_version_id"] is None
    assert created["active_round"] is None
    assert created["created_at"].endswith("Z")

    listed = auth_client.get("/api/v1/banks").json()
    assert [bank["id"] for bank in listed] == [created["id"]]


def test_bank_name_cannot_be_blank(auth_client: TestClient) -> None:
    assert auth_client.post("/api/v1/banks", json={"name": "   "}).status_code == 400
    assert auth_client.post("/api/v1/banks", json={"name": ""}).status_code == 400


def test_get_bank_detail(auth_client: TestClient) -> None:
    created = _create_bank(auth_client)
    response = auth_client.get(f"/api/v1/banks/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_unknown_bank_returns_404(auth_client: TestClient) -> None:
    response = auth_client.get("/api/v1/banks/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_delete_bank(auth_client: TestClient) -> None:
    created = _create_bank(auth_client)
    assert auth_client.delete(f"/api/v1/banks/{created['id']}").status_code == 204
    assert auth_client.get(f"/api/v1/banks/{created['id']}").status_code == 404
    assert auth_client.get("/api/v1/banks").json() == []


def test_versions_empty_for_new_bank(auth_client: TestClient) -> None:
    created = _create_bank(auth_client)
    assert auth_client.get(f"/api/v1/banks/{created['id']}/versions").json() == []


def test_questions_empty_for_new_bank(auth_client: TestClient) -> None:
    created = _create_bank(auth_client)
    page = auth_client.get(f"/api/v1/banks/{created['id']}/questions").json()
    assert page == {"items": [], "page": 1, "page_size": 50, "total": 0, "total_pages": 0}


def test_questions_rejects_bad_pagination(auth_client: TestClient) -> None:
    created = _create_bank(auth_client)
    url = f"/api/v1/banks/{created['id']}/questions"
    assert auth_client.get(url, params={"page": 0}).status_code == 400
    assert auth_client.get(url, params={"page_size": 0}).status_code == 400
    assert auth_client.get(url, params={"page_size": 500}).status_code == 400


def test_questions_unknown_version_returns_404(auth_client: TestClient) -> None:
    created = _create_bank(auth_client)
    response = auth_client.get(
        f"/api/v1/banks/{created['id']}/questions",
        params={"version_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert response.status_code == 404


def test_cannot_access_other_users_bank(client: TestClient, db_session_factory) -> None:
    """资源归属必须校验：另一个用户不能读写该题库。"""
    from app.common.security import hash_password
    from app.db.models import QuestionBank, User

    with db_session_factory() as session:
        owner = session.query(User).filter_by(username="owner").one()
        other = User(username="intruder", password_hash=hash_password("other-password"))
        session.add(other)
        session.flush()
        bank = QuestionBank(user_id=owner.id, name="私有题库")
        session.add(bank)
        session.commit()
        bank_id = bank.id

    client.post(
        "/api/v1/auth/login", json={"username": "intruder", "password": "other-password"}
    )
    assert client.get(f"/api/v1/banks/{bank_id}").status_code == 404
    assert client.delete(f"/api/v1/banks/{bank_id}").status_code == 404
    assert client.get(f"/api/v1/banks/{bank_id}/versions").status_code == 404
    assert client.get("/api/v1/banks").json() == []


def test_summarize_answer_strips_markdown() -> None:
    answer = (
        "## 标题\n\n"
        "```java\nint a = 1;\n```\n\n"
        "- 列表项\n"
        "1. 有序项\n\n"
        "> 引用\n\n"
        "**加粗** 与 [链接](https://example.com) 和 ![图](https://example.com/a.png)\n"
    )
    summary = summarize_answer(answer)
    assert "```" not in summary
    assert "##" not in summary
    assert "**" not in summary
    assert "https://example.com/a.png" not in summary
    assert "加粗" in summary and "链接" in summary


def test_summarize_answer_truncates() -> None:
    summary = summarize_answer("字" * 500, limit=20)
    assert len(summary) == 20
    assert summary.endswith("…")


def test_summarize_answer_flattens_tables() -> None:
    """回归：摘要里曾经出现 `| 问题 | 原因 | | --- | --- |` 这种原始表格语法。

    答案里带表格的题目很多，列表页的摘要必须把它压成可读的一行。
    """
    answer = (
        "| 问题 | 原因 | 解决方案 |\n"
        "| --- | --- | --- |\n"
        "| 穿透 | 查询不存在的数据 | 布隆过滤器 |\n"
        "| 击穿 | 热点 key 过期 | 互斥锁 |\n"
    )
    summary = summarize_answer(answer)
    assert "|" not in summary
    assert "---" not in summary
    assert "穿透" in summary
    assert "布隆过滤器" in summary


def test_summarize_answer_flattened_table_still_truncates() -> None:
    rows = "\n".join(f"| 项{i} | 说明{i} |" for i in range(60))
    summary = summarize_answer(f"| 名称 | 描述 |\n| --- | --- |\n{rows}\n", limit=40)
    assert len(summary) == 40
    assert "|" not in summary


def test_version_summary_reports_question_count(auth_client: TestClient, db_session_factory) -> None:
    """题库摘要中的 question_count 来自当前生效版本。"""
    from app.db.models import BankVersion, QuestionBank

    created = _create_bank(auth_client)
    with db_session_factory() as session:
        bank = session.get(QuestionBank, created["id"])
        version = BankVersion(
            bank_id=bank.id,
            version_number=1,
            source_filename="sample.md",
            source_hash="hash",
            question_count=7,
        )
        session.add(version)
        session.flush()
        bank.current_version_id = version.id
        session.commit()

    summary = auth_client.get(f"/api/v1/banks/{created['id']}").json()
    assert summary["question_count"] == 7
    assert summary["current_version"] == 1

    versions = auth_client.get(f"/api/v1/banks/{created['id']}/versions").json()
    assert len(versions) == 1
    assert versions[0]["source_filename"] == "sample.md"
    assert versions[0]["status"] == "active"

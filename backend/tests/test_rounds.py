"""阶段 5：轮次生成、推进与并发校验测试。"""

from __future__ import annotations

import io

from fastapi.testclient import TestClient

DOC = """\
# Java 面试复习

## HashMap 的原理是什么？

数组 + 链表 + 红黑树。

## redis通常应用在哪些场景

缓存、分布式锁。

## 反射所能够提供的功能有哪些？

- 获取 Class 对象

## synchronized 和 ReentrantLock 的区别

锁的粒度不同。

## JVM 内存模型介绍

堆、栈、方法区。
"""

QUESTION_COUNT = 5

# 每道题在 DOC 里对应的答案原文，用于按「当前题」校验 reveal 返回的正文
ANSWERS = {
    "HashMap 的原理是什么？": "数组 + 链表 + 红黑树。",
    "redis通常应用在哪些场景": "缓存、分布式锁。",
    "反射所能够提供的功能有哪些？": "- 获取 Class 对象",
    "synchronized 和 ReentrantLock 的区别": "锁的粒度不同。",
    "JVM 内存模型介绍": "堆、栈、方法区。",
}


def _setup_bank(client: TestClient, name: str = "Java 热门面试") -> str:
    """建库 + 导入 + 确认，返回 bank_id。"""
    bank_id = client.post("/api/v1/banks", json={"name": name}).json()["id"]
    preview = client.post(
        f"/api/v1/banks/{bank_id}/imports/preview",
        files={"file": ("java.md", io.BytesIO(DOC.encode("utf-8")), "text/markdown")},
    ).json()
    response = client.post(f"/api/v1/imports/{preview['preview_id']}/confirm", json={})
    assert response.status_code == 201, response.text
    assert response.json()["changes"]["added"] == QUESTION_COUNT
    return bank_id


def _start(client: TestClient, bank_id: str, **payload):
    body = {"restart": False}
    body.update(payload)
    return client.post(f"/api/v1/banks/{bank_id}/rounds", json=body)


# --- 生成 ---


def test_start_round_creates_full_sequence(auth_client: TestClient) -> None:
    bank_id = _setup_bank(auth_client)
    response = _start(auth_client, bank_id)
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["status"] == "in_progress"
    assert body["round_number"] == 1
    assert body["current_index"] == 0
    assert body["total_count"] == QUESTION_COUNT
    assert body["progress_version"] == 1
    assert body["current_item"]["position"] == 0
    assert body["current_item"]["answer"] is None
    assert body["current_item"]["answer_revealed"] is False


def test_round_contains_each_question_exactly_once(auth_client: TestClient) -> None:
    """验收标准 8：一轮中每个题目只出现一次。"""
    from app.db.models import RoundItem
    from app.db.session import get_session_factory

    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]

    with get_session_factory()() as session:
        items = session.query(RoundItem).filter_by(round_id=round_id).all()
        revision_ids = [item.question_revision_id for item in items]
        positions = [item.position for item in items]

    assert len(revision_ids) == QUESTION_COUNT
    assert len(set(revision_ids)) == QUESTION_COUNT
    assert sorted(positions) == list(range(QUESTION_COUNT))


def test_round_order_is_randomised(auth_client: TestClient) -> None:
    """两个轮次的顺序不应完全相同（5 道题，完全相同概率 1/120）。"""
    from app.db.models import Round, RoundItem
    from app.db.session import get_session_factory

    bank_id = _setup_bank(auth_client)
    orders = []
    for _ in range(6):
        round_id = _start(auth_client, bank_id, restart=True).json()["id"]
        with get_session_factory()() as session:
            items = (
                session.query(RoundItem)
                .filter_by(round_id=round_id)
                .order_by(RoundItem.position)
                .all()
            )
            orders.append(tuple(item.question_revision_id for item in items))

    assert len(set(orders)) > 1


def test_restarting_does_not_change_question_set(auth_client: TestClient) -> None:
    """顺序随机，但集合必须完全一致。"""
    from app.db.models import RoundItem
    from app.db.session import get_session_factory

    bank_id = _setup_bank(auth_client)
    sets = []
    for _ in range(4):
        round_id = _start(auth_client, bank_id, restart=True).json()["id"]
        with get_session_factory()() as session:
            items = session.query(RoundItem).filter_by(round_id=round_id).all()
            sets.append({item.question_revision_id for item in items})

    assert all(item == sets[0] for item in sets)


def test_start_round_reuses_active_round(auth_client: TestClient) -> None:
    bank_id = _setup_bank(auth_client)
    first = _start(auth_client, bank_id).json()

    response = _start(auth_client, bank_id)
    assert response.status_code == 200
    assert response.json()["id"] == first["id"]

    history = auth_client.get(f"/api/v1/banks/{bank_id}/rounds").json()
    assert len(history) == 1


def test_restart_abandons_previous_round(auth_client: TestClient) -> None:
    bank_id = _setup_bank(auth_client)
    first = _start(auth_client, bank_id).json()

    response = _start(auth_client, bank_id, restart=True)
    assert response.status_code == 201
    assert response.json()["id"] != first["id"]
    assert response.json()["round_number"] == 2

    history = {item["round_number"]: item for item in auth_client.get(
        f"/api/v1/banks/{bank_id}/rounds"
    ).json()}
    assert history[1]["status"] == "abandoned"
    assert history[2]["status"] == "in_progress"


def test_start_round_without_version_is_rejected(auth_client: TestClient) -> None:
    bank_id = auth_client.post("/api/v1/banks", json={"name": "空题库"}).json()["id"]
    response = _start(auth_client, bank_id)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_rounds_require_login(client: TestClient) -> None:
    assert client.post("/api/v1/banks/x/rounds", json={"restart": False}).status_code == 401


def test_cannot_start_round_on_other_users_bank(client: TestClient, auth_client: TestClient) -> None:
    from app.common.security import hash_password
    from app.db.models import User
    from app.db.session import get_session_factory

    bank_id = _setup_bank(auth_client)
    with get_session_factory()() as session:
        session.add(User(username="intruder", password_hash=hash_password("pw123456")))
        session.commit()

    client.post("/api/v1/auth/login", json={"username": "intruder", "password": "pw123456"})
    assert _start(client, bank_id).status_code == 404


# --- 答案查看 ---


def test_answer_is_hidden_until_revealed(auth_client: TestClient) -> None:
    """验收标准 10：答案在点击前不可见。"""
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]

    detail = auth_client.get(f"/api/v1/rounds/{round_id}").json()
    assert detail["current_item"]["answer"] is None
    assert detail["current_item"]["answer_revealed"] is False


def test_reveal_returns_answer(auth_client: TestClient) -> None:
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]

    response = auth_client.post(f"/api/v1/rounds/{round_id}/reveal")
    assert response.status_code == 200
    body = response.json()
    assert body["answer_revealed"] is True
    assert body["answer"]


def test_reveal_is_idempotent(auth_client: TestClient) -> None:
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]

    first = auth_client.post(f"/api/v1/rounds/{round_id}/reveal").json()
    second = auth_client.post(f"/api/v1/rounds/{round_id}/reveal").json()
    assert first == second

    detail = auth_client.get(f"/api/v1/rounds/{round_id}").json()
    assert detail["progress_version"] == 1


def test_reveal_does_not_advance(auth_client: TestClient) -> None:
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]
    auth_client.post(f"/api/v1/rounds/{round_id}/reveal")
    assert auth_client.get(f"/api/v1/rounds/{round_id}").json()["current_index"] == 0


def test_reveal_state_survives_reload(auth_client: TestClient) -> None:
    """验收标准 9：刷新/换设备后答案查看状态不丢失。"""
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]
    auth_client.post(f"/api/v1/rounds/{round_id}/reveal")

    detail = auth_client.get(f"/api/v1/rounds/{round_id}").json()
    assert detail["current_item"]["answer_revealed"] is True
    assert detail["current_item"]["answer"] is not None


def test_revealed_answer_carries_markdown(auth_client: TestClient) -> None:
    """reveal 返回的必须是**当前题自己**的答案原文。

    轮次顺序由服务端随机生成，所以这里不能假设第一题是哪一道——
    原实现写死了四个关键词做「或」判断，抽到「反射」那道题时必然失败。
    """
    bank_id = _setup_bank(auth_client)
    detail = _start(auth_client, bank_id).json()
    round_id = detail["id"]
    title = detail["current_item"]["question"]["title"]
    assert title in ANSWERS

    answer = auth_client.post(f"/api/v1/rounds/{round_id}/reveal").json()["answer"]
    assert answer is not None
    assert ANSWERS[title] in answer


# --- 推进 ---


def _advance(client: TestClient, round_id: str, version: int, key: str | None = None):
    payload = {"expected_progress_version": version}
    if key:
        payload["idempotency_key"] = key
    return client.post(f"/api/v1/rounds/{round_id}/advance", json=payload)


def _retreat(client: TestClient, round_id: str, version: int, key: str | None = None):
    """回退到上一题：复用 advance，只把 direction 换成 previous。"""
    payload = {"expected_progress_version": version, "direction": "previous"}
    if key:
        payload["idempotency_key"] = key
    return client.post(f"/api/v1/rounds/{round_id}/advance", json=payload)


def test_advance_moves_to_next_question(auth_client: TestClient) -> None:
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]

    response = _advance(auth_client, round_id, 1)
    assert response.status_code == 200
    body = response.json()
    assert body["current_index"] == 1
    assert body["progress_version"] == 2
    assert body["current_item"]["position"] == 1
    assert body["current_item"]["answer"] is None


def test_advance_through_all_questions_completes_round(auth_client: TestClient) -> None:
    """验收标准 8：最后显示该轮已完成。"""
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]

    version = 1
    seen_positions = []
    for _ in range(QUESTION_COUNT - 1):
        body = _advance(auth_client, round_id, version).json()
        assert body["status"] == "in_progress"
        seen_positions.append(body["current_item"]["position"])
        version = body["progress_version"]

    assert seen_positions == list(range(1, QUESTION_COUNT))

    final = _advance(auth_client, round_id, version).json()
    assert final["status"] == "completed"
    assert final["current_item"] is None
    assert final["completed_at"] is not None
    assert final["progress_version"] == QUESTION_COUNT + 1


def test_advance_after_completion_is_rejected(auth_client: TestClient) -> None:
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]

    version = 1
    for _ in range(QUESTION_COUNT):
        version = _advance(auth_client, round_id, version).json()["progress_version"]

    response = _advance(auth_client, round_id, version)
    assert response.status_code == 400


def test_progress_survives_reload(auth_client: TestClient) -> None:
    """验收标准 9：刷新页面、换设备后当前位置不改变。"""
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]
    _advance(auth_client, round_id, 1)
    _advance(auth_client, round_id, 2)

    detail = auth_client.get(f"/api/v1/rounds/{round_id}").json()
    assert detail["current_index"] == 2
    assert detail["progress_version"] == 3


# --- 上一题 ---


def test_previous_moves_back_one_question(auth_client: TestClient) -> None:
    """回退同样由服务端改写位置，并让进度版本自增。"""
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]
    _advance(auth_client, round_id, 1)
    _advance(auth_client, round_id, 2)

    response = _retreat(auth_client, round_id, 3)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "in_progress"
    assert body["current_index"] == 1
    assert body["progress_version"] == 4
    assert body["current_item"]["position"] == 1

    # 服务端已落库，刷新后仍然停在上一题
    detail = auth_client.get(f"/api/v1/rounds/{round_id}").json()
    assert detail["current_index"] == 1
    assert detail["progress_version"] == 4


def test_previous_then_next_returns_to_same_question(auth_client: TestClient) -> None:
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]
    _advance(auth_client, round_id, 1)

    forward_item = auth_client.get(f"/api/v1/rounds/{round_id}").json()["current_item"]["id"]
    _retreat(auth_client, round_id, 2)
    back_item = _retreat(auth_client, round_id, 3)  # 已在第一题，空操作
    assert back_item.json()["current_item"]["id"] != forward_item

    body = _advance(auth_client, round_id, back_item.json()["progress_version"]).json()
    assert body["current_item"]["id"] == forward_item


def test_previous_at_first_question_is_a_noop(auth_client: TestClient) -> None:
    """第一题没有上一题：不改变状态，也不报错。"""
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]

    response = _retreat(auth_client, round_id, 1)
    assert response.status_code == 200
    body = response.json()
    assert body["current_index"] == 0
    # 没有发生移动，版本号不能自增——否则反复重试会一路推高版本号
    assert body["progress_version"] == 1


def test_previous_uses_optimistic_lock(auth_client: TestClient) -> None:
    """回退不是绕过乐观锁的后门：拿着旧版本号回退必须 409。"""
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]
    _advance(auth_client, round_id, 1)

    response = _retreat(auth_client, round_id, 1)  # 服务端已经是 2
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ROUND_PROGRESS_CONFLICT"

    detail = auth_client.get(f"/api/v1/rounds/{round_id}").json()
    assert detail["current_index"] == 1
    assert detail["progress_version"] == 2


def test_previous_is_idempotent_with_key(auth_client: TestClient) -> None:
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]
    _advance(auth_client, round_id, 1)
    _advance(auth_client, round_id, 2)

    first = _retreat(auth_client, round_id, 3, key="back-1").json()
    second = _retreat(auth_client, round_id, 3, key="back-1").json()

    assert first["current_index"] == second["current_index"] == 1
    assert second["progress_version"] == 4


def test_previous_keeps_revealed_answer(auth_client: TestClient) -> None:
    """回退到已经查看过答案的题：答案直接可见，「已查看」记录不回退。"""
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]
    first_item_id = auth_client.get(f"/api/v1/rounds/{round_id}").json()["current_item"]["id"]
    auth_client.post(f"/api/v1/rounds/{round_id}/reveal")
    _advance(auth_client, round_id, 1)

    body = _retreat(auth_client, round_id, 2).json()
    assert body["current_item"]["id"] == first_item_id
    assert body["current_item"]["answer_revealed"] is True
    assert body["current_item"]["answer"] is not None


def test_previous_after_completion_is_rejected(auth_client: TestClient) -> None:
    """轮次结束后不能再回退，否则 completed 状态会被绕过。"""
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]

    version = 1
    for _ in range(QUESTION_COUNT):
        version = _advance(auth_client, round_id, version).json()["progress_version"]

    response = _retreat(auth_client, round_id, version)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"

    assert auth_client.get(f"/api/v1/rounds/{round_id}").json()["status"] == "completed"


def test_unknown_direction_is_rejected(auth_client: TestClient) -> None:
    """方向取值是封闭集合，非法值不能悄悄当成「下一题」。"""
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]

    response = auth_client.post(
        f"/api/v1/rounds/{round_id}/advance",
        json={"expected_progress_version": 1, "direction": "sideways"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert auth_client.get(f"/api/v1/rounds/{round_id}").json()["current_index"] == 0


def test_direction_defaults_to_next(auth_client: TestClient) -> None:
    """不传 direction 的老客户端行为不变。"""
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]

    body = _advance(auth_client, round_id, 1).json()
    assert body["current_index"] == 1
    assert body["progress_version"] == 2


# --- 并发 ---


def test_stale_progress_version_returns_conflict(auth_client: TestClient) -> None:
    """验收标准 11：两个设备同时推进时至少一个收到冲突提示。"""
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]

    assert _advance(auth_client, round_id, 1).status_code == 200

    # 第二台设备仍拿着旧版本号
    response = _advance(auth_client, round_id, 1)
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "ROUND_PROGRESS_CONFLICT"
    assert body["error"]["details"]["actual_progress_version"] == 2


def test_conflict_does_not_move_pointer(auth_client: TestClient) -> None:
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]
    _advance(auth_client, round_id, 1)
    _advance(auth_client, round_id, 1)

    detail = auth_client.get(f"/api/v1/rounds/{round_id}").json()
    assert detail["current_index"] == 1
    assert detail["progress_version"] == 2


def test_idempotency_key_prevents_double_advance(auth_client: TestClient) -> None:
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]

    first = _advance(auth_client, round_id, 1, key="retry-abc").json()
    second = _advance(auth_client, round_id, 1, key="retry-abc").json()

    assert first["current_index"] == second["current_index"] == 1
    assert second["progress_version"] == 2

    detail = auth_client.get(f"/api/v1/rounds/{round_id}").json()
    assert detail["current_index"] == 1


def test_different_idempotency_keys_advance_normally(auth_client: TestClient) -> None:
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]

    _advance(auth_client, round_id, 1, key="k1")
    body = _advance(auth_client, round_id, 2, key="k2").json()
    assert body["current_index"] == 2


def test_concurrent_advance_rejects_one(
    auth_client: TestClient, db_session_factory, monkeypatch
) -> None:
    """回归：两个请求同时带着同一个 expected_progress_version 推进。

    原实现是「先读版本号比较、再写回」，两个请求都能通过检查，
    然后互相覆盖——服务端只前进一格，丢失一次推进（lost update）。
    把检查与写入合并成一条带条件的 UPDATE 后，必须恰好一个成功、一个 409。
    """
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Lock

    from sqlalchemy import select

    from app.db.models import User
    from app.rounds import repository as round_repo
    from app.rounds import service as rounds
    from app.rounds.schemas import AdvanceRequest

    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]

    barrier = Barrier(2)
    lock = Lock()
    calls = 0
    original = round_repo.count_round_items

    def count(session, rid):
        nonlocal calls
        with lock:
            calls += 1
            position = calls
        if position <= 2:
            barrier.wait(timeout=10)
        return original(session, rid)

    monkeypatch.setattr(round_repo, "count_round_items", count)

    def worker(key: str):
        with db_session_factory() as session:
            user = session.execute(select(User)).scalar_one()
            try:
                result = rounds.advance_round(
                    session,
                    user,
                    round_id,
                    AdvanceRequest(expected_progress_version=1, idempotency_key=key),
                )
                return ("ok", result.progress_version)
            except Exception as exc:  # noqa: BLE001 - 测试需要看到具体异常类型
                return (type(exc).__name__, str(exc))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, ["concurrent-a", "concurrent-b"]))

    assert sum(1 for entry in results if entry[0] == "ok") == 1
    assert sum(1 for entry in results if entry[0] == "RoundProgressConflictError") == 1

    detail = auth_client.get(f"/api/v1/rounds/{round_id}").json()
    assert detail["current_index"] == 1
    assert detail["progress_version"] == 2


# --- 放弃 ---


def test_abandon_round(auth_client: TestClient) -> None:
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]

    response = auth_client.post(f"/api/v1/rounds/{round_id}/abandon")
    assert response.status_code == 200
    assert response.json()["status"] == "abandoned"

    detail = auth_client.get(f"/api/v1/rounds/{round_id}").json()
    assert detail["status"] == "abandoned"
    assert detail["current_item"] is None


def test_abandon_is_idempotent(auth_client: TestClient) -> None:
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]
    first = auth_client.post(f"/api/v1/rounds/{round_id}/abandon").json()
    second = auth_client.post(f"/api/v1/rounds/{round_id}/abandon").json()
    assert first == second


def test_abandoned_round_does_not_count_as_completed(auth_client: TestClient) -> None:
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]
    auth_client.post(f"/api/v1/rounds/{round_id}/abandon")

    history = auth_client.get(f"/api/v1/banks/{bank_id}/rounds").json()
    assert [item["status"] for item in history] == ["abandoned"]

    new_round = _start(auth_client, bank_id)
    assert new_round.status_code == 201
    assert new_round.json()["round_number"] == 2


def test_new_round_after_abandon_uses_latest_version(auth_client: TestClient) -> None:
    """FR-007：开始新轮次时使用最新已确认的题库版本。"""
    from app.db.models import BankVersion, QuestionBank
    from app.db.session import get_session_factory

    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]
    auth_client.post(f"/api/v1/rounds/{round_id}/abandon")

    extended = DOC + "\n## ConcurrentHashMap 如何保证线程安全？\n\n分段锁。\n"
    preview = auth_client.post(
        f"/api/v1/banks/{bank_id}/imports/preview",
        files={"file": ("java2.md", io.BytesIO(extended.encode("utf-8")), "text/markdown")},
    ).json()
    auth_client.post(f"/api/v1/imports/{preview['preview_id']}/confirm", json={})

    new_round = _start(auth_client, bank_id).json()
    assert new_round["total_count"] == QUESTION_COUNT + 1

    with get_session_factory()() as session:
        bank = session.get(QuestionBank, bank_id)
        assert new_round["bank_version_id"] == bank.current_version_id
        assert session.get(BankVersion, bank.current_version_id).version_number == 2


# --- 历史与归属 ---


def test_round_history_lists_all_rounds(auth_client: TestClient) -> None:
    bank_id = _setup_bank(auth_client)
    first = _start(auth_client, bank_id).json()["id"]
    version = 1
    for _ in range(QUESTION_COUNT):
        version = _advance(auth_client, first, version).json()["progress_version"]

    _start(auth_client, bank_id)

    history = auth_client.get(f"/api/v1/banks/{bank_id}/rounds").json()
    assert [item["round_number"] for item in history] == [2, 1]
    assert history[1]["status"] == "completed"
    assert history[0]["status"] == "in_progress"


def test_round_history_does_not_leak_answers(auth_client: TestClient) -> None:
    bank_id = _setup_bank(auth_client)
    _start(auth_client, bank_id)
    response = auth_client.get(f"/api/v1/banks/{bank_id}/rounds")
    assert "answer" not in response.text


def test_unknown_round_returns_404(auth_client: TestClient) -> None:
    assert (
        auth_client.get("/api/v1/rounds/00000000-0000-0000-0000-000000000000").status_code
        == 404
    )


def test_cannot_read_other_users_round(client: TestClient, auth_client: TestClient) -> None:
    from app.common.security import hash_password
    from app.db.models import User
    from app.db.session import get_session_factory

    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]

    with get_session_factory()() as session:
        session.add(User(username="intruder", password_hash=hash_password("pw123456")))
        session.commit()

    client.post("/api/v1/auth/login", json={"username": "intruder", "password": "pw123456"})
    assert client.get(f"/api/v1/rounds/{round_id}").status_code == 404
    assert client.post(f"/api/v1/rounds/{round_id}/reveal").status_code == 404
    assert client.post(f"/api/v1/rounds/{round_id}/abandon").status_code == 404


def test_bank_list_exposes_active_round(auth_client: TestClient) -> None:
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]
    _advance(auth_client, round_id, 1)

    listed = auth_client.get("/api/v1/banks").json()
    active = listed[0]["active_round"]
    assert active["id"] == round_id
    assert active["current_index"] == 1
    assert active["total_count"] == QUESTION_COUNT
    assert active["status"] == "in_progress"


def test_bank_summary_reports_completed_round_count(auth_client: TestClient) -> None:
    """题库列表要能回答「这个题库我刷完过几轮」。"""
    bank_id = _setup_bank(auth_client)
    assert auth_client.get(f"/api/v1/banks/{bank_id}").json()["completed_round_count"] == 0

    first = _start(auth_client, bank_id).json()["id"]
    version = 1
    for _ in range(QUESTION_COUNT):
        version = _advance(auth_client, first, version).json()["progress_version"]

    assert auth_client.get(f"/api/v1/banks/{bank_id}").json()["completed_round_count"] == 1
    listed = {bank["id"]: bank for bank in auth_client.get("/api/v1/banks").json()}
    assert listed[bank_id]["completed_round_count"] == 1

    # 第二轮刷到一半：没有走完就不算完成
    second = _start(auth_client, bank_id).json()["id"]
    _advance(auth_client, second, 1)
    assert auth_client.get(f"/api/v1/banks/{bank_id}").json()["completed_round_count"] == 1


def test_abandoned_round_does_not_count_as_completed(auth_client: TestClient) -> None:
    bank_id = _setup_bank(auth_client)
    round_id = _start(auth_client, bank_id).json()["id"]
    auth_client.post(f"/api/v1/rounds/{round_id}/abandon")

    assert auth_client.get(f"/api/v1/banks/{bank_id}").json()["completed_round_count"] == 0

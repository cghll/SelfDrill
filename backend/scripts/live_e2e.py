"""真实 HTTP 端到端验证脚本。

与 pytest 的 TestClient 不同，这里通过真实网络栈访问已启动的 uvicorn 服务，
用于确认 Cookie、multipart 上传和路由在真实运行环境下都正常。

用法：
    python scripts/live_e2e.py [base_url] [username] [password]

默认读取环境变量 E2E_BASE_URL / E2E_USERNAME / E2E_PASSWORD。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from http.cookiejar import CookieJar
from pathlib import Path

BASE = (
    sys.argv[1] if len(sys.argv) > 1 else os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8000")
)
USERNAME = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("E2E_USERNAME", "owner")
PASSWORD = sys.argv[3] if len(sys.argv) > 3 else os.environ.get("E2E_PASSWORD", "")
API = f"{BASE}/api/v1"
SAMPLES = Path(__file__).resolve().parent.parent.parent / "samples"

_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

PASSED = 0
FAILED = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS  {label}")
    else:
        FAILED += 1
        print(f"  FAIL  {label} {detail}")


def call(
    method: str,
    path: str,
    *,
    payload: dict | None = None,
    expect: int | None = None,
) -> tuple[int, dict | list | None]:
    url = f"{API}{path}"
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _opener.open(request) as response:
            body = response.read().decode("utf-8")
            status = response.status
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8")
        status = error.code

    parsed = json.loads(body) if body else None
    if expect is not None and status != expect:
        print(f"  ! {method} {path} -> {status}（期望 {expect}）: {body[:200]}")
    return status, parsed


def upload(path: str, file_path: Path) -> tuple[int, dict]:
    boundary = f"----selfdrill{uuid.uuid4().hex}"
    content = file_path.read_bytes()
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'.encode(),
            b"Content-Type: text/markdown\r\n\r\n",
            content,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    request = urllib.request.Request(
        f"{API}{path}",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with _opener.open(request) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def main() -> int:
    print(f"真实 HTTP 端到端验证：{BASE}（用户 {USERNAME}）\n")

    print("[1] 未登录访问被拒绝")
    status, _ = call("GET", "/banks")
    check("GET /banks 未登录返回 401", status == 401, f"实际 {status}")

    print("\n[2] 登录")
    status, body = call(
        "POST", "/auth/login", payload={"username": USERNAME, "password": PASSWORD}
    )
    check("登录成功", status == 200 and body["user"]["username"] == USERNAME, str(body)[:120])

    status, body = call("GET", "/auth/me")
    check("会话 Cookie 生效", status == 200 and body["username"] == USERNAME)

    print("\n[3] 建库与首次导入")
    status, bank = call("POST", "/banks", payload={"name": "真实环境验证题库"}, expect=201)
    check("创建题库", status == 201)
    bank_id = bank["id"]

    v1 = SAMPLES / "java热门面试.md"
    status, preview = upload(f"/banks/{bank_id}/imports/preview", v1)
    check("上传 Markdown 成功", status == 201, str(preview)[:150])
    check("识别出 14 个候选（13 题 + 1 待确认）", preview["summary"]["total_candidates"] == 14)
    check("代码块未被识别为标题", all("TREEIFY" not in i["title"] for i in preview["items"]))
    check(
        "「redis篇」被判为分类",
        next(i for i in preview["items"] if i["title"] == "redis篇")["classification"]
        == "section",
    )

    accepted = [
        i["preview_item_id"] for i in preview["items"] if i["classification"] == "question"
    ]
    status, confirmed = call(
        "POST",
        f"/imports/{preview['preview_id']}/confirm",
        payload={
            "accepted_preview_item_ids": accepted,
            "resolved_ambiguities": [],
            "confirmed_deleted_question_ids": [],
        },
        expect=201,
    )
    check("确认导入生成版本 1", status == 201 and confirmed["version_number"] == 1)
    check("导入 13 道题", confirmed["changes"]["added"] == 13, str(confirmed["changes"]))

    status, detail = call("GET", f"/banks/{bank_id}")
    check("题库题目数为 13", detail["question_count"] == 13)
    check("新题库已完成轮数为 0", detail["completed_round_count"] == 0, str(detail.get("completed_round_count")))

    print("\n[4] 刷题：每题一次、答案默认隐藏、可完成整轮")
    status, round_body = call("POST", f"/banks/{bank_id}/rounds", payload={"restart": False})
    check("开始轮次", status == 201 and round_body["total_count"] == 13)
    round_id = round_body["id"]

    status, current = call("GET", f"/rounds/{round_id}")
    check("未 reveal 时 answer 为 null", current["current_item"]["answer"] is None)

    status, revealed = call("POST", f"/rounds/{round_id}/reveal")
    check("reveal 返回答案", status == 200 and bool(revealed["answer"]))

    status, again = call("POST", f"/rounds/{round_id}/reveal")
    check("reveal 幂等", again["answer"] == revealed["answer"])

    print("\n[4b] 上一题：由服务端改写位置，受乐观锁保护")
    first_item_id = current["current_item"]["id"]

    # 第一题再按「上一题」：空操作，不改变位置，也不推高版本号
    status, at_first = call(
        "POST",
        f"/rounds/{round_id}/advance",
        payload={"expected_progress_version": current["progress_version"], "direction": "previous"},
    )
    check("第一题回退是空操作", status == 200 and at_first["current_index"] == 0)
    check("空操作不改变进度版本", at_first["progress_version"] == current["progress_version"])

    status, moved = call(
        "POST",
        f"/rounds/{round_id}/advance",
        payload={"expected_progress_version": at_first["progress_version"], "direction": "next"},
    )
    check("推进到第二题", moved["current_index"] == 1, str(moved)[:120])
    second_item_id = moved["current_item"]["id"]

    status, back = call(
        "POST",
        f"/rounds/{round_id}/advance",
        payload={"expected_progress_version": moved["progress_version"], "direction": "previous"},
    )
    check("回退到上一题", status == 200 and back["current_index"] == 0, str(back)[:120])
    check("回到的正是第一题", back["current_item"]["id"] == first_item_id)
    check("回退后已查看的答案仍可见", back["current_item"]["answer_revealed"] is True)

    # 回退同样受乐观锁保护：拿旧版本号必须 409
    status, stale = call(
        "POST",
        f"/rounds/{round_id}/advance",
        payload={"expected_progress_version": moved["progress_version"], "direction": "previous"},
    )
    check("回退使用过期版本号返回 409", status == 409, f"实际 {status}")
    check(
        "回退冲突错误码正确",
        stale["error"]["code"] == "ROUND_PROGRESS_CONFLICT",
        str(stale)[:120],
    )

    status, illegal = call(
        "POST",
        f"/rounds/{round_id}/advance",
        payload={"expected_progress_version": back["progress_version"], "direction": "sideways"},
    )
    check("非法方向被拒绝", status == 400 and illegal["error"]["code"] == "INVALID_REQUEST")

    # 回到第二题继续把整轮走完，seen 里不能因此出现重复题
    status, resumed = call(
        "POST",
        f"/rounds/{round_id}/advance",
        payload={"expected_progress_version": back["progress_version"], "direction": "next"},
    )
    check("回到第二题", resumed["current_index"] == 1 and resumed["current_item"]["id"] == second_item_id)

    # 回到第二题继续把整轮走完。这里先把已经看过的前两题记进 seen，
    # 循环从第二题往后推进，避免因为中途回退过而漏题或重复计数。
    seen: list[str] = [
        current["current_item"]["question"]["title"],
        resumed["current_item"]["question"]["title"],
    ]
    version = resumed["progress_version"]
    cursor = resumed
    guard = 0
    while cursor["status"] == "in_progress" and guard < 100:
        guard += 1
        status, cursor = call(
            "POST",
            f"/rounds/{round_id}/advance",
            payload={"expected_progress_version": version, "idempotency_key": f"live-{version}"},
        )
        if status != 200:
            check(f"推进第 {version} 步", False, str(cursor)[:150])
            break
        version = cursor["progress_version"]
        if cursor["status"] == "in_progress":
            seen.append(cursor["current_item"]["question"]["title"])

    check("走完 13 道题", len(seen) == 13, f"实际 {len(seen)}")
    check("每题恰好出现一次", len(set(seen)) == 13)
    check("轮次标记为已完成", cursor["status"] == "completed")
    check("记录了完成时间", bool(cursor.get("completed_at")))

    status, after_done = call("GET", f"/banks/{bank_id}")
    check("完成后已完成轮数为 1", after_done["completed_round_count"] == 1, str(after_done.get("completed_round_count")))

    status, listed = call("GET", "/banks")
    entry = next((b for b in listed if b["id"] == bank_id), None)
    check("题库列表暴露已完成轮数", entry is not None and entry["completed_round_count"] == 1, str(entry)[:150])

    status, late = call(
        "POST",
        f"/rounds/{round_id}/advance",
        payload={"expected_progress_version": cursor["progress_version"], "direction": "previous"},
    )
    check("已完成轮次不能回退", status == 400, f"实际 {status}")

    print("\n[5] 并发冲突")
    status, conflict = call(
        "POST",
        f"/rounds/{round_id}/advance",
        payload={"expected_progress_version": 1},
    )
    check("已完成轮次推进被拒绝", status == 400, f"实际 {status}")

    status, new_round = call("POST", f"/banks/{bank_id}/rounds", payload={"restart": False})
    check("开始第 2 轮", new_round["round_number"] == 2)
    new_round_id = new_round["id"]

    status, first = call(
        "POST",
        f"/rounds/{new_round_id}/advance",
        payload={"expected_progress_version": 1, "idempotency_key": "dup-key"},
    )
    check("第一次推进成功", status == 200)

    status, retry = call(
        "POST",
        f"/rounds/{new_round_id}/advance",
        payload={"expected_progress_version": 1, "idempotency_key": "dup-key"},
    )
    check("相同幂等键重放不重复推进", retry["current_index"] == first["current_index"])

    status, conflict = call(
        "POST",
        f"/rounds/{new_round_id}/advance",
        payload={"expected_progress_version": 1, "idempotency_key": "another-key"},
    )
    check("过期版本号返回 409", status == 409, f"实际 {status}")
    check(
        "冲突错误码正确",
        conflict["error"]["code"] == "ROUND_PROGRESS_CONFLICT",
        str(conflict)[:150],
    )

    print("\n[6] 更新导入")
    v2 = SAMPLES / "java热门面试-v2.md"
    status, preview2 = upload(f"/banks/{bank_id}/imports/preview", v2)
    check("更新预览成功", status == 201)
    check("识别为更新模式", preview2["mode"] == "update")
    # 新增 = 新题 1 道 + 待确认的文档标题 1 项（低置信项每次都需用户确认）
    check("新增 2 项（1 道新题 + 1 个待确认标题）", preview2["diff"]["added"] == 2, str(preview2["diff"]))
    check("修改 2 道题", preview2["diff"]["modified"] == 2, str(preview2["diff"]))
    check("未变化 11 道题", preview2["diff"]["unchanged"] == 11, str(preview2["diff"]))

    accepted2 = [
        i["preview_item_id"] for i in preview2["items"] if i["classification"] == "question"
    ]
    status, confirmed2 = call(
        "POST",
        f"/imports/{preview2['preview_id']}/confirm",
        payload={
            "accepted_preview_item_ids": accepted2,
            "resolved_ambiguities": [],
            "confirmed_deleted_question_ids": [],
        },
        expect=201,
    )
    check("确认更新生成版本 2", status == 201 and confirmed2["version_number"] == 2)

    status, detail2 = call("GET", f"/banks/{bank_id}")
    check("题库题目数变为 14", detail2["question_count"] == 14, str(detail2["question_count"]))

    status, versions = call("GET", f"/banks/{bank_id}/versions")
    by_number = {v["version_number"]: v["status"] for v in versions}
    check("版本 1 被标记 superseded", by_number[1] == "superseded")
    check("版本 2 为 active", by_number[2] == "active")

    status, old_round = call("GET", f"/rounds/{new_round_id}")
    check("更新前创建的轮次仍使用旧版本", old_round["bank_version_id"] != detail2["current_version_id"])

    print("\n[7] 删除题库")
    status, _ = call("DELETE", f"/banks/{bank_id}", expect=204)
    check("删除返回 204", status == 204)
    status, _ = call("GET", f"/banks/{bank_id}")
    check("删除后查询返回 404", status == 404)

    print(f"\n结果：{PASSED} 项通过，{FAILED} 项失败")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""阶段 1：配置、数据库与鉴权接口测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings


def test_initial_user_created_on_startup(client: TestClient) -> None:
    """启动时按配置创建唯一账号，且不开放注册接口。"""
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "owner", "password": "test-password"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["username"] == "owner"
    assert "password" not in response.text


def test_login_sets_httponly_cookie(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "owner", "password": "test-password"},
    )
    assert response.status_code == 200
    cookie_header = response.headers["set-cookie"]
    assert "HttpOnly" in cookie_header
    assert "SameSite=lax" in cookie_header.lower() or "samesite=lax" in cookie_header.lower()


def test_login_wrong_password_returns_unauthenticated(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "owner", "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_login_unknown_user_same_error_as_wrong_password(client: TestClient) -> None:
    """不能通过错误信息区分「用户不存在」与「密码错误」。"""
    unknown = client.post(
        "/api/v1/auth/login", json={"username": "nobody", "password": "whatever"}
    )
    wrong = client.post(
        "/api/v1/auth/login", json={"username": "owner", "password": "whatever"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_me_requires_session(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_me_returns_current_user(auth_client: TestClient) -> None:
    response = auth_client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["username"] == "owner"


def test_logout_clears_session(auth_client: TestClient) -> None:
    logout = auth_client.post("/api/v1/auth/logout")
    assert logout.status_code == 204
    assert auth_client.get("/api/v1/auth/me").status_code == 401


def test_tampered_cookie_is_rejected(client: TestClient) -> None:
    client.cookies.set("selfdrill_session", "not-a-valid-token")
    assert client.get("/api/v1/auth/me").status_code == 401


def test_validation_error_uses_contract_shape(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"username": "owner"})
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "INVALID_REQUEST"
    # 校验错误不得回显输入的密码等敏感值
    assert "test-password" not in response.text


def test_unknown_route_uses_contract_shape(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_production_requires_secret_key(monkeypatch) -> None:
    """生产环境缺 APP_SECRET_KEY 必须启动失败。"""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("APP_SECRET_KEY", raising=False)
    settings = Settings(_env_file=None)
    try:
        settings.resolved_secret_key()
    except RuntimeError as exc:
        assert "APP_SECRET_KEY" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("生产环境缺密钥时应抛出 RuntimeError")


def test_development_generates_temporary_secret(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("APP_SECRET_KEY", raising=False)
    settings = Settings(_env_file=None)
    assert settings.resolved_secret_key()


def test_password_stored_as_argon2id_hash(auth_client: TestClient, db_session_factory) -> None:
    from app.db.models import User

    with db_session_factory() as session:
        user = session.query(User).one()
    assert user.password_hash.startswith("$argon2id$")
    assert "test-password" not in user.password_hash

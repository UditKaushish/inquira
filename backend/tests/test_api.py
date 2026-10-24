from fastapi.testclient import TestClient

from inquira.core.security import decrypt_secret, encrypt_secret, hash_password, verify_password
from inquira.db import AppSetting, SessionLocal
from inquira.main import app

API = "/api/v1"


def test_health(client):
    assert client.get(f"{API}/health").json()["status"] == "ok"


def test_csrf_header_required(client):
    with TestClient(app) as bare:
        r = bare.post(f"{API}/auth/login", json={"email": "a@b.co", "password": "x"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf"


def test_first_admin_only_once(client, admin):
    assert admin["role"] == "admin"
    with TestClient(app, headers={"X-Inquira-Client": "web"}) as other:
        r = other.post(f"{API}/setup/admin", json={"name": "Eve", "email": "eve@example.com",
                                                   "password": "another-password"})
    assert r.status_code == 409


def test_protected_endpoints_require_auth(client, admin):
    with TestClient(app, headers={"X-Inquira-Client": "web"}) as anon:
        for method, path in [("get", "/users"), ("get", "/settings"), ("get", "/audit"),
                             ("post", "/settings/datasource/demo"), ("get", "/conversations")]:
            r = getattr(anon, method)(f"{API}{path}")
            assert r.status_code == 401, path


def test_member_cannot_do_admin_things(client, admin):
    r = client.post(f"{API}/users", json={"name": "Bob", "email": "bob@example.com",
                                          "password": "bob-password-1", "role": "member"})
    assert r.status_code == 200
    with TestClient(app, headers={"X-Inquira-Client": "web"}) as bob:
        assert bob.post(f"{API}/auth/login", json={"email": "bob@example.com",
                                                   "password": "bob-password-1"}).status_code == 200
        assert bob.get(f"{API}/users").status_code == 403
        assert bob.put(f"{API}/settings/llm", json={"provider": "gemini", "api_key": "x"}).status_code == 403
        assert bob.patch(f"{API}/users/{admin['id']}", json={"role": "member"}).status_code == 403
        # Responses never leak password hashes.
        assert "password" not in bob.get(f"{API}/auth/me").text


def test_bad_login_is_generic(client, admin):
    r1 = client.post(f"{API}/auth/login", json={"email": "ada@example.com", "password": "wrong-password"})
    r2 = client.post(f"{API}/auth/login", json={"email": "nobody@example.com", "password": "wrong-password"})
    assert r1.status_code == r2.status_code == 401
    assert r1.json() == r2.json()


def test_logout_revokes_session(admin):
    with TestClient(app, headers={"X-Inquira-Client": "web"}) as c:
        c.post(f"{API}/auth/login", json={"email": "ada@example.com", "password": "correct-horse-1"})
        stolen = c.cookies.get("inquira_session")
        assert c.post(f"{API}/auth/logout").status_code == 200
    with TestClient(app, headers={"X-Inquira-Client": "web"}, cookies={"inquira_session": stolen}) as attacker:
        assert attacker.get(f"{API}/auth/me").status_code == 401
    # log the shared admin client back in for later tests
    with TestClient(app, headers={"X-Inquira-Client": "web"}) as c:
        assert c.post(f"{API}/auth/login", json={"email": "ada@example.com",
                                                 "password": "correct-horse-1"}).status_code == 200


def test_llm_key_is_encrypted_and_never_returned(client, admin, monkeypatch):
    from inquira.engine.llm.providers import GeminiProvider

    monkeypatch.setattr(GeminiProvider, "_complete", lambda self, system, prompt: '{"ok": true}')
    client.post(f"{API}/auth/login", json={"email": "ada@example.com", "password": "correct-horse-1"})
    r = client.put(f"{API}/settings/llm", json={"provider": "gemini", "model": "gemini-2.5-flash",
                                                "api_key": "AIzaSECRET-test-key-123"})
    assert r.status_code == 200, r.text
    assert r.json()["llm"]["has_key"] is True
    assert "AIzaSECRET" not in client.get(f"{API}/settings").text
    with SessionLocal() as db:
        row = db.get(AppSetting, "llm")
        assert "AIzaSECRET" not in (row.secret or "") and "AIzaSECRET" not in str(row.value)


def test_demo_datasource_and_schema(client, admin):
    client.post(f"{API}/auth/login", json={"email": "ada@example.com", "password": "correct-horse-1"})
    assert client.post(f"{API}/settings/datasource/demo").status_code == 200
    tables = {t["name"] for t in client.get(f"{API}/schema").json()["tables"]}
    assert {"orders", "customers", "order_items", "products", "sellers", "order_payments"} <= tables
    assert client.get(f"{API}/setup/status").json()["completed"] is True
    assert len(client.get(f"{API}/knowledge").json()["documents"]) > 0


def test_security_primitives():
    h = hash_password("hunter2-hunter2")
    assert h.startswith("$argon2id$")
    assert verify_password("hunter2-hunter2", h)
    assert not verify_password("nope", h)
    assert not verify_password("anything", None)
    assert decrypt_secret(encrypt_secret("s3cret")) == "s3cret"
    assert decrypt_secret("garbage") is None


def test_bad_llm_key_is_rejected_on_save(client, admin, monkeypatch):
    from inquira.engine.llm.providers import OpenAIProvider

    class AuthErr(Exception):
        status_code = 401

    def fail(self, system, prompt):
        raise AuthErr("Incorrect API key provided")

    monkeypatch.setattr(OpenAIProvider, "_complete", fail)
    client.post(f"{API}/auth/login", json={"email": "ada@example.com", "password": "correct-horse-1"})
    before = client.get(f"{API}/settings").json()["llm"]
    r = client.put(f"{API}/settings/llm", json={"provider": "openai", "api_key": "sk-proj-wrongwrongwrong"})
    assert r.status_code == 502 and "rejected the API key" in r.json()["error"]["message"]
    mismatch = client.put(f"{API}/settings/llm", json={"provider": "openai", "api_key": "sk-ant-api03-xyz"})
    assert mismatch.status_code == 400 and mismatch.json()["error"]["code"] == "key_provider_mismatch"
    assert client.get(f"{API}/settings").json()["llm"] == before  # nothing was saved


def test_model_listing_live_and_fallback(client, admin, monkeypatch):
    from inquira.engine.llm.providers import AnthropicProvider, ModelInfo

    client.post(f"{API}/auth/login", json={"email": "ada@example.com", "password": "correct-horse-1"})
    # No key yet: curated suggestions, no error.
    r = client.post(f"{API}/settings/llm/models", json={"provider": "anthropic"}).json()
    assert r["source"] == "curated" and r["message"] is None and r["default_model"]
    assert any(m["id"] == r["default_model"] for m in r["models"])
    # With a key: live list from the provider API.
    monkeypatch.setattr(AnthropicProvider, "_list_models",
                        lambda self: [ModelInfo("claude-new-1", "Claude New"), ModelInfo("claude-old-0")])
    r = client.post(f"{API}/settings/llm/models", json={"provider": "anthropic", "api_key": "sk-ant-api03-x"}).json()
    assert r["source"] == "live" and [m["id"] for m in r["models"]] == ["claude-new-1", "claude-old-0"]
    # Provider API failing: fall back to curated with a readable reason.
    def boom(self):
        raise RuntimeError("connection reset")
    monkeypatch.setattr(AnthropicProvider, "_list_models", boom)
    r = client.post(f"{API}/settings/llm/models", json={"provider": "anthropic", "api_key": "sk-ant-api03-x"}).json()
    assert r["source"] == "curated" and "Anthropic" in r["message"]
    # Members can't enumerate with the stored key.
    with TestClient(app, headers={"X-Inquira-Client": "web"}) as bob:
        bob.post(f"{API}/auth/login", json={"email": "bob@example.com", "password": "bob-password-1"})
        assert bob.post(f"{API}/settings/llm/models", json={"provider": "gemini"}).status_code == 403


def test_edit_knowledge(client, admin):
    client.post(f"{API}/auth/login", json={"email": "ada@example.com", "password": "correct-horse-1"})
    doc = client.post(f"{API}/knowledge", json={"title": "GMV", "kind": "glossary", "content": "old"}).json()["document"]
    r = client.patch(f"{API}/knowledge/{doc['id']}", json={"content": "  Gross merchandise value  ", "kind": "metric"})
    assert r.status_code == 200
    updated = r.json()["document"]
    assert updated["content"] == "Gross merchandise value" and updated["kind"] == "metric" and updated["title"] == "GMV"
    assert client.patch(f"{API}/knowledge/{doc['id']}", json={"title": ""}).status_code == 422
    assert client.patch(f"{API}/knowledge/missing", json={"title": "x"}).status_code == 404
    with TestClient(app, headers={"X-Inquira-Client": "web"}) as bob:
        bob.post(f"{API}/auth/login", json={"email": "bob@example.com", "password": "bob-password-1"})
        assert bob.patch(f"{API}/knowledge/{doc['id']}", json={"title": "hijack"}).status_code == 403

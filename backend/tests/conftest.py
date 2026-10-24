import os
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="inquira-test-"))
os.environ["INQUIRA_DATA_DIR"] = str(_tmp)
# Set TEST_DATABASE_URL to run the suite against Postgres (CI does both).
os.environ["INQUIRA_DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_tmp / 'test.db'}"
os.environ["INQUIRA_SECRET_KEY"] = "test-secret-key-that-is-long-enough-1234567890"
os.environ["INQUIRA_LOGIN_RATE_LIMIT"] = "1000/minute"

from fastapi.testclient import TestClient  # noqa: E402

from inquira.main import app  # noqa: E402

HEADERS = {"X-Inquira-Client": "web"}


@pytest.fixture(scope="session")
def client():
    with TestClient(app, headers=HEADERS) as c:
        yield c


@pytest.fixture(scope="session")
def admin(client):
    r = client.post("/api/v1/setup/admin", json={"name": "Ada", "email": "ada@example.com", "password": "correct-horse-1"})
    assert r.status_code == 200, r.text
    return r.json()["user"]

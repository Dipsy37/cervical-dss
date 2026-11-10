"""
Test set-up: uses a separate throw-away SQLite database so tests never touch
your real PostgreSQL data. The trained model in ml/artifacts must exist.
Run from the backend folder:   pytest -v
"""
import os
import sys
from pathlib import Path

TEST_DB = Path(__file__).parent / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Role, User  # noqa: E402
from app.security import hash_password  # noqa: E402

ADMIN_PASSWORD = "AdminPass1"


@pytest.fixture(scope="session")
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add(User(full_name="Test Admin", username="admin", role=Role.ADMIN,
                    password_hash=hash_password(ADMIN_PASSWORD), must_change_password=False))
        db.commit()
    with TestClient(app) as c:
        yield c
    engine.dispose()
    TEST_DB.unlink(missing_ok=True)


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def admin_token(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
    return r.json()["access_token"]


def create_chw(client, admin_token, name, phone, chu="Kiambaa", new_password="ChwPass123"):
    """Register a CHW, log in with the temporary password, set a new one. Returns (user_id, token)."""
    r = client.post("/api/users", headers=auth(admin_token),
                    json={"full_name": name, "phone": phone, "chu_name": chu})
    assert r.status_code == 201, r.text
    creds = r.json()
    t = client.post("/api/auth/login", json={"username": creds["username"],
                                             "password": creds["temporary_password"]}).json()["access_token"]
    r = client.post("/api/auth/change-password", headers=auth(t),
                    json={"current_password": creds["temporary_password"], "new_password": new_password})
    assert r.status_code == 204, r.text
    return creds["user_id"], t


@pytest.fixture(scope="session")
def chw(client, admin_token):
    return create_chw(client, admin_token, "Jane Wanjiru", "0712345678")


@pytest.fixture(scope="session")
def other_chw(client, admin_token):
    return create_chw(client, admin_token, "Peter Otieno", "0723456789", chu="Kisumu Central")

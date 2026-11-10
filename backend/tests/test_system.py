"""
Black-box system tests (Chapter 3, section 3.7): each test checks one functional
requirement through the public API only. Test IDs can be copied into your test-case table.
"""
from tests.conftest import auth, create_chw


# ---------------- Authentication ----------------
def test_TC01_login_valid(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "AdminPass1"})
    assert r.status_code == 200 and r.json()["role"] == "ADMIN"


def test_TC02_login_wrong_password(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_TC03_no_token_rejected(client):
    assert client.get("/api/dashboard/summary").status_code == 401


def test_TC04_temporary_password_must_be_changed(client, admin_token):
    creds = client.post("/api/users", headers=auth(admin_token),
                        json={"full_name": "Mary Akinyi", "phone": "0734567890", "chu_name": "Kiambaa"}).json()
    login = client.post("/api/auth/login", json={"username": creds["username"],
                                                 "password": creds["temporary_password"]}).json()
    assert login["must_change_password"] is True
    # Until the password is changed, other functions are blocked
    assert client.get("/api/dashboard/summary", headers=auth(login["access_token"])).status_code == 403


def test_TC05_weak_new_password_rejected(client, admin_token):
    creds = client.post("/api/users", headers=auth(admin_token),
                        json={"full_name": "Grace Muthoni", "phone": "0745678901", "chu_name": "Kiambaa"}).json()
    t = client.post("/api/auth/login", json={"username": creds["username"],
                                             "password": creds["temporary_password"]}).json()["access_token"]
    r = client.post("/api/auth/change-password", headers=auth(t),
                    json={"current_password": creds["temporary_password"], "new_password": "short"})
    assert r.status_code == 400


# ---------------- Administrator functions ----------------
def test_TC06_register_chw_generates_credentials(client, admin_token):
    r = client.post("/api/users", headers=auth(admin_token),
                    json={"full_name": "Ann Njeri", "phone": "0756789012", "chu_name": "Kiambaa"})
    body = r.json()
    assert r.status_code == 201 and body["username"] == "anjeri" and len(body["temporary_password"]) >= 8


def test_TC07_duplicate_phone_rejected(client, admin_token, chw):
    r = client.post("/api/users", headers=auth(admin_token),
                    json={"full_name": "Someone Else", "phone": "0712345678", "chu_name": "Kiambaa"})
    assert r.status_code == 409


def test_TC08_invalid_phone_rejected(client, admin_token):
    r = client.post("/api/users", headers=auth(admin_token),
                    json={"full_name": "Bad Phone", "phone": "12345", "chu_name": "Kiambaa"})
    assert r.status_code == 422


def test_TC09_chw_cannot_use_admin_functions(client, chw):
    _, token = chw
    assert client.get("/api/users", headers=auth(token)).status_code == 403


def test_TC10_deactivated_chw_cannot_log_in(client, admin_token):
    user_id, _ = create_chw(client, admin_token, "Tom Kiprop", "0767890123", new_password="TomPass123")
    assert client.post(f"/api/users/{user_id}/deactivate", headers=auth(admin_token)).status_code == 200
    r = client.post("/api/auth/login", json={"username": "tkiprop", "password": "TomPass123"})
    assert r.status_code == 403


def test_TC11_reset_password_issues_new_temporary_password(client, admin_token):
    user_id, _ = create_chw(client, admin_token, "Lucy Achieng", "0778901234", new_password="LucyPass123")
    creds = client.post(f"/api/users/{user_id}/reset-password", headers=auth(admin_token)).json()
    assert client.post("/api/auth/login", json={"username": "lachieng", "password": "LucyPass123"}).status_code == 401
    r = client.post("/api/auth/login", json={"username": "lachieng", "password": creds["temporary_password"]})
    assert r.status_code == 200 and r.json()["must_change_password"] is True


# ---------------- Dashboard ----------------
def test_TC22_dashboard_counts_and_scope(client, admin_token, chw, other_chw):
    admin = client.get("/api/dashboard/summary", headers=auth(admin_token)).json()
    mine = client.get("/api/dashboard/summary", headers=auth(chw[1])).json()
    other = client.get("/api/dashboard/summary", headers=auth(other_chw[1])).json()
    assert admin["total_assessments"] == sum(admin["by_level"].values())
    assert len(admin["per_day"]) == 14 and "model" in admin and "by_chu" in admin
    assert admin["total_assessments"] == 0 and mine["total_assessments"] == 0 == other["total_assessments"]
    assert "by_chu" not in mine and "model" not in mine          # CHWs see only their own figures

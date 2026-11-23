"""
Black-box system tests (Chapter 3, section 3.7): each test checks one functional
requirement through the public API only. Test IDs can be copied into your test-case table.
"""
from tests.conftest import VALID_ANSWERS, auth, create_chw


def new_client(client, token):
    r = client.post("/api/clients", headers=auth(token))
    assert r.status_code == 201
    return r.json()["client_code"]


# ---------------- Authentication ----------------
def test_TC01_login_valid(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "AdminPass1"})
    assert r.status_code == 200 and r.json()["role"] == "ADMIN"


def test_TC02_login_wrong_password(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_TC03_no_token_rejected(client):
    assert client.get("/api/assessments").status_code == 401


def test_TC04_temporary_password_must_be_changed(client, admin_token):
    creds = client.post("/api/users", headers=auth(admin_token),
                        json={"full_name": "Mary Akinyi", "phone": "0734567890", "chu_name": "Kiambaa"}).json()
    login = client.post("/api/auth/login", json={"username": creds["username"],
                                                 "password": creds["temporary_password"]}).json()
    assert login["must_change_password"] is True
    # Until the password is changed, other functions are blocked
    assert client.get("/api/assessments", headers=auth(login["access_token"])).status_code == 403


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


# ---------------- Clients ----------------
def test_TC12_register_client_creates_pseudonymous_code(client, chw):
    code = new_client(client, chw[1])
    assert code.startswith("CL-") and len(code) == 8


# ---------------- Risk assessment (core use case) ----------------
def test_TC13_valid_assessment_returns_level_referral_and_explanation(client, chw):
    _, token = chw
    r = client.post("/api/assessments", headers=auth(token),
                    json={**VALID_ANSWERS, "client_code": new_client(client, token)})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["risk_level"] in {"LOW", "MODERATE", "HIGH"}
    assert 0 <= body["probability"] <= 1
    assert body["referral_message"]
    assert len(body["top_factors"]) == 3 and body["top_factors"][0]["rank"] == 1
    assert "NOT a diagnosis" in body["disclaimer"]


def test_TC14_declined_answers_are_accepted(client, chw):
    _, token = chw
    answers = {k: None for k in VALID_ANSWERS} | {"consent_obtained": True, "age": 40}
    r = client.post("/api/assessments", headers=auth(token),
                    json={**answers, "client_code": new_client(client, token)})
    assert r.status_code == 201
    saved = r.json()["answers"]
    assert saved["num_sexual_partners"] is None and saved["stds"] is None   # stored as missing, not guessed
    assert all(f["feature_value"] != "Not answered" for f in r.json()["top_factors"])  # only answered factors explained


def test_TC15_assessment_without_consent_rejected(client, chw):
    _, token = chw
    r = client.post("/api/assessments", headers=auth(token),
                    json={**VALID_ANSWERS, "consent_obtained": False, "client_code": new_client(client, token)})
    assert r.status_code == 422


def test_TC16_boundary_ages(client, chw):
    _, token = chw
    code = new_client(client, token)
    for age, expected in [(13, 201), (100, 201), (12, 422), (101, 422)]:
        r = client.post("/api/assessments", headers=auth(token),
                        json={**VALID_ANSWERS, "age": age, "age_first_intercourse": min(13, age),
                              "client_code": code})
        assert r.status_code == expected, (age, r.text)


def test_TC17_inconsistent_ages_rejected(client, chw):
    _, token = chw
    r = client.post("/api/assessments", headers=auth(token),
                    json={**VALID_ANSWERS, "age": 20, "age_first_intercourse": 25,
                          "client_code": new_client(client, token)})
    assert r.status_code == 422


def test_TC18_unknown_client_rejected(client, chw):
    _, token = chw
    r = client.post("/api/assessments", headers=auth(token), json={**VALID_ANSWERS, "client_code": "CL-99999"})
    assert r.status_code == 404


def test_TC19_result_saved_with_model_version(client, chw):
    _, token = chw
    created = client.post("/api/assessments", headers=auth(token),
                          json={**VALID_ANSWERS, "client_code": new_client(client, token)}).json()
    saved = client.get(f"/api/assessments/{created['assessment_id']}", headers=auth(token)).json()
    assert saved["risk_level"] == created["risk_level"] and saved["model_version"]


# ---------------- Access control on records ----------------
def test_TC20_chw_sees_only_own_assessments(client, chw, other_chw):
    _, token_a = chw
    _, token_b = other_chw
    created = client.post("/api/assessments", headers=auth(token_a),
                          json={**VALID_ANSWERS, "client_code": new_client(client, token_a)}).json()
    assert client.get(f"/api/assessments/{created['assessment_id']}", headers=auth(token_b)).status_code == 403
    ids_b = [a["assessment_id"] for a in client.get("/api/assessments", headers=auth(token_b)).json()]
    assert created["assessment_id"] not in ids_b


def test_TC21_admin_sees_all_and_can_filter(client, admin_token, chw):
    all_rows = client.get("/api/assessments", headers=auth(admin_token)).json()
    assert len(all_rows) >= 1
    level = all_rows[0]["risk_level"]
    filtered = client.get(f"/api/assessments?risk_level={level}", headers=auth(admin_token)).json()
    assert filtered and all(a["risk_level"] == level for a in filtered)


# ---------------- Dashboard ----------------
def test_TC22_dashboard_counts_and_scope(client, admin_token, chw, other_chw):
    admin = client.get("/api/dashboard/summary", headers=auth(admin_token)).json()
    mine = client.get("/api/dashboard/summary", headers=auth(chw[1])).json()
    other = client.get("/api/dashboard/summary", headers=auth(other_chw[1])).json()
    assert admin["total_assessments"] == sum(admin["by_level"].values())
    assert len(admin["per_day"]) == 14 and "model" in admin and "by_chu" in admin
    assert mine["total_assessments"] + other["total_assessments"] <= admin["total_assessments"]
    assert "by_chu" not in mine and "model" not in mine          # CHWs see only their own figures

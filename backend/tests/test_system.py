"""
Black-box system tests (Chapter 3, section 3.7): each test checks one functional
requirement through the public API only. Test IDs can be copied into your test-case table.
"""
from sqlalchemy import text

from app.database import SessionLocal
from app.models import Client
from tests.conftest import VALID_ANSWERS, auth, create_chw, register_client, years_ago


def new_client(client, token, age=34, **details):
    return register_client(client, token, age, **details)["client_code"]


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
    body = register_client(client, chw[1], 34)
    assert body["client_code"].startswith("CL-") and len(body["client_code"]) == 8
    assert body["age"] == 34 and body["dob_estimated"] is False


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
    answers = {k: None for k in VALID_ANSWERS} | {"consent_obtained": True}
    r = client.post("/api/assessments", headers=auth(token),
                    json={**answers, "client_code": new_client(client, token, age=40)})
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
    """Clients must be 18-100. 17 years and 364 days is still 17."""
    _, token = chw
    for dob, expected in [(years_ago(18), 201), (years_ago(100), 201),
                          (years_ago(18, days=-1), 422), (years_ago(101), 422)]:
        r = client.post("/api/clients", headers=auth(token), json={"date_of_birth": dob})
        assert r.status_code == expected, (dob, r.text)


def test_TC17_inconsistent_ages_rejected(client, chw):
    _, token = chw
    r = client.post("/api/assessments", headers=auth(token),
                    json={**VALID_ANSWERS, "age_first_intercourse": 25,
                          "client_code": new_client(client, token, age=20)})
    assert r.status_code == 422 and "cannot be greater than her age" in r.text


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


# ---------------- Client identity, date of birth and privacy ----------------
MARY = {"identity_consent": True, "full_name": "Mary Wanjiru", "phone": "0711222333", "village": "Kiambaa"}


def test_TC23_personal_details_are_encrypted_in_the_database(client, chw):
    code = new_client(client, chw[1], **MARY)
    with SessionLocal() as db:
        client_id = db.query(Client).filter_by(client_code=code).one().client_id
        row = db.execute(text("SELECT full_name, phone, village, date_of_birth FROM client_identities "
                              "WHERE client_id = :id"), {"id": client_id}).one()
    for stored in row:
        assert stored.startswith("gAAAA")                     # Fernet ciphertext, not readable text
    assert "Mary" not in "".join(row) and "0711222333" not in "".join(row)


def test_TC24_name_visible_to_registering_chw_only(client, admin_token, chw, other_chw):
    _, token = chw
    code = new_client(client, token, **MARY)
    mine = client.get(f"/api/clients/{code}", headers=auth(token)).json()
    assert mine["display_name"] == "Mary Wanjiru" and mine["phone"] == "0711222333" and mine["date_of_birth"]
    theirs = client.get(f"/api/clients/{code}", headers=auth(other_chw[1])).json()
    assert theirs["display_name"] == "M. W." and theirs["name_masked"] is True
    assert theirs["phone"] is None and theirs["date_of_birth"] is None and theirs["age"] == 34

    created = client.post("/api/assessments", headers=auth(token), json={**VALID_ANSWERS, "client_code": code}).json()
    assert created["client_name"] == "Mary Wanjiru"
    as_admin = client.get(f"/api/assessments/{created['assessment_id']}", headers=auth(admin_token)).json()
    assert as_admin["client_name"] == "M. W."                 # Administrator sees initials only
    rows = client.get(f"/api/assessments?client_code={code}", headers=auth(admin_token)).json()
    assert rows[0]["client_name"] == "M. W."


def test_TC25_identity_details_need_separate_consent(client, chw):
    _, token = chw
    r = client.post("/api/clients", headers=auth(token),
                    json={"date_of_birth": years_ago(30), "full_name": "Ruth Chebet"})
    assert r.status_code == 422 and "agrees" in r.text
    # Without identity consent the client is still registered, pseudonymously
    body = register_client(client, token, 30)
    assert body["display_name"] is None


def test_TC26_approximate_age_when_date_of_birth_unknown(client, chw):
    _, token = chw
    r = client.post("/api/clients", headers=auth(token), json={"estimated_age": 45})
    assert r.status_code == 201 and r.json()["age"] == 45 and r.json()["dob_estimated"] is True
    both = client.post("/api/clients", headers=auth(token),
                       json={"estimated_age": 45, "date_of_birth": years_ago(45)})
    neither = client.post("/api/clients", headers=auth(token), json={})
    assert both.status_code == 422 and neither.status_code == 422


def test_TC27_age_calculated_from_date_of_birth_with_screening_notice(client, chw):
    _, token = chw
    for age, notice in [(22, "Below"), (34, None), (70, "Above")]:
        code = new_client(client, token, age=age)
        # an "age" typed into the request is ignored: the date of birth decides
        r = client.post("/api/assessments", headers=auth(token),
                        json={**VALID_ANSWERS, "age": 99, "client_code": code})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["age"] == age and body["answers"]["age"] == age
        if notice:
            assert body["guideline_notice"].startswith(notice) and "25" in body["guideline_notice"]
        else:
            assert body["guideline_notice"] is None


def test_TC28_client_without_date_of_birth_must_be_registered_again(client, chw):
    user_id, token = chw
    with SessionLocal() as db:                                # a client saved before this change
        old = Client(client_code="CL-90001", chu_name="Kiambaa", registered_by=user_id)
        db.add(old)
        db.commit()
    assert client.get("/api/clients/CL-90001", headers=auth(token)).json()["has_date_of_birth"] is False
    r = client.post("/api/assessments", headers=auth(token), json={**VALID_ANSWERS, "client_code": "CL-90001"})
    assert r.status_code == 409 and "Register her again" in r.text

# ---------------- Client records (Clients list, client page, update / remove details) ----------------
def test_TC29_clients_list_shows_own_clients_with_latest_result(client, chw, other_chw):
    _, token = chw
    code = new_client(client, token, **MARY)
    client.post("/api/assessments", headers=auth(token), json={**VALID_ANSWERS, "client_code": code})
    second = client.post("/api/assessments", headers=auth(token),
                         json={**VALID_ANSWERS, "client_code": code}).json()
    rows = client.get("/api/clients", headers=auth(token)).json()
    mine = next(r for r in rows if r["client_code"] == code)
    assert mine["display_name"] == "Mary Wanjiru" and mine["visits"] == 2 and mine["age"] == 34
    assert mine["last_risk_level"] == second["risk_level"]
    others = client.get("/api/clients", headers=auth(other_chw[1])).json()
    assert code not in [r["client_code"] for r in others]          # another CHW does not see her


def test_TC30_search_clients_by_name_or_code(client, chw):
    _, token = chw
    code = new_client(client, token, identity_consent=True, full_name="Esther Nyokabi")
    by_name = client.get("/api/clients?search=nyokabi", headers=auth(token)).json()
    by_code = client.get(f"/api/clients?search={code}", headers=auth(token)).json()
    assert [r["client_code"] for r in by_name] == [code] and [r["client_code"] for r in by_code] == [code]


def test_TC31_client_record_for_registering_chw_only(client, chw, other_chw):
    _, token = chw
    code = new_client(client, token, **MARY)
    created = client.post("/api/assessments", headers=auth(token),
                          json={**VALID_ANSWERS, "client_code": code}).json()
    rec = client.get(f"/api/clients/{code}/record", headers=auth(token)).json()
    assert rec["client"]["display_name"] == "Mary Wanjiru" and rec["client"]["village"] == "Kiambaa"
    assert [v["assessment_id"] for v in rec["visits"]] == [created["assessment_id"]]
    assert rec["access_log"] is None                                # the log is for the Administrator
    assert client.get(f"/api/clients/{code}/record", headers=auth(other_chw[1])).status_code == 403


def test_TC32_admin_sees_initials_and_identity_access_log(client, admin_token, chw):
    _, token = chw
    code = new_client(client, token, **MARY)
    client.get(f"/api/clients/{code}/record", headers=auth(token))           # CHW opens the record
    rec = client.get(f"/api/clients/{code}/record", headers=auth(admin_token)).json()
    assert rec["client"]["display_name"] == "M. W." and rec["client"]["phone"] is None
    assert rec["access_log"][0]["action"] == "VIEW" and rec["access_log"][0]["user_name"] == "Jane Wanjiru"
    rows = client.get("/api/clients", headers=auth(admin_token)).json()
    assert any(r["client_code"] == code and r["display_name"] == "M. W." for r in rows)


def test_TC33_update_client_details_is_logged_without_values(client, admin_token, chw, other_chw):
    _, token = chw
    code = new_client(client, token, **MARY)
    r = client.patch(f"/api/clients/{code}", headers=auth(token), json={"phone": "0799888777", "village": "Ndumberi"})
    assert r.status_code == 200 and r.json()["phone"] == "0799888777" and r.json()["village"] == "Ndumberi"
    log = client.get(f"/api/clients/{code}/record", headers=auth(admin_token)).json()["access_log"]
    update = next(e for e in log if e["action"] == "UPDATE")
    assert update["detail"] == "phone, village" and "0799888777" not in str(log)
    assert client.patch(f"/api/clients/{code}", headers=auth(other_chw[1]),
                        json={"phone": "0700000000"}).status_code == 403
    assert client.patch(f"/api/clients/{code}", headers=auth(admin_token),
                        json={"phone": "0700000000"}).status_code == 403
    # a client registered without identity consent cannot be given a name without it
    plain = new_client(client, token)
    assert client.patch(f"/api/clients/{plain}", headers=auth(token),
                        json={"full_name": "Ruth Chebet"}).status_code == 422
    ok = client.patch(f"/api/clients/{plain}", headers=auth(token),
                      json={"identity_consent": True, "full_name": "Ruth Chebet"})
    assert ok.status_code == 200 and ok.json()["display_name"] == "Ruth Chebet"


def test_TC34_remove_personal_details_keeps_code_age_and_visits(client, admin_token, chw):
    _, token = chw
    code = new_client(client, token, **MARY)
    client.post("/api/assessments", headers=auth(token), json={**VALID_ANSWERS, "client_code": code})
    r = client.post(f"/api/clients/{code}/remove-details", headers=auth(token))
    body = r.json()
    assert r.status_code == 200 and body["display_name"] is None and body["phone"] is None
    assert body["age"] == 34                                         # date of birth is kept
    with SessionLocal() as db:
        client_id = db.query(Client).filter_by(client_code=code).one().client_id
        row = db.execute(text("SELECT full_name, phone, village, date_of_birth, identity_consent "
                              "FROM client_identities WHERE client_id = :id"), {"id": client_id}).one()
    assert row[0] is None and row[1] is None and row[2] is None and row[3] and not row[4]
    rec = client.get(f"/api/clients/{code}/record", headers=auth(admin_token)).json()
    assert len(rec["visits"]) == 1 and rec["details_removed_at"]
    assert rec["access_log"][0]["action"] == "REMOVE"
    # she can still be assessed: her age still comes from her date of birth
    again = client.post("/api/assessments", headers=auth(token), json={**VALID_ANSWERS, "client_code": code})
    assert again.status_code == 201 and again.json()["client_name"] is None and again.json()["age"] == 34

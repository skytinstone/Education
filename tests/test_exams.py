"""시험 기록·점수 추이, 운영 콘솔의 강제 로그아웃과 관리 기록."""

import pytest

from education.config import get_settings

from conftest import signup

ADMIN = "admin@example.com"


@pytest.fixture(autouse=True)
def admins(monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_emails", ADMIN)


def project(client, auth) -> str:
    return client.post("/api/projects", json={"name": "미적분", "subject_id": "math.calculus"}, headers=auth).json()["id"]


def items(right: int, wrong: int, skipped: int = 0) -> list[dict]:
    out = [{"problem_id": f"p{i}", "number": i + 1, "my": "1", "answer": "1", "correct": True, "points": 3, "sec": 30 + i}
           for i in range(right)]
    out += [{"problem_id": f"w{i}", "my": "2", "answer": "1", "correct": False, "points": 3, "sec": 200} for i in range(wrong)]
    out += [{"problem_id": f"s{i}", "my": "", "answer": "1", "correct": False, "points": 3, "sec": 5} for i in range(skipped)]
    return out


def test_exam_record_and_trend(client, auth):
    pid = project(client, auth)
    r = client.post(f"/api/projects/{pid}/exams", json={"title": "1회", "per": 1, "time_limit_sec": 1800, "used_sec": 900,
                                                         "items": items(2, 1, 1)}, headers=auth)
    assert r.status_code == 201
    first = r.json()
    assert (first["score"], first["total_points"], first["correct"], first["total"], first["skipped"]) == (6, 12, 2, 4, 1)
    assert first["previous_rate"] is None and first["attempts"] == 1
    second = client.post(f"/api/projects/{pid}/exams", json={"title": "2회", "used_sec": 600, "items": items(4, 0)},
                         headers=auth).json()
    assert second["previous_rate"] == 0.5 and second["rate"] == 1.0 and second["attempts"] == 2
    rows = client.get(f"/api/projects/{pid}/exams", headers=auth).json()
    assert [x["title"] for x in rows] == ["2회", "1회"]                               # 최신순
    d = client.get(f"/api/exams/{first['id']}", headers=auth).json()
    assert len(d["items"]) == 4 and max(i["sec"] for i in d["items"]) == 200      # 문항별 시간
    assert client.delete(f"/api/exams/{first['id']}", headers=auth).status_code == 204
    assert len(client.get(f"/api/projects/{pid}/exams", headers=auth).json()) == 1


def test_exam_records_are_private(client, auth, new_user):
    pid = project(client, auth)
    rid = client.post(f"/api/projects/{pid}/exams", json={"title": "x", "used_sec": 1, "items": items(1, 0)}, headers=auth).json()["id"]
    other = new_user()
    assert client.get(f"/api/exams/{rid}", headers=other).status_code == 404
    assert client.get(f"/api/projects/{pid}/exams", headers=other).status_code == 404
    assert client.post(f"/api/projects/{pid}/exams", json={"title": "x", "used_sec": 1, "items": items(1, 0)}, headers=other).status_code == 404


def test_admin_force_logout_and_action_log(client):
    admin = signup(client, name="운영자", email=ADMIN)
    signup(client, name="학생", email="kid@example.com", password="password123")
    kid = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": "kid@example.com", "password": "password123"}).json()["access_token"]}
    uid = client.get("/api/me", headers=kid).json()["id"]

    r = client.post(f"/api/admin/users/{uid}/logout", json={"reason": "도용 의심"}, headers=admin)
    assert r.status_code == 200 and r.json()["actions"][0]["action"] == "logout"
    out = client.get("/api/me", headers=kid)
    assert out.status_code == 401 and out.headers["X-Session-Replaced"] == "admin" and "운영자" in out.json()["detail"]
    # 다시 로그인하면 쓸 수 있다
    kid2 = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": "kid@example.com", "password": "password123"}).json()["access_token"]}
    assert client.get("/api/me", headers=kid2).status_code == 200

    client.post(f"/api/admin/users/{uid}/suspend", json={"reason": "규칙 위반"}, headers=admin)
    client.post(f"/api/admin/users/{uid}/unsuspend", headers=admin)
    log = client.get("/api/admin/actions", headers=admin).json()
    assert [a["action"] for a in log["items"]][:3] == ["unsuspend", "suspend", "logout"]
    assert log["items"][2]["detail"] == "도용 의심" and log["items"][0]["admin_email"] == ADMIN
    assert log["last_30d"]["suspend"] == 1
    assert client.get("/api/admin/actions", params={"action": "logout"}, headers=admin).json()["items"][0]["target_email"] == "kid@example.com"
    # 계정을 지워도 기록은 남는다
    client.request("DELETE", f"/api/admin/users/{uid}", json={"confirm_email": "kid@example.com"}, headers=admin)
    log = client.get("/api/admin/actions", headers=admin).json()["items"]
    assert log[0]["action"] == "delete" and log[0]["target_email"] == "kid@example.com"


def test_admin_cannot_force_logout_self_and_users_cannot_call(client, auth):
    admin = signup(client, name="운영자", email=ADMIN)
    me = client.get("/api/me", headers=admin).json()["id"]
    assert client.post(f"/api/admin/users/{me}/logout", json={}, headers=admin).status_code == 409
    assert client.post(f"/api/admin/users/{me}/logout", json={}, headers=auth).status_code == 404
    assert client.get("/api/admin/actions", headers=auth).status_code == 404

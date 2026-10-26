from datetime import date, timedelta

from sqlalchemy import select

from education.db import models as m



def wrong_choice(answer: str) -> str:
    return "1" if answer != "1" else "2"


# ---------- 인증 ----------
def test_signup_login_me(client):
    r = client.post("/api/auth/signup", json={"name": "민석", "email": "Min@Example.com", "password": "abc12345",
                                              "over_14": True, "agreed_terms": True})
    assert r.status_code == 201
    assert r.json()["user"]["email"] == "min@example.com"  # 소문자로 저장

    assert client.post("/api/auth/signup", json={"name": "x", "email": "min@example.com", "password": "abc12345",
                                                 "over_14": True, "agreed_terms": True}).status_code == 409
    token = client.post("/api/auth/login", json={"email": "MIN@example.com", "password": "abc12345"}).json()["access_token"]
    me = client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["name"] == "민석" and me["daily_goal"] == 20


def test_login_failure_does_not_reveal_account(client, new_user):
    new_user(email="a@example.com")
    wrong_pw = client.post("/api/auth/login", json={"email": "a@example.com", "password": "nope12345"})
    no_user = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "nope12345"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()


def test_signup_validation(client):
    base = {"name": "a", "email": "v@example.com", "over_14": True, "agreed_terms": True}
    assert client.post("/api/auth/signup", json={**base, "password": "abcdefgh"}).status_code == 422  # 숫자 없음
    assert client.post("/api/auth/signup", json={**base, "password": "abc1"}).status_code == 422  # 8자 미만
    assert client.post("/api/auth/signup", json={**base, "password": "abc12345", "over_14": False}).status_code == 422


def test_requires_login(client):
    assert client.get("/api/projects").status_code == 401
    assert client.get("/api/projects", headers={"Authorization": "Bearer forged.token.value"}).status_code == 401


def test_update_me(client, auth):
    r = client.patch("/api/me", json={"name": "새이름", "daily_goal": 30}, headers=auth)
    assert r.json()["name"] == "새이름" and r.json()["daily_goal"] == 30
    assert client.patch("/api/me", json={"daily_goal": 0}, headers=auth).status_code == 422


# ---------- 문제: 정답은 풀기 전에 보이지 않는다 ----------
def test_problem_hides_answer(client, auth):
    p = client.get("/api/problems/pb_log", headers=auth).json()
    assert "answer" not in p and "solution" not in p
    assert len(client.get("/api/problems?domain=math", headers=auth).json()) == 5


# ---------- 프로젝트 ----------
def test_project_crud_and_scope_validation(client, auth):
    exam = (date.today() + timedelta(days=10)).isoformat()
    r = client.post("/api/projects", json={"name": "미적분", "subject_id": "math.calculus",
                                           "unit_ids": ["math.calculus.int_methods"], "exam_date": exam}, headers=auth)
    assert r.status_code == 201
    pid = r.json()["id"]

    bad = client.post("/api/projects", json={"name": "x", "subject_id": "math.calculus.int_methods"}, headers=auth)
    assert bad.status_code == 422  # 단원은 과목 자리에 못 옴
    bad = client.post("/api/projects", json={"name": "x", "subject_id": "math.calculus", "unit_ids": ["physics.physics1.matter_em"]}, headers=auth)
    assert bad.status_code == 422  # 다른 과목의 단원

    r = client.patch(f"/api/projects/{pid}", json={"pinned": True, "exam_date": None}, headers=auth)
    assert r.json()["pinned"] is True and r.json()["exam_date"] is None
    assert client.get(f"/api/projects/{pid}", headers=auth).json()["project"]["name"] == "미적분"


def test_other_users_data_is_invisible(client, auth, new_user):
    pid = client.post("/api/projects", json={"name": "내 것", "subject_id": "math.math1"}, headers=auth).json()["id"]
    other = new_user()
    assert client.get(f"/api/projects/{pid}", headers=other).status_code == 404
    assert client.delete(f"/api/projects/{pid}", headers=other).status_code == 404
    assert client.get("/api/projects", headers=other).json() == []
    assert client.post("/api/sessions", json={"text": "문제", "project_id": pid}, headers=other).status_code == 404


# ---------- 대화 ----------
def test_new_session_replies_with_matching_problems(client, auth):
    r = client.post("/api/sessions", json={"text": "화학 문제 2문제 내줘"}, headers=auth)
    assert r.status_code == 201
    body = r.json()
    assert [msg["role"] for msg in body["messages"]] == ["user", "ai"]
    problems = body["messages"][1]["problems"]
    assert len(problems) == 2 and all(p["domain"] == "chemistry" for p in problems)
    assert all(p["answer"] is None and p["attempt"] is None for p in problems)  # 풀기 전엔 정답 없음

    more = client.post(f"/api/sessions/{body['id']}/messages", json={"text": "물리 1문제"}, headers=auth).json()
    assert len(more) == 2 and more[1]["problems"][0]["domain"] == "physics"
    assert len(client.get(f"/api/sessions/{body['id']}", headers=auth).json()["messages"]) == 4


def test_project_session_uses_project_subject(client, auth):
    pid = client.post("/api/projects", json={"name": "지구", "subject_id": "earth_science.earth1"}, headers=auth).json()["id"]
    s = client.post("/api/sessions", json={"text": "3문제 내줘", "project_id": pid}, headers=auth).json()
    assert s["project_id"] == pid
    assert {p["domain"] for p in s["messages"][1]["problems"]} == {"earth_science"}


def test_rename_move_delete_session(client, auth):
    pid = client.post("/api/projects", json={"name": "P", "subject_id": "math.math1"}, headers=auth).json()["id"]
    sid = client.post("/api/sessions", json={"text": "로그 문제"}, headers=auth).json()["id"]
    assert client.patch(f"/api/sessions/{sid}", json={"title": "새 이름", "project_id": pid}, headers=auth).json()["project_id"] == pid
    r = client.patch(f"/api/sessions/{sid}", json={"project_id": None}, headers=auth).json()
    assert r["project_id"] is None and r["title"] == "새 이름"
    assert client.delete(f"/api/sessions/{sid}", headers=auth).status_code == 204
    assert client.get(f"/api/sessions/{sid}", headers=auth).status_code == 404


# ---------- 풀이 · 오답노트 ----------
def test_wrong_then_correct_resolves_note(client, auth, db):
    s = client.post("/api/sessions", json={"text": "로그 문제 1문제"}, headers=auth).json()
    pid = s["messages"][1]["problems"][0]["id"]
    answer = db.get(m.Problem, pid).answer

    r = client.post("/api/attempts", json={"problem_id": pid, "answer": wrong_choice(answer), "session_id": s["id"]}, headers=auth).json()
    assert r["correct"] is False and r["answer"] == answer and r["solution"] and r["wrong_note_id"]
    # 같은 문제를 또 틀려도 안 푼 오답은 하나
    client.post("/api/attempts", json={"problem_id": pid, "answer": wrong_choice(answer)}, headers=auth)
    notes = client.get("/api/wrong-notes", headers=auth).json()
    assert len(notes) == 1 and "answer" not in notes[0]["problem"]

    # 대화를 다시 열면 푼 기록과 정답·해설이 보인다
    view = client.get(f"/api/sessions/{s['id']}", headers=auth).json()["messages"][1]["problems"][0]
    assert view["attempt"] == {"answer": wrong_choice(answer), "correct": False} and view["answer"] == answer

    assert client.patch(f"/api/wrong-notes/{notes[0]['id']}", json={"error_type": "calculation"}, headers=auth).status_code == 200
    assert client.get("/api/wrong-notes?error_type=calculation", headers=auth).json()[0]["error_type"] == "calculation"

    r = client.post("/api/attempts", json={"problem_id": pid, "answer": answer}, headers=auth).json()
    assert r["correct"] is True and r["resolved"] is True
    assert client.get("/api/wrong-notes", headers=auth).json() == []
    assert len(client.get("/api/wrong-notes?open_only=false", headers=auth).json()) == 1
    assert client.get("/api/stats", headers=auth).json()["open_notes"] == 0


def test_attempt_rejects_foreign_session(client, auth, new_user):
    sid = client.post("/api/sessions", json={"text": "수학"}, headers=auth).json()["id"]
    other = new_user()
    r = client.post("/api/attempts", json={"problem_id": "pb_log", "answer": "3", "session_id": sid}, headers=other)
    assert r.status_code == 404


def test_delete_project_keeps_learning_history(client, auth, db):
    pid = client.post("/api/projects", json={"name": "P", "subject_id": "math.math1"}, headers=auth).json()["id"]
    sid = client.post("/api/sessions", json={"text": "로그", "project_id": pid}, headers=auth).json()["id"]
    client.post("/api/attempts", json={"problem_id": "pb_log", "answer": "1", "project_id": pid}, headers=auth)
    assert client.delete(f"/api/projects/{pid}", headers=auth).status_code == 204
    assert client.get(f"/api/sessions/{sid}", headers=auth).status_code == 404  # 대화는 함께 삭제
    notes = client.get("/api/wrong-notes", headers=auth).json()
    assert len(notes) == 1 and notes[0]["project_id"] is None  # 오답은 남고 프로젝트 연결만 끊김
    assert db.scalar(select(m.Attempt.project_id).where(m.Attempt.problem_id == "pb_log")) is None


# ---------- 통계 · 라이브러리 ----------
def test_stats_and_weak_concepts(client, auth):
    for ans in ("1", "1", "3"):  # pb_log 정답 3 → 3번 중 1번 맞힘
        client.post("/api/attempts", json={"problem_id": "pb_log", "answer": ans}, headers=auth)
    client.post("/api/attempts", json={"problem_id": "pb_kin", "answer": "3"}, headers=auth)
    st = client.get("/api/stats", headers=auth).json()
    assert st["today_count"] == 4 and st["streak"] == 1
    assert st["accuracy_by_domain"]["physics"] == 1.0 and st["accuracy_by_domain"]["biology"] is None
    weak = st["weak_concepts"][0]
    assert weak["concept_id"] == "math.math1.exp_log.log_properties" and weak["attempts"] == 3 and weak["correct"] == 1


def test_saved_problems(client, auth):
    assert client.put("/api/saved/pb_kin", headers=auth).status_code == 204
    assert client.put("/api/saved/pb_kin", headers=auth).status_code == 204  # 두 번 저장해도 하나
    assert [p["id"] for p in client.get("/api/saved", headers=auth).json()] == ["pb_kin"]
    assert client.put("/api/saved/nope", headers=auth).status_code == 404
    client.delete("/api/saved/pb_kin", headers=auth)
    assert client.get("/api/saved", headers=auth).json() == []


def test_cards(client, auth, db):
    me = client.get("/api/me", headers=auth).json()
    db.add(m.Card(user_id=me["id"], concept_id="math.math1.exp_log.log_properties", front="Q", back="A"))
    db.commit()
    card = client.get("/api/cards", headers=auth).json()[0]
    assert card["known"] is None
    assert client.patch(f"/api/cards/{card['id']}", json={"known": True}, headers=auth).json()["known"] is True
    client.post("/api/cards/reset", headers=auth)
    assert client.get("/api/cards", headers=auth).json()[0]["known"] is None


def test_concept_detail(client, auth):
    c = client.get("/api/concepts/chemistry.chemistry1.dynamic_reactions.neutralization", headers=auth).json()
    assert [x["level"] for x in c["path"]] == ["subject", "unit", "concept"]
    assert len(c["concept"]["prerequisites"]) == 2
    assert [p["id"] for p in c["problems"]] == ["pb_neut"] and c["problems"][0]["answer"] is None
    nxt = client.get("/api/concepts/math.math1.exp_log.exponent_rules", headers=auth).json()["next_concepts"]
    assert [x["id"] for x in nxt] == ["math.math1.exp_log.log_properties"]
    assert len(client.get("/api/concepts").json()) == 143


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_demo_account_seed_and_login(client, db):
    from education.seed import DEMO_EMAIL, DEMO_PASSWORD, seed_demo_user

    seed_demo_user(db)
    db.commit()
    r = client.post("/api/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert len(client.get("/api/projects", headers=h).json()) == 3
    assert len(client.get("/api/sessions", headers=h).json()) == 6
    assert client.get("/api/stats", headers=h).json()["open_notes"] == 3

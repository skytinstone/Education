"""문제 성적표 — 학생 실력을 감안한 문항 분석."""

import pytest

from education.config import get_settings
from education.services import item_stats
from education.services.item_stats import Item, observed_level, rasch

ADMIN = "admin@example.com"
LOG_CONCEPT = "math.math1.exp_log.log_properties"


@pytest.fixture(autouse=True)
def admins(monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_emails", ADMIN)


def test_rasch_separates_students_and_items():
    # 실력 순서대로 0~5개를 맞힌 학생 6명, 문제 5개 (쉬운 문제일수록 많이 맞힘)
    items = {f"q{j}": Item(f"q{j}", "math", 3, None, "") for j in range(5)}
    for u in range(6):
        for j in range(5):
            items[f"q{j}"].resp.append((u, j < u, ""))
    theta, b = rasch(items)
    assert theta[5] > theta[3] > theta[0]
    assert b["q0"] < b["q2"] < b["q4"]
    assert abs(sum(theta.values()) / len(theta)) < 1e-6  # 학생 평균 = 0
    assert observed_level(-3) == 1 and observed_level(3) == 5


def solve(client, headers, pid, answer):
    assert client.post("/api/attempts", json={"problem_id": pid, "answer": answer}, headers=headers).status_code == 201


def test_item_stats_flags_and_feedback(client, db, new_user):
    # 잘하는 학생 8명: 대부분 맞히는데 pb_seq 만 2번을 고른다 / 약한 학생 8명: 대부분 틀리는데 pb_seq 는 정답(3번)
    strong = [new_user() for _ in range(8)]
    weak = [new_user() for _ in range(8)]
    for h in strong:
        for pid, a in (("pb_log", "3"), ("pb_subst", "1"), ("pb_defint", "3"), ("pb_cond", "3"), ("pb_seq", "2")):
            solve(client, h, pid, a)
        solve(client, h, "pb_log", "1")  # 다시 푼 기록은 쓰지 않는다 (처음 푼 것만)
    for h in weak:
        for pid, a in (("pb_log", "1"), ("pb_subst", "2"), ("pb_defint", "1"), ("pb_cond", "1"), ("pb_seq", "3")):
            solve(client, h, pid, a)

    admin = new_user(name="운영자", email=ADMIN)
    assert client.post("/api/admin/item-stats/refresh", headers=strong[0]).status_code == 404  # 운영자가 아니면 있는지도 알리지 않는다
    r = client.post("/api/admin/item-stats/refresh", headers=admin)
    assert r.status_code == 200 and r.json()["problems"] == 5

    data = client.get("/api/admin/item-stats", headers=admin).json()
    by_id = {x["problem_id"]: x for x in data["items"]}
    log, seq = by_id["pb_log"], by_id["pb_seq"]
    # pb_log: 잘하는 학생만 맞힘 → 변별력 높음 · 처음 풀이만 셈 · 의도(1)보다 어려움 · 2·4·5번은 아무도 안 고름
    assert log["n"] == 16 and log["p"] == 0.5 and log["disc"] > 0.8
    assert "harder_than_meant" in log["flags"] and "dead_choice" in log["flags"]
    assert [c["n"] for c in log["choices"]] == [8, 0, 8, 0, 0]
    assert log["choices"][2]["ability"] > 0 > log["choices"][0]["ability"]
    # pb_seq: 잘하는 학생이 오답 보기를 더 많이 고름 → 정답 의심 · D 등급이 맨 앞
    assert {"neg_disc", "key_suspect"} <= set(seq["flags"]) and seq["grade"] == "D"
    assert data["items"][0]["grade"] == "D"
    only_d = client.get("/api/admin/item-stats", params={"flag": "key_suspect"}, headers=admin).json()["items"]
    assert [x["problem_id"] for x in only_d] == ["pb_seq"]

    # 문제 생성이 참고할 개념 요약
    fb = item_stats.concept_feedback(db, LOG_CONCEPT)
    assert "난이도 1로 낸 문제" in fb and "효과적이었던 함정" in fb and "아무도 고르지 않은 보기" in fb
    assert item_stats.concept_feedback(db, "math.math1.trig.radian_trig_def") == ""


def test_item_stats_need_enough_students(client, db, new_user):
    for _ in range(3):
        solve(client, new_user(), "pb_kin", "3")
    assert item_stats.refresh(db)["problems"] == 0  # 5명 미만이면 매기지 않는다

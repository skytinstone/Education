"""AI 면접 모드 — 말로 보는 시험(OPIc 대비, 직무 면접, 편입·의전원 면접)을 연습한다.

흐름: 설정 → 질문 → (준비 시간) → 말로 답변 → 꼬리질문 → … → 리포트.
- 소리는 브라우저가 듣고 글로 바꾼다 (Web Speech API). 서버는 받아쓴 글과 걸린 시간만 받는다 — 녹음은 오지도, 남지도 않는다.
- 질문 계획·꼬리질문·리포트는 AI 가 만든다. AI 가 없거나 오늘 한도를 넘으면 내장 질문 은행과
  '말의 양·속도·군말' 측정값만으로 리포트를 만든다 (그렇다고 리포트에 적는다).
- 종류는 KINDS 에 한 줄씩 더한다 — 설정 칸, 질문 수, 준비·답변 시간, 등급 이름, 평가 기준, 내장 질문.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from education.config import get_settings
from education.db import models as m
from education.services import quota
from education.services.llm import LLMError, get_llm


# ---------------------------------------------------------------- 종류

@dataclass(frozen=True)
class SetupField:
    key: str
    label: str
    placeholder: str = ""
    kind: str = "text"            # text · textarea · select
    options: tuple[str, ...] = ()
    required: bool = False
    max_len: int = 200


@dataclass(frozen=True)
class Kind:
    key: str
    name: str
    desc: str
    lang: str                     # 답변 언어 — en(영어로 말하기) · ko
    mains: int                    # 본 질문 수
    follow_ups: int               # 꼬리질문 최대 수 (AI 가 있을 때만)
    prep_sec: int                 # 질문 뒤 준비 시간
    answer_sec: int               # 답변 시간 (넘으면 저절로 멈춤)
    fields: tuple[SetupField, ...]
    levels: tuple[str, ...]       # 낮은 것 → 높은 것. 비어 있으면 100점 만점 점수만
    guide: str                    # AI 에게 줄 이 시험의 형식·평가 기준
    bank: Callable[[dict, random.Random], list[str]]  # AI 없이 쓸 본 질문 (mains 개)
    level_note: str = ""          # 리포트에 붙는 안내 (예: 공식 등급이 아님)


HOME_EN = {"가족과 함께": "with your family", "혼자": "alone", "친구·룸메이트와": "with friends or roommates", "기숙사": "in a dormitory"}


def _opic_bank(setup: dict, rnd: random.Random) -> list[str]:
    hobby = (setup.get("hobbies") or "").split(",")[0].strip()
    if not hobby or re.search(r"[가-힣]", hobby):  # 영어 질문에 한글을 끼우지 않는다 (AI 가 있으면 AI 가 번역해 묻는다)
        hobby = "your favorite free-time activity"
    home = HOME_EN.get(setup.get("home") or "", "")
    pool = [
        f"You indicated in the survey that you enjoy {hobby}. Why do you like it? Describe what you usually do, in as much detail as possible.",
        f"Tell me about a memorable experience related to {hobby}. What happened, who were you with, and why was it so memorable?",
        "Tell me about your home" + (f" — you said you live {home}" if home else "") + ". What does it look like? Describe your favorite room in detail.",
        "Describe a typical day for you, from the moment you wake up until you go to bed.",
        "I'd like to give you a situation to act out. You want to book a table at a restaurant for a friend's birthday. "
        "Call the restaurant and ask three or four questions to make the reservation.",
        "Compare how people in your country spent their free time in the past with how they spend it now. What has changed, and why?",
        "Tell me about a place you like to visit in your neighborhood. What is it like, and what do you do there?",
        "Talk about a time when something unexpected happened while you were traveling. How did you handle it?",
    ]
    rnd.shuffle(pool)
    return ["Let's start the interview now. Tell me a little bit about yourself.", *pool[:5]]


OPIC = Kind(
    key="opic", name="OPIc 영어", lang="en",
    desc="배경 설문에 맞춘 질문에 영어로 2분씩 답해요. 자기소개 · 묘사 · 경험 · 롤플레이 · 비교",
    mains=6, follow_ups=2, prep_sec=20, answer_sec=120,
    fields=(
        SetupField("role", "지금 하는 일", kind="select", options=("학생", "직장인", "구직 중"), required=True),
        SetupField("home", "사는 곳", kind="select", options=("가족과 함께", "혼자", "친구·룸메이트와", "기숙사")),
        SetupField("hobbies", "좋아하는 활동 (쉼표로)", "movies, jogging, cafés · 한국어로 적어도 돼요", max_len=120),
        SetupField("target", "목표 등급", kind="select", options=("IM2", "IM3", "IH", "AL")),
    ),
    levels=("NL", "NM", "NH", "IL", "IM1", "IM2", "IM3", "IH", "AL"),
    level_note="예상 등급이에요. 실제 OPIc 등급과 다를 수 있어요.",
    guide=(
        "OPIc(외국어 말하기 평가) 대비 모의 인터뷰다. 질문은 모두 영어. 배경 설문(하는 일·사는 곳·좋아하는 활동)에 맞춘 "
        "자기소개, 묘사, 과거 경험, 롤플레이(상황극), 비교·사회 이슈 질문을 섞는다. "
        "평가는 ACTFL 기준을 따른다: 과제 수행(묘사·서술·비교·문제 해결), 문장 길이와 연결(문장 → 문단), 시제 정확성, "
        "어휘 다양성, 유창성(머뭇거림·반복), 내용의 구체성. 등급은 NL·NM·NH·IL·IM1·IM2·IM3·IH·AL 중 하나."
    ),
    bank=_opic_bank,
)


def _job_bank(setup: dict, rnd: random.Random) -> list[str]:
    job = setup.get("job") or "지원하신 직무"
    company = setup.get("company") or "저희 회사"
    senior = setup.get("career") == "경력"
    pool = [
        f"{company}에 지원하신 이유와, 입사 후 {job}로서 가장 먼저 이루고 싶은 것을 말씀해 주세요.",
        f"{job} 직무와 가장 관련 있는 경험 하나를 골라, 상황·맡은 일·한 행동·결과 순서로 설명해 주세요.",
        "함께 일하던 사람과 의견이 크게 달랐던 적이 있나요? 어떻게 풀었는지 구체적으로 말씀해 주세요.",
        "가장 크게 실패했던 경험과, 그 뒤로 일하는 방식에서 무엇이 달라졌는지 말씀해 주세요.",
        ("이전 회사에서 낸 가장 큰 성과를 숫자로 설명해 주시고, 그 성과에서 본인의 기여가 어디까지였는지 말씀해 주세요."
         if senior else "본인의 강점 하나와 약점 하나를, 실제 있었던 일로 보여 주세요."),
        f"5년 뒤 {job}로서 어떤 모습이고 싶은지, 그걸 위해 지금 무엇을 하고 있는지 말씀해 주세요.",
        "마감이 겹쳐 모든 일을 제때 끝낼 수 없을 때, 우선순위를 어떻게 정하시나요? 실제 예로 말씀해 주세요.",
    ]
    rnd.shuffle(pool)
    return ["먼저 1분 동안 자기소개를 부탁드립니다.", *pool[:4], "마지막으로 하고 싶은 말씀이 있으면 해 주세요."]


JOB = Kind(
    key="job", name="직무 면접", lang="ko",
    desc="채용 공고와 자기소개서에 맞춘 질문에 1분 30초씩 답해요. 자기소개 · 지원 동기 · 직무 경험 · 협업 · 실패 경험",
    mains=6, follow_ups=3, prep_sec=15, answer_sec=90,
    fields=(
        SetupField("job", "지원 직무", "백엔드 개발자, 마케터, 회계 …", required=True, max_len=60),
        SetupField("company", "회사 (선택)", "회사 이름", max_len=60),
        SetupField("career", "구분", kind="select", options=("신입", "경력")),
        SetupField("jd", "채용 공고 (선택)", "자격 요건 · 우대 사항 · 하는 일을 붙여 넣으면 거기에 맞춰 물어요", kind="textarea", max_len=3000),
        SetupField("resume", "자기소개서·경력 요약 (선택)", "쓴 내용을 바탕으로 꼬리질문을 해요", kind="textarea", max_len=3000),
    ),
    levels=(),
    guide=(
        "한국 기업의 구조화 직무 면접이다. 질문은 한국어 존댓말. 1분 자기소개, 지원 동기, 직무 관련 경험(STAR: 상황·과제·행동·결과), "
        "협업·갈등, 실패와 배운 점, 마지막 한마디를 다룬다. 채용 공고가 있으면 자격 요건·우대 사항을 확인하는 질문을, "
        "자기소개서가 있으면 그 안의 경험을 파고드는 질문을 섞는다. "
        "평가 기준: 두괄식(결론 먼저), STAR 구조, 직무 연관성, 구체성(숫자·고유한 사례), 자기소개서와의 일관성, 답변 길이(1분 30초 안팎), "
        "태도(책임 전가·남 탓 없음). 점수는 100점 만점."
    ),
    bank=_job_bank,
)


# 전공 기초 구술 — 전공 이름에 이 말이 들어 있으면 그 질문을 쓴다 (없으면 일반 질문)
MAJOR_ORAL = {
    "전자": "전압과 전류, 저항의 관계를 설명하고, 실제 회로에서 옴의 법칙이 잘 맞지 않는 경우를 예로 들어 주세요.",
    "전기": "교류와 직류의 차이를 설명하고, 전력을 멀리 보낼 때 왜 높은 전압을 쓰는지 말씀해 주세요.",
    "컴퓨터": "자료구조에서 배열과 연결 리스트의 차이를 설명하고, 각각 언제 쓰는 게 좋은지 예를 들어 주세요.",
    "소프트웨어": "시간 복잡도가 무엇인지, O(n log n) 정렬이 O(n²) 정렬보다 왜 유리한지 설명해 주세요.",
    "기계": "열역학 제1법칙과 제2법칙을 설명하고, 자동차 엔진의 효율이 100%가 될 수 없는 이유를 말씀해 주세요.",
    "화학": "화학 평형과 르샤틀리에 원리를 설명하고, 일상에서 볼 수 있는 예를 하나 들어 주세요.",
    "생명": "DNA 복제와 전사의 차이를 설명하고, 돌연변이가 단백질 기능에 어떤 영향을 줄 수 있는지 말씀해 주세요.",
    "수학": "미분의 정의를 극한으로 설명하고, 미분 가능하지 않은 연속 함수의 예를 들어 주세요.",
    "물리": "뉴턴의 운동 법칙 세 가지를 설명하고, 로켓이 우주에서 앞으로 나아가는 원리를 말씀해 주세요.",
    "경영": "기업의 가치를 평가하는 방법 두 가지를 설명하고, 각각의 장단점을 말씀해 주세요.",
    "경제": "기회비용과 매몰비용의 차이를 설명하고, 실제 의사 결정에서 매몰비용에 휘둘린 예를 들어 주세요.",
    "간호": "감염 관리에서 표준 주의 지침이 무엇인지, 왜 모든 환자에게 적용하는지 설명해 주세요.",
}


def _admission_bank(setup: dict, rnd: random.Random) -> list[str]:
    track = setup.get("track") or "학사편입"
    major = setup.get("major") or "지원 전공"
    school = setup.get("school") or "우리 학교"
    medical = track.startswith("의")
    oral = next((q for k, q in MAJOR_ORAL.items() if k in major),
                f"{major}에서 가장 기초가 된다고 생각하는 개념 하나를 골라, 처음 배우는 사람에게 설명하듯 말씀해 주세요.")
    pool = [
        f"{major} 공부를 하면서 가장 어려웠던 부분과, 그걸 어떻게 극복했는지 말씀해 주세요.",
        "최근 관심 있게 본 사회 이슈 하나를 골라, 본인의 생각과 근거를 말씀해 주세요.",
        "팀 과제에서 맡은 역할과, 의견이 맞지 않았을 때 어떻게 했는지 말씀해 주세요.",
        f"입학 후 {major}에서 가장 깊이 공부하고 싶은 분야와 그 이유를 말씀해 주세요.",
    ]
    if medical:
        pool.append("좋은 의사에게 가장 필요한 자질 하나를 고르고, 본인이 그 자질을 보여 준 경험을 말씀해 주세요.")
    rnd.shuffle(pool)
    first = (f"{school} {major}에 지원한 동기와, " + ("의사가 되려는 이유를 함께 말씀해 주세요." if medical
             else "지금까지의 공부가 이 전공과 어떻게 이어지는지 말씀해 주세요."))
    picks = pool[:3]
    if medical:  # 의·치의학전문대학원은 의료 윤리·상황 판단 질문을 꼭 하나 (MMI)
        picks[-1] = rnd.choice(ETHICS)
    return ["간단히 자기소개를 부탁드립니다.", first, oral, *picks][:6]


ETHICS = (
    "환자가 치료를 거부하는데 치료하지 않으면 생명이 위험한 상황입니다. 의사로서 어떻게 하시겠습니까?",
    "의료 자원이 부족해 두 환자 중 한 명만 먼저 치료할 수 있다면, 무엇을 기준으로 결정하겠습니까?",
    "동료 의사가 술을 마신 상태로 진료하려는 것을 보았습니다. 어떻게 하시겠습니까?",
)


ADMISSION = Kind(
    key="admission", name="편입·의전원 면접", lang="ko",
    desc="전형과 전공에 맞춘 질문에 2분씩 답해요. 지원 동기 · 학업 계획 · 전공 구술 · 상황·윤리 · 인성",
    mains=6, follow_ups=2, prep_sec=30, answer_sec=120,
    fields=(
        SetupField("track", "전형", kind="select", options=("학사편입", "의·치의학전문대학원", "대학원", "대학 수시"), required=True),
        SetupField("school", "지원 학교 (선택)", "고려대학교", max_len=60),
        SetupField("major", "지원 전공", "전자전기공학부, 의학과 …", required=True, max_len=60),
        SetupField("resume", "자기소개서·학업계획서 (선택)", "쓴 내용을 바탕으로 꼬리질문을 해요", kind="textarea", max_len=3000),
    ),
    levels=(),
    guide=(
        "한국 대학의 편입·전문대학원·대학원·수시 면접이다. 질문은 한국어 존댓말. 지원 동기와 학업 계획, 전공 기초 구술(개념을 말로 설명), "
        "인성·협업, 시사 이슈를 다루고, 의·치의학전문대학원이면 의료 윤리·상황 판단 질문(MMI 방식)을 반드시 하나 이상 넣는다. "
        "서류(자기소개서·학업계획서)가 있으면 그 내용을 확인하고 파고든다. "
        "평가 기준: 결론을 먼저 말하는 논리 구조, 전공 개념 설명의 정확성(틀린 개념은 분명히 짚는다), 학업 의지와 계획의 구체성, "
        "서류와의 일관성, 윤리 질문에서 여러 입장을 고려하는 균형. 점수는 100점 만점."
    ),
    bank=_admission_bank,
)

KINDS: dict[str, Kind] = {k.key: k for k in (OPIC, JOB, ADMISSION)}


# ---------------------------------------------------------------- 측정 (AI 없이도)

FILLERS = {
    "en": re.compile(r"\b(um+|uh+|erm|hmm+|like|you know|i mean|basically|actually|kind of|sort of)\b", re.I),
    "ko": re.compile(r"(?<![가-힣])(음+|어+|그+|저+|뭐랄까|약간|이제|그러니까|뭔가)(?![가-힣])"),
}


def measure(text: str, sec: int, lang: str) -> dict:
    """답 하나의 말의 양·속도·군말. 영어는 단어/분, 한국어는 음절/분."""
    t = (text or "").strip()
    words = len(re.findall(r"[A-Za-z']+", t)) if lang == "en" else len(t.split())
    syll = len(re.findall(r"[가-힣]", t))
    mins = max(sec, 1) / 60
    fillers = [f.lower() for f in (FILLERS[lang].findall(t) if t else [])]
    fillers = [f if isinstance(f, str) else f[0] for f in fillers]
    return {"words": words, "syllables": syll, "sec": sec,
            "rate": round((words if lang == "en" else syll) / mins) if t and sec >= 5 else None,
            "fillers": len(fillers), "filler_words": sorted(set(fillers))[:6]}


def summary_metrics(turns: list[dict], lang: str) -> dict:
    done = [t for t in turns if t.get("ans") is not None]
    ms = [measure(t["ans"], t.get("sec") or 0, lang) for t in done]
    answered = [x for x in ms if x["words"]]
    rates = [x["rate"] for x in answered if x["rate"]]
    words: dict[str, int] = {}
    for t in done:
        for f in FILLERS[lang].findall(t["ans"] or ""):
            f = (f if isinstance(f, str) else f[0]).lower()
            words[f] = words.get(f, 0) + 1
    return {
        "answered": len(answered), "total": len(done), "skipped": len(done) - len(answered),
        "avg_words": round(sum(x["words"] for x in answered) / len(answered)) if answered else 0,
        "avg_sec": round(sum(x["sec"] for x in answered) / len(answered)) if answered else 0,
        "rate": round(sum(rates) / len(rates)) if rates else None,
        "rate_unit": "단어/분" if lang == "en" else "음절/분",
        "fillers": sum(words.values()), "top_fillers": sorted(words, key=lambda k: -words[k])[:5],
    }


# ---------------------------------------------------------------- AI 응답 형식

class Plan(BaseModel):
    questions: list[str] = Field(description="본 질문들, 순서대로")


class FollowUp(BaseModel):
    ask: bool = Field(description="꼬리질문이 필요하면 true")
    question: str = Field(description="꼬리질문 (ask 가 false 면 빈 문자열)")


class ItemFeedback(BaseModel):
    score: int = Field(description="이 답의 점수 0~100")
    feedback: str = Field(description="잘한 점과 고칠 점을 2~4문장으로, 구체적으로")
    better: str = Field(description="같은 내용을 더 잘 말한 모범 답변 (답변 언어로)")


class Report(BaseModel):
    level: str = Field(description="등급 이름 (등급 목록이 없으면 빈 문자열)")
    score: int = Field(description="전체 점수 0~100")
    summary: str = Field(description="전체 총평 2~3문장 (한국어)")
    strengths: list[str] = Field(description="잘한 점 2~4개 (한국어, 짧게)")
    improve: list[str] = Field(description="가장 먼저 고칠 점 2~4개 (한국어, 바로 연습할 수 있게)")
    items: list[ItemFeedback] = Field(description="질문 순서대로 하나씩")


def _ai(db: Session, user: m.User, purpose: str, *, model: str, effort: str, instructions: str, prompt: str,
        schema, max_tokens: int = 6000):
    """AI 를 한 번 부른다. 키가 없거나, 오늘 한도를 넘었거나, 실패하면 None (부른 쪽이 AI 없는 길로 간다)."""
    llm = get_llm()
    if llm is None or quota.exceeded(db, user):
        return None
    try:
        res = llm.structured(model=model, effort=effort, instructions=instructions, prompt=prompt, schema=schema,
                             max_output_tokens=max_tokens)
    except LLMError as e:
        db.add(m.LLMCall(purpose=purpose, model=model, ok=False, error=str(e)[:500], user_id=user.id))
        db.flush()
        return None
    u = res.usage
    db.add(m.LLMCall(purpose=purpose, model=u.model, ok=True, user_id=user.id, cost_usd=u.cost_usd,
                     input_tokens=u.input_tokens, cached_tokens=u.cached_tokens, output_tokens=u.output_tokens,
                     reasoning_tokens=u.reasoning_tokens, latency_ms=u.latency_ms))
    db.flush()
    return res.data


def _setup_text(kind: Kind, setup: dict) -> str:
    rows = [f"- {f.label}: {setup[f.key]}" for f in kind.fields if setup.get(f.key)]
    return "\n".join(rows) or "- (설정 없음)"


def _lang_rule(kind: Kind) -> str:
    return "질문은 영어로 쓴다." if kind.lang == "en" else "질문은 한국어 존댓말로 쓴다."


def clean_setup(kind: Kind, raw: dict) -> dict:
    out = {}
    for f in kind.fields:
        v = str(raw.get(f.key) or "").strip()[: f.max_len]
        if f.kind == "select" and v and v not in f.options:
            v = ""
        if v:
            out[f.key] = v
    return out


def missing_fields(kind: Kind, setup: dict) -> list[str]:
    return [f.label for f in kind.fields if f.required and not setup.get(f.key)]


# ---------------------------------------------------------------- 진행

def start(db: Session, user: m.User, kind: Kind, setup: dict) -> m.Interview:
    s = get_settings()
    plan = _ai(db, user, "interview_plan", model=s.openai_model_route, effort="low",
               instructions=(f"너는 {kind.name} 면접관이다. {kind.guide}\n"
                             f"지원자 정보에 맞춘 본 질문을 정확히 {kind.mains}개 만든다. 첫 질문은 가벼운 자기소개. "
                             f"각 질문은 한두 문장, {kind.answer_sec // 60}분 안에 답할 수 있게. {_lang_rule(kind)}"),
               prompt=f"지원자 정보:\n{_setup_text(kind, setup)}", schema=Plan, max_tokens=3000)
    questions = [q.strip() for q in (plan.questions if plan else []) if q.strip()][: kind.mains]
    by_ai = len(questions) == kind.mains
    if not by_ai:
        questions = kind.bank(setup, random.Random())[: kind.mains]
    iv = m.Interview(user_id=user.id, kind=kind.key, lang=kind.lang, setup=setup, plan=questions,
                     turns=[{"q": questions[0], "follow": False, "ans": None, "sec": 0}], status="active",
                     by_ai=by_ai)
    db.add(iv)
    db.flush()
    return iv


def current(iv: m.Interview) -> int | None:
    return next((i for i, t in enumerate(iv.turns) if t.get("ans") is None), None)


def answer(db: Session, user: m.User, iv: m.Interview, text: str, sec: int) -> None:
    kind = KINDS[iv.kind]
    i = current(iv)
    if i is None:
        return
    turns = [dict(t) for t in iv.turns]
    turns[i].update(ans=text.strip(), sec=sec, at=datetime.now(timezone.utc).isoformat())
    nxt = None
    t = turns[i]
    follows_used = sum(1 for x in turns if x.get("follow"))
    # 본 질문에 제대로 답했으면, 꼬리질문이 남아 있을 때 AI 에게 물을지 맡긴다
    if not t["follow"] and t["ans"] and follows_used < kind.follow_ups and i > 0:
        s = get_settings()
        f = _ai(db, user, "interview_follow", model=s.openai_model_route, effort="low",
                instructions=(f"너는 {kind.name} 면접관이다. {kind.guide}\n"
                              "지원자의 방금 답을 듣고, 더 깊이 확인할 가치가 있을 때만 꼬리질문을 하나 한다 "
                              "(구체적 경험·근거·수치를 묻거나, 모호한 부분을 짚는다). 이미 충분하면 ask=false. "
                              f"남은 꼬리질문 {kind.follow_ups - follows_used}개. {_lang_rule(kind)}"),
                prompt=f"지원자 정보:\n{_setup_text(kind, iv.setup)}\n\n질문: {t['q']}\n답: {t['ans'][:3000]}",
                schema=FollowUp, max_tokens=800)
        if f and f.ask and f.question.strip():
            nxt = {"q": f.question.strip()[:600], "follow": True, "ans": None, "sec": 0}
    if nxt is None:
        mains_done = sum(1 for x in turns if not x.get("follow"))
        if mains_done < len(iv.plan):
            nxt = {"q": iv.plan[mains_done], "follow": False, "ans": None, "sec": 0}
    if nxt:
        turns.append(nxt)
    else:
        iv.status = "answered"
    iv.turns = turns
    db.flush()


def _heuristic_level(kind: Kind, metrics: dict) -> tuple[str, int]:
    """AI 없이: 답의 길이·속도로 어림한 등급·점수 (답의 내용은 보지 않는다)."""
    w = metrics["avg_words"]
    base = min(100, round(w / (1.3 if kind.lang == "en" else 0.9)))
    if metrics["skipped"]:
        base = round(base * metrics["answered"] / max(metrics["total"], 1))
    if not kind.levels:
        return "", base
    cuts = [0, 8, 15, 25, 40, 60, 85, 115, 999]  # 평균 단어 수 기준 (AL 은 AI 평가로만)
    idx = max(i for i, c in enumerate(cuts) if w >= c)
    return kind.levels[min(idx, len(kind.levels) - 2)], base


def finish(db: Session, user: m.User, iv: m.Interview) -> None:
    if iv.status == "done":
        return
    kind = KINDS[iv.kind]
    turns = [t for t in iv.turns if t.get("ans") is not None]
    metrics = summary_metrics(turns, kind.lang)
    s = get_settings()
    rep = None
    if metrics["answered"]:
        qa = "\n\n".join(f"[{i + 1}{' · 꼬리질문' if t.get('follow') else ''}] 질문: {t['q']}\n답 ({t.get('sec', 0)}초): {t['ans'] or '(답하지 않음)'}"
                         for i, t in enumerate(turns))
        rep = _ai(db, user, "interview_report", model=s.openai_model_generate, effort="low",
                  instructions=(f"너는 {kind.name} 평가 전문가다. {kind.guide}\n"
                                "답은 브라우저 음성 인식으로 받아쓴 글이라 맞춤법·띄어쓰기·구두점 오류는 감점하지 않는다. "
                                f"{'등급은 다음 중 하나: ' + ', '.join(kind.levels) + '.' if kind.levels else '등급 없이 점수만 매긴다 (level 은 빈 문자열).'} "
                                "피드백·총평은 한국어, 모범 답변(better)은 답변 언어로 쓴다. "
                                "items 는 질문 수와 같은 개수로, 답하지 않은 질문은 0점과 함께 모범 답변만 준다."),
                  prompt=(f"지원자 정보:\n{_setup_text(kind, iv.setup)}\n\n측정값: 평균 {metrics['avg_words']}"
                          f"{'단어' if kind.lang == 'en' else '어절'}, 말 속도 {metrics['rate']} {metrics['rate_unit']}, "
                          f"군말 {metrics['fillers']}번\n\n{qa}"),
                  schema=Report, max_tokens=12000)
    if rep and len(rep.items) == len(turns):
        level = rep.level if rep.level in kind.levels else (kind.levels[0] if kind.levels and not metrics["answered"] else rep.level)
        report = {"by_ai": True, "level": level if kind.levels else "", "score": max(0, min(100, rep.score)),
                  "summary": rep.summary, "strengths": rep.strengths[:4], "improve": rep.improve[:4],
                  "items": [{"score": max(0, min(100, x.score)), "feedback": x.feedback, "better": x.better} for x in rep.items]}
    else:
        level, score = _heuristic_level(kind, metrics)
        tips = []
        if metrics["avg_words"] < (60 if kind.lang == "en" else 45):
            tips.append("답이 짧아요. 이유 → 구체적인 예 → 느낀 점 순서로 한두 문장씩 더 붙여 보세요")
        if metrics["fillers"] >= max(3, metrics["answered"]):
            tips.append(f"'{', '.join(metrics['top_fillers'][:3])}' 같은 군말이 자주 나와요. 잠깐 멈추는 편이 더 자연스러워요")
        if metrics["rate"] and metrics["rate"] < (90 if kind.lang == "en" else 200):
            tips.append("말이 조금 느려요. 같은 답을 두세 번 소리 내 연습하면 빨라져요")
        if metrics["skipped"]:
            tips.append(f"답하지 않은 질문이 {metrics['skipped']}개 있어요. 모르는 주제도 아는 경험에 이어서 답해 보세요")
        report = {"by_ai": False, "level": level, "score": score,
                  "summary": "AI 평가 없이 말의 양·속도·군말만으로 어림한 결과예요. 내용과 문법은 보지 않았어요.",
                  "strengths": ["모든 질문에 답했어요"] if not metrics["skipped"] and metrics["answered"] else [],
                  "improve": tips or ["좋아요. 다음에는 더 어려운 질문으로 연습해 보세요"],
                  "items": [{"score": None, "feedback": "", "better": ""} for _ in turns]}
    report["metrics"] = metrics
    report["per"] = [measure(t["ans"], t.get("sec") or 0, kind.lang) for t in turns]
    iv.report = report
    iv.status = "done"
    iv.finished_at = datetime.now(timezone.utc)
    db.flush()

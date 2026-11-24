"""AI 면접 모드 — 말로 보는 시험(OPIc 대비, 직무 면접, 편입·의전원 면접)을 연습한다.

흐름: 설정 → 질문 → (준비 시간) → 말로 답변 → 꼬리질문 → … → 리포트.
- 소리는 브라우저가 듣고 글로 바꾼다 (Web Speech API). 서버는 받아쓴 글과 걸린 시간만 받는다 — 녹음은 오지도, 남지도 않는다.
- 질문 계획·꼬리질문·리포트는 AI 가 만든다. AI 가 없거나 오늘 한도를 넘으면 내장 질문 은행과
  '말의 양·속도·군말' 측정값만으로 리포트를 만든다 (그렇다고 리포트에 적는다).
- 종류는 KINDS 에 한 줄씩 더한다 — 설정 칸, 질문 수, 준비·답변 시간, 등급 이름, 평가 기준, 내장 질문.
"""

from __future__ import annotations

import difflib
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
class Slot:
    """본 질문 자리 하나 — 파트 이름·준비/답변 시간, AI 가 이 자리에 맞는 질문을 만들도록 주는 설명."""
    part: str
    prep: int
    answer: int
    hint: str = ""


@dataclass(frozen=True)
class Kind:
    key: str
    name: str
    desc: str
    lang: str                     # 답변 언어 — en(영어로 말하기) · ko
    mains: int                    # 본 질문 수
    follow_ups: int               # 꼬리질문 최대 수 (AI 가 있을 때만)
    prep_sec: int                 # 질문 뒤 준비 시간 (자리·문항에 따로 없을 때)
    answer_sec: int               # 답변 시간 (넘으면 저절로 멈춤)
    fields: tuple[SetupField, ...]
    levels: tuple[str, ...]       # 낮은 것 → 높은 것. 비어 있으면 100점 만점 점수만
    guide: str                    # AI 에게 줄 이 시험의 형식·평가 기준
    # AI 없이 쓸 본 질문 (mains 개). 글자 하나 또는 {q, part, prep, answer, material}
    bank: Callable[[dict, random.Random], list]
    level_note: str = ""          # 리포트에 붙는 안내 (예: 공식 등급이 아님)
    slots: tuple[Slot, ...] = ()  # 자리마다 파트·시간이 정해진 형식 (AI 역량검사 등)
    fixed: bool = False           # 정해진 시험 형식(지문·사진·표) — 늘 내장 문항을 쓰고 AI 는 평가만
    time_note: str = ""           # 카드에 보일 시간 안내 (문항마다 다를 때)


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


RESUME_HINTS = re.compile(r"프로젝트|경험|담당|맡|개선|성과|해결|주도|협업|갈등|실패|배웠|배운|도전|리더|팀|인턴|동아리|개발|분석|기획|고객|"
                          r"운영|설계|제안|달성|줄였|늘렸|높였|만들|이끌|\d")


def resume_snippets(text: str, n: int = 3) -> list[str]:
    """자기소개서에서 면접관이 파고들 만한 문장 (경험·행동·숫자가 있는 것) n 개를 원래 순서대로."""
    sents = [x.strip(" \t-•·*\"'“”") for x in re.split(r"(?<=[.!?。])\s+|(?<=다\.)|\n+", text or "")]
    sents = [x for x in sents if 15 <= len(x) <= 220]
    scored = sorted(enumerate(sents), key=lambda p: -(len(RESUME_HINTS.findall(p[1])) + (2 if re.search(r"\d", p[1]) else 0)))
    best = sorted([p for p in scored if RESUME_HINTS.search(p[1])][:n])
    return [(x if len(x) <= 70 else x[:68].rstrip() + "…") for _, x in best]


RESUME_TEMPLATES = (
    "자기소개서에 「{s}」라고 쓰셨는데, 그때 본인이 맡은 역할과 직접 한 행동을 구체적으로 말씀해 주세요.",
    "「{s}」 부분에서 가장 어려웠던 점은 무엇이었고, 어떻게 해결하셨나요?",
    "「{s}」라고 하셨는데, 그 결과를 숫자나 사실로 보여 주실 수 있나요? 다시 한다면 무엇을 바꾸시겠어요?",
)


def resume_questions(resume: str, rnd: random.Random, n: int = 3) -> list[dict]:
    """자기소개서 문장을 근거로 한 질문 — {q, basis}. 화면에 '자기소개서의 어느 문장에서 나온 질문인지' 보여 준다."""
    snips = resume_snippets(resume, n)
    tpl = list(RESUME_TEMPLATES)
    rnd.shuffle(tpl)
    return [{"q": tpl[i % len(tpl)].format(s=x), "basis": x} for i, x in enumerate(snips)]


def _job_bank(setup: dict, rnd: random.Random) -> list:
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
    from_resume = resume_questions(setup.get("resume", ""), rnd, 3)
    middle = [pool[0] if "지원하신 이유" in pool[0] else next(q for q in pool if "지원하신 이유" in q), *from_resume]
    middle += [q for q in pool if q not in middle][: 4 - len(middle)]
    return ["먼저 1분 동안 자기소개를 부탁드립니다.", *middle[:4], "마지막으로 하고 싶은 말씀이 있으면 해 주세요."]


JOB = Kind(
    key="job", name="직무 면접", lang="ko",
    desc="채용 공고와 자기소개서에 맞춘 질문에 1분 30초씩 답해요. 자기소개 · 지원 동기 · 직무 경험 · 협업 · 실패 경험",
    mains=6, follow_ups=3, prep_sec=15, answer_sec=90,
    fields=(
        SetupField("company", "지원 회사", "삼성전자, 네이버, 토스 …", max_len=60),
        SetupField("job", "지원 직무", "백엔드 개발자, 마케터, 회계 …", required=True, max_len=60),
        SetupField("career", "구분", kind="select", options=("신입", "경력")),
        SetupField("jd", "채용 공고 (선택)", "자격 요건 · 우대 사항 · 하는 일을 붙여 넣으면 거기에 맞춰 물어요", kind="textarea", max_len=3000),
        SetupField("resume", "자기소개서", "자기소개서를 붙여 넣으면 그 안의 경험·성과 문장을 읽고 파고드는 질문을 만들어요. "
                   "(지원 동기 · 직무 경험 · 협업 · 성장 과정 등 항목 그대로)", kind="textarea", max_len=6000),
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
    plan_q = resume_questions(setup.get("resume", ""), rnd, 1)
    if plan_q:
        picks[0] = plan_q[0]
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
        SetupField("resume", "자기소개서·학업계획서 (선택)", "붙여 넣으면 쓴 내용을 근거로 질문과 꼬리질문을 해요", kind="textarea", max_len=6000),
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

# ---------------------------------------------------------------- TOEIC Speaking (11문항 · 5파트)

TOEIC_READ = (
    "Thank you for calling Greenfield Public Library. Our hours this week are Monday through Friday, nine a.m. to seven p.m., "
    "and Saturday, ten a.m. to four p.m. To renew a book, press one. For information about our summer reading program, "
    "events, and workshops, press two. To speak with a librarian, please stay on the line.",
    "Attention, shoppers. For the next hour only, all kitchen appliances, bedding, and garden tools are thirty percent off. "
    "Visit our customer service desk on the second floor to sign up for our rewards card, and you will receive free delivery "
    "on any purchase over fifty dollars. Thank you for shopping at Westfield Mart.",
    "Welcome to today's business news. Riverside Motors announced yesterday that it will open a new factory, a research center, "
    "and a training facility in the northern region next spring. The company expects the project to create more than two "
    "thousand jobs. Our reporter, Linda Park, has more details.",
    "Good morning, everyone, and welcome to the annual marketing conference. Before we begin, please make sure your mobile phones "
    "are switched off. Lunch will be served in the main hall at twelve thirty, and the afternoon sessions on design, branding, "
    "and social media will start at two o'clock.",
)
# 사진 (prototype/iv/<scene>.svg) — alt 는 AI 평가에 주는 사진 설명
TOEIC_PICTURES = (
    ("office", "An office meeting room: four people sit around a table with laptops and papers, a woman stands pointing at a chart "
               "on a screen, a plant in the corner, large windows with a city view."),
    ("cafe", "A cafe: a barista behind the counter makes coffee, a customer waits holding a phone, a menu board hangs on the wall, "
             "two people sit at a small round table by the window with cups."),
    ("park", "A park on a sunny day: a man jogs on a path, a woman sits on a bench reading a book, two children play with a ball "
             "on the grass, trees and a small pond in the background."),
    ("market", "An outdoor market: a vendor arranges fruit and vegetables on a stall under a striped awning, a woman with a shopping "
               "bag looks at apples, price signs on boxes, people walking in the background."),
)
TOEIC_SETS = (
    ("Imagine that a marketing firm is doing research in your area. You have agreed to participate in a telephone interview about movies.",
     ("How often do you go to the movies, and who do you usually go with?",
      "Do you prefer watching movies at a theater or at home? Why?",
      "What kind of information do you look for before deciding which movie to see? Explain why.")),
    ("Imagine that a friend is moving to your city. You are talking on the telephone about public transportation.",
     ("What kind of public transportation do you use most often, and why?",
      "How long does it take you to get to work or school, and how do you get there?",
      "If your friend could use only one type of transportation in your city, which would you recommend? Why?")),
    ("Imagine that a fitness magazine is doing research in your country. You have agreed to participate in a telephone interview about exercise.",
     ("When do you usually exercise, and for how long?",
      "Where do you prefer to exercise, at home or at a gym? Why?",
      "What would encourage more people in your area to exercise regularly? Explain why.")),
)
TOEIC_INFO = (
    {"title": "Business Leadership Workshop", "sub": "Hotel Grand, Room 3B · Friday, March 12",
     "rows": [["9:00 – 9:30", "Registration & welcome coffee"], ["9:30 – 10:30", "Lecture: Leading Remote Teams — Dr. Karen Lee"],
              ["10:30 – 11:30", "Workshop: Giving Effective Feedback (CANCELLED)"], ["11:30 – 12:30", "Lunch (provided)"],
              ["1:00 – 2:30", "Panel: Building Trust at Work — Tom Wilson, Ana Ruiz"], ["2:30 – 3:00", "Closing remarks"]],
     "intro": "Hi, this is Jason Miller. I signed up for the leadership workshop, but I lost the schedule. Could you help me?",
     "qs": ("Where will the workshop be held, and what time should I arrive?",
            "I heard the session on giving effective feedback starts at ten thirty. Is that right?",
            "Could you tell me everything that is scheduled for the afternoon?")},
    {"title": "Interview Schedule — Sales Manager Position", "sub": "Brightway Co., Conference Room A · Tuesday, June 4",
     "rows": [["9:30", "Emily Chen — current position: Sales Associate, Daylight Inc."], ["10:30", "Marcus Brown — Account Manager, Peak Solutions"],
              ["11:30", "Sara Kim — Sales Team Leader, Nova Retail (CANCELLED)"], ["1:30", "David Lopez — Regional Sales Rep, Arrow Foods"],
              ["2:30", "Hannah Ito — Marketing Coordinator, BlueSky Media"]],
     "intro": "Hello, this is Rachel from the HR team. I'm going to sit in on tomorrow's interviews, but I don't have the schedule with me.",
     "qs": ("What time is the first interview, and who will we be meeting?",
            "I think we're interviewing Sara Kim before lunch. Is that correct?",
            "Could you give me the details of the interviews scheduled for the afternoon?")},
)
TOEIC_OPINION = (
    "Some people prefer to work for a large company, while others prefer to work for a small company. Which do you prefer, and why? "
    "Give specific reasons and examples to support your opinion.",
    "Do you agree or disagree with the following statement? It is better to learn a new skill from a teacher than to learn it on your own. "
    "Give specific reasons and examples to support your opinion.",
    "What is the most important quality for a team leader to have? Choose one of the following and explain why: communication skills, "
    "experience, or fairness.",
    "Do you agree or disagree with the following statement? Companies should allow employees to work from home several days a week. "
    "Give specific reasons and examples to support your opinion.",
)


def _toeic_bank(setup: dict, rnd: random.Random) -> list[dict]:
    reads = rnd.sample(TOEIC_READ, 2)
    pics = rnd.sample(TOEIC_PICTURES, 2)
    intro, qs = rnd.choice(TOEIC_SETS)
    info = rnd.choice(TOEIC_INFO)
    out: list[dict] = []
    for r in reads:
        out.append({"q": "Read the text on your screen aloud.", "part": "Part 1 · 소리 내어 읽기", "prep": 45, "answer": 45,
                    "material": {"type": "read", "text": r}})
    for scene, alt in pics:
        out.append({"q": "Describe the picture on your screen in as much detail as you can.", "part": "Part 2 · 사진 묘사",
                    "prep": 45, "answer": 30, "material": {"type": "picture", "scene": scene, "alt": alt}})
    for i, q in enumerate(qs):
        out.append({"q": f"{intro} {q}" if i == 0 else q, "part": "Part 3 · 질문에 답하기", "prep": 3,
                    "answer": 30 if i == 2 else 15, "material": {"type": "set", "text": intro}})
    table = {"type": "info", "title": info["title"], "sub": info["sub"], "rows": info["rows"]}
    for i, q in enumerate(info["qs"]):
        out.append({"q": f"{info['intro']} {q}" if i == 0 else q, "part": "Part 4 · 표 보고 답하기",
                    "prep": 45 if i == 0 else 3, "answer": 30 if i == 2 else 15, "material": table})
    out.append({"q": rnd.choice(TOEIC_OPINION), "part": "Part 5 · 의견 말하기", "prep": 45, "answer": 60, "material": None})
    return out


TOEIC = Kind(
    key="toeic", name="TOEIC Speaking", lang="en",
    desc="실제 시험 형식 11문항 — 소리 내어 읽기 · 사진 묘사 · 질문에 답하기 · 표 보고 답하기 · 의견 말하기",
    mains=11, follow_ups=0, prep_sec=45, answer_sec=45, fixed=True, time_note="문항마다 15초~1분",
    fields=(SetupField("target", "목표 레벨", kind="select", options=("Lv.5", "Lv.6", "Lv.7", "Lv.8")),),
    levels=("Lv.1", "Lv.2", "Lv.3", "Lv.4", "Lv.5", "Lv.6", "Lv.7", "Lv.8"),
    level_note="예상 레벨이에요. 실제 TOEIC Speaking 점수와 다를 수 있어요.",
    guide=(
        "TOEIC Speaking 모의시험이다 (ETS 형식, 11문항). Part 1(1~2) 소리 내어 읽기: 발음·억양·강세 — 받아쓴 글이라 지문과 "
        "얼마나 같게 읽었는지(빠뜨린·잘못 읽은 단어)로 본다. Part 2(3~4) 사진 묘사: 문법·어휘·연결성, 사진 속 사람·사물·위치를 "
        "얼마나 구체적으로 말했는지. Part 3(5~7) 질문에 답하기: 질문에 맞는 내용·완결성. Part 4(8~10) 표 보고 답하기: 표의 정보를 "
        "정확히 전달했는지(취소된 항목 등 함정 포함). Part 5(11) 의견 말하기: 분명한 입장과 이유·예시, 구성. "
        "레벨은 Lv.1~Lv.8 (Lv.8 은 거의 원어민 수준, Lv.6 은 대부분의 상황에서 적절히 소통)."
    ),
    bank=_toeic_bank,
)


# ---------------------------------------------------------------- AI 역량검사 면접 (요즘 기업 AI 면접 형식)

AICOMP_SITUATIONS = (
    "같은 팀 선배가 마감 직전에 자기가 맡은 일까지 떠넘기려 합니다. 지금 그 선배에게 직접 말하듯 답해 주세요.",
    "고객이 배송이 늦었다며 크게 화를 내고 환불을 요구합니다. 지금 그 고객에게 직접 말하듯 답해 주세요.",
    "팀장님이 정한 업무 방식이 비효율적이라고 생각합니다. 회의가 끝난 뒤 팀장님께 직접 말씀드리듯 답해 주세요.",
    "신입 동료가 같은 실수를 세 번째 반복했습니다. 그 동료에게 직접 말하듯 답해 주세요.",
    "중요한 발표 10분 전, 준비한 자료 파일이 열리지 않습니다. 지금 팀원들에게 말하듯 답해 주세요.",
    "친한 동료가 회사 규정을 어기고 개인 일을 근무 시간에 처리하는 것을 보았습니다. 그 동료에게 직접 말하듯 답해 주세요.",
)
AICOMP_DEEP = (
    "지금까지 가장 몰입했던 경험은 무엇이고, 왜 그렇게까지 몰입할 수 있었나요?",
    "다른 사람들의 반대에도 끝까지 밀고 나갔던 결정이 있나요? 그 결과와 지금의 생각을 말씀해 주세요.",
    "일할 때 가장 중요하게 생각하는 원칙 하나와, 그 원칙을 지키느라 손해를 본 경험을 말씀해 주세요.",
    "누군가에게 실망을 준 경험이 있나요? 그 뒤에 무엇을 했는지 말씀해 주세요.",
)


def _aicomp_bank(setup: dict, rnd: random.Random) -> list[str]:
    job = setup.get("job") or "지원하신 직무"
    company = setup.get("company") or "우리 회사"
    sits = rnd.sample(AICOMP_SITUATIONS, 2)
    deep = resume_questions(setup.get("resume", ""), rnd, 1)
    return [
        "지금부터 1분 동안 자기소개를 해 주세요.",
        "본인의 장점과 단점을 하나씩, 실제 있었던 일과 함께 말씀해 주세요.",
        f"{company}에 지원한 동기와, {job}로서 입사 후 이루고 싶은 목표를 말씀해 주세요.",
        *sits,
        deep[0] if deep else rnd.choice(AICOMP_DEEP),
    ]


AICOMP = Kind(
    key="aicomp", name="AI 역량검사 면접", lang="ko",
    desc="요즘 기업이 쓰는 AI 면접 형식 — 자기소개 · 장단점 · 지원 동기 · 상황 대처 롤플레이 · 심층 질문",
    mains=6, follow_ups=3, prep_sec=30, answer_sec=90, time_note="준비 30초 · 답변 1분~1분 30초",
    slots=(
        Slot("기본 질문 · 자기소개", 30, 60, "1분 자기소개"),
        Slot("기본 질문 · 장단점", 30, 90, "본인의 장점과 단점을 실제 사례와 함께"),
        Slot("기본 질문 · 지원 동기", 30, 90, "지원 동기와 입사 후 목표"),
        Slot("상황 대처 · 롤플레이", 30, 60, "직장에서 생길 법한 갈등 상황을 주고 '지금 그 사람에게 직접 말하듯' 답하게 하는 롤플레이"),
        Slot("상황 대처 · 롤플레이", 30, 60, "앞과 다른 상대(고객·상사·동료)의 상황 롤플레이"),
        Slot("심층 질문", 30, 90, "경험·가치관을 깊이 묻는 구조화 질문 (몰입, 원칙, 실패)"),
    ),
    fields=(
        SetupField("company", "지원 회사", "회사 이름", max_len=60),
        SetupField("job", "지원 직무", "백엔드 개발자, 영업, 인사 …", max_len=60),
        SetupField("resume", "자기소개서", "붙여 넣으면 그 안의 경험을 근거로 심층 질문과 꼬리질문을 해요", kind="textarea", max_len=6000),
    ),
    levels=(),
    guide=(
        "요즘 한국 기업이 채용에 쓰는 AI 역량검사(AI 면접)의 면접 부분이다. 질문은 한국어 존댓말. 기본 질문(자기소개·장단점·지원 동기), "
        "상황 대처 질문(롤플레이: 상대에게 실제로 말하듯 답해야 함), 심층 구조화 질문(경험·가치관)을 하고, 답이 모호하면 꼬리질문으로 "
        "구체적 행동·근거를 확인한다. 평가 기준: 결론을 먼저 말하는 논리, 답변 사이의 일관성(장단점·경험·가치관이 서로 맞는지), "
        "롤플레이에서 상대의 감정을 먼저 인정하고 해결책을 제시하는 말투(설명조가 아니라 대화체), 구체성, 정해진 시간을 알맞게 쓰는지, "
        "부정적 표현·남 탓 여부. 점수는 100점 만점."
    ),
    bank=_aicomp_bank,
)

KINDS: dict[str, Kind] = {k.key: k for k in (OPIC, TOEIC, JOB, AICOMP, ADMISSION)}


# ---------------------------------------------------------------- 측정 (AI 없이도)

FILLERS = {
    "en": re.compile(r"\b(um+|uh+|erm|hmm+|like|you know|i mean|basically|actually|kind of|sort of)\b", re.I),
    "ko": re.compile(r"(?<![가-힣])(음+|어+|그+|저+|뭐랄까|약간|이제|그러니까|뭔가)(?![가-힣])"),
}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def read_accuracy(ref: str, said: str) -> int | None:
    """소리 내어 읽기: 받아쓴 글이 지문과 단어 단위로 얼마나 같은지 (0~100). 빠뜨리거나 잘못 읽은 단어가 깎인다."""
    a, b = _words(ref), _words(said)
    if not a or not b:
        return None if not a else 0
    return round(difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() * 100)


def measure(text: str, sec: int, lang: str, ref: str | None = None) -> dict:
    """답 하나의 말의 양·속도·군말. 영어는 단어/분, 한국어는 음절/분. ref(읽을 지문)가 있으면 읽기 정확도도."""
    t = (text or "").strip()
    words = len(re.findall(r"[A-Za-z']+", t)) if lang == "en" else len(t.split())
    syll = len(re.findall(r"[가-힣]", t))
    mins = max(sec, 1) / 60
    fillers = [f.lower() for f in (FILLERS[lang].findall(t) if t else [])]
    fillers = [f if isinstance(f, str) else f[0] for f in fillers]
    out = {"words": words, "syllables": syll, "sec": sec,
           "rate": round((words if lang == "en" else syll) / mins) if t and sec >= 5 else None,
           "fillers": len(fillers), "filler_words": sorted(set(fillers))[:6]}
    if ref:
        out["read_acc"] = read_accuracy(ref, t)
    return out


def _ref(t: dict) -> str | None:
    mat = t.get("material") or {}
    return mat.get("text") if mat.get("type") == "read" else None


def _material_text(t: dict) -> str:
    """AI 평가에 함께 줄 자료 (읽을 지문 · 사진 설명 · 일정표)."""
    mat = t.get("material") or {}
    kind = mat.get("type")
    if kind == "read":
        return f"\n읽을 지문: {mat['text']}"
    if kind == "picture":
        return f"\n사진 내용: {mat.get('alt', '')}"
    if kind == "info":
        rows = "; ".join(" ".join(r) for r in mat.get("rows", []))
        return f"\n자료 [{mat.get('title', '')} {mat.get('sub', '')}]: {rows}"
    if kind == "set":
        return f"\n상황: {mat.get('text', '')}"
    return ""


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
    reads = [read_accuracy(_ref(t), t["ans"]) for t in done if _ref(t)]
    reads = [r for r in reads if r is not None]
    # 답변 시간을 얼마나 채웠는지 (말한 양 ÷ 그 시간에 말할 수 있는 양) — 문항마다 시간이 달라도 비교된다
    fill = [min(1.0, x["words"] / max(1.0, (t.get("answer") or 60) * (2.0 if lang == "en" else 1.5)))
            for t, x in zip(done, ms)]
    return {
        "answered": len(answered), "total": len(done), "skipped": len(done) - len(answered),
        "avg_words": round(sum(x["words"] for x in answered) / len(answered)) if answered else 0,
        "avg_sec": round(sum(x["sec"] for x in answered) / len(answered)) if answered else 0,
        "rate": round(sum(rates) / len(rates)) if rates else None,
        "rate_unit": "단어/분" if lang == "en" else "음절/분",
        "fillers": sum(words.values()), "top_fillers": sorted(words, key=lambda k: -words[k])[:5],
        "read_acc": round(sum(reads) / len(reads)) if reads else None,
        "fill": round(sum(fill) / len(fill), 3) if fill else 0,
    }


# ---------------------------------------------------------------- AI 응답 형식

class Plan(BaseModel):
    questions: list[str] = Field(description="본 질문들, 순서대로")
    basis: list[str] = Field(default_factory=list, description=(
        "질문마다 근거가 된 자기소개서 문장을 짧게 그대로 인용 (questions 와 같은 개수, 자기소개서와 상관없는 질문은 빈 문자열)"))


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


def _resume_rule(setup: dict) -> str:
    if not (setup.get("resume") or "").strip():
        return ""
    return ("\n\n[지시] 자기소개서를 읽고, 본 질문 중 적어도 3개는 자기소개서의 구체적인 문장(경험·성과·주장)을 근거로 "
            "그 경험에서 본인의 역할·행동·결과·배운 점을 파고든다. 근거 문장은 basis 에 그대로 짧게 인용한다. "
            "회사·직무가 있으면 자기소개서 내용과 직무를 연결해 묻는 질문도 하나 넣는다.")


def _in_resume(basis: str, resume: str) -> bool:
    """AI 가 붙인 근거가 실제 자기소개서에 있는 말인지 (단어 절반 이상이 겹치면)."""
    b = [w for w in re.findall(r"[가-힣A-Za-z0-9]+", basis or "") if len(w) > 1]
    if not b or not resume:
        return False
    return sum(1 for w in b if w in resume) >= max(1, len(b) // 2)


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

def _item(kind: Kind, x, idx: int) -> dict:
    """계획의 문항 하나를 {q, part, prep, answer, material} 로 (예전 기록은 글자만 있다)."""
    d = {"q": x} if isinstance(x, str) else dict(x)
    slot = kind.slots[idx] if idx < len(kind.slots) else None
    d.setdefault("part", slot.part if slot else None)
    d.setdefault("prep", slot.prep if slot else kind.prep_sec)
    d.setdefault("answer", slot.answer if slot else kind.answer_sec)
    d.setdefault("material", None)
    return d


def _turn(item: dict, follow: bool = False) -> dict:
    return {**item, "follow": follow, "ans": None, "sec": 0}


def start(db: Session, user: m.User, kind: Kind, setup: dict) -> m.Interview:
    s = get_settings()
    questions: list = []
    if not kind.fixed:
        slots = ("\n자리별로 이 순서대로 하나씩:\n" + "\n".join(f"{i + 1}. [{sl.part}] {sl.hint} (답변 {sl.answer}초)"
                                                      for i, sl in enumerate(kind.slots))) if kind.slots else ""
        plan = _ai(db, user, "interview_plan", model=s.openai_model_route, effort="low",
                   instructions=(f"너는 {kind.name} 면접관이다. {kind.guide}\n"
                                 f"지원자 정보에 맞춘 본 질문을 정확히 {kind.mains}개 만든다. 첫 질문은 가벼운 자기소개. "
                                 f"각 질문은 한두 문장, {max(1, kind.answer_sec // 60)}분 안에 답할 수 있게. {_lang_rule(kind)}{slots}"),
                   prompt=f"지원자 정보:\n{_setup_text(kind, setup)}{_resume_rule(setup)}", schema=Plan, max_tokens=4000)
        questions = [q.strip() for q in (plan.questions if plan else []) if q.strip()][: kind.mains]
        if plan and len(plan.basis) == len(plan.questions):  # 자기소개서 근거를 질문에 붙인다 (자기소개서에 실제로 있는 말만)
            questions = [({"q": q, "basis": b.strip()[:120]} if _in_resume(b, setup.get("resume", "")) else q)
                         for q, b in zip(questions, plan.basis)]
    by_ai = len(questions) == kind.mains
    if not by_ai:
        questions = kind.bank(setup, random.Random())[: kind.mains]
    plan_items = [_item(kind, x, i) for i, x in enumerate(questions)]
    iv = m.Interview(user_id=user.id, kind=kind.key, lang=kind.lang, setup=setup, plan=plan_items,
                     turns=[_turn(plan_items[0])], status="active", by_ai=by_ai)
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
            nxt = _turn({"q": f.question.strip()[:600], "part": "꼬리질문", "prep": min(kind.prep_sec, 15),
                         "answer": t.get("answer") or kind.answer_sec, "material": None}, follow=True)
    if nxt is None:
        mains_done = sum(1 for x in turns if not x.get("follow"))
        if mains_done < len(iv.plan):
            nxt = _turn(_item(kind, iv.plan[mains_done], mains_done))
    if nxt:
        turns.append(nxt)
    else:
        iv.status = "answered"
    iv.turns = turns
    db.flush()


def _heuristic_level(kind: Kind, metrics: dict) -> tuple[str, int]:
    """AI 없이: 답의 길이·속도로 어림한 등급·점수 (답의 내용은 보지 않는다)."""
    # 답변 시간을 얼마나 채웠는지(안 푼 문항은 0)로 어림한다. 읽기 문항이 있으면 읽기 정확도도 반영
    base = metrics.get("fill", 0) * 100
    if metrics.get("read_acc") is not None:
        base = base * 0.8 + metrics["read_acc"] * 0.2
    base = max(0, min(100, round(base)))
    if not kind.levels:
        return "", base
    # 맨 위 등급(OPIc AL · TOEIC Lv.8)은 AI 평가로만
    idx = min(int(base / 100 * (len(kind.levels) - 1)), len(kind.levels) - 2)
    return kind.levels[idx], base


def finish(db: Session, user: m.User, iv: m.Interview) -> None:
    if iv.status == "done":
        return
    kind = KINDS[iv.kind]
    turns = [t for t in iv.turns if t.get("ans") is not None]
    metrics = summary_metrics(turns, kind.lang)
    s = get_settings()
    rep = None
    if metrics["answered"]:
        qa = "\n\n".join(f"[{i + 1}{' · ' + t['part'] if t.get('part') else ''}{' · 꼬리질문' if t.get('follow') else ''}] "
                         f"질문: {t['q']}{_material_text(t)}\n답 ({t.get('sec', 0)}초 / 제한 {t.get('answer') or kind.answer_sec}초): "
                         f"{t['ans'] or '(답하지 않음)'}"
                         for i, t in enumerate(turns))
        rep = _ai(db, user, "interview_report", model=s.openai_model_generate, effort="low",
                  instructions=(f"너는 {kind.name} 평가 전문가다. {kind.guide}\n"
                                "답은 브라우저 음성 인식으로 받아쓴 글이라 맞춤법·띄어쓰기·구두점 오류는 감점하지 않는다. "
                                f"{'등급은 다음 중 하나: ' + ', '.join(kind.levels) + '.' if kind.levels else '등급 없이 점수만 매긴다 (level 은 빈 문자열).'} "
                                "피드백·총평은 한국어, 모범 답변(better)은 답변 언어로 쓴다. "
                                "items 는 질문 수와 같은 개수로, 답하지 않은 질문은 0점과 함께 모범 답변만 준다."),
                  prompt=(f"지원자 정보:\n{_setup_text(kind, iv.setup)}\n\n측정값: 평균 {metrics['avg_words']}"
                          f"{'단어' if kind.lang == 'en' else '어절'}, 말 속도 {metrics['rate']} {metrics['rate_unit']}, "
                          f"군말 {metrics['fillers']}번"
                          f"{', 소리 내어 읽기 정확도 ' + str(metrics['read_acc']) + '%' if metrics.get('read_acc') is not None else ''}"
                          f"\n\n{qa}"),
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
        if metrics.get("read_acc") is not None and metrics["read_acc"] < 85:
            tips.append(f"소리 내어 읽기 정확도가 {metrics['read_acc']}%예요. 빠뜨린 단어 없이 끊어 읽을 곳을 정해 천천히 읽어 보세요")
        report = {"by_ai": False, "level": level, "score": score,
                  "summary": "AI 평가 없이 말의 양·속도·군말만으로 어림한 결과예요. 내용과 문법은 보지 않았어요.",
                  "strengths": ["모든 질문에 답했어요"] if not metrics["skipped"] and metrics["answered"] else [],
                  "improve": tips or ["좋아요. 다음에는 더 어려운 질문으로 연습해 보세요"],
                  "items": [{"score": None, "feedback": "", "better": ""} for _ in turns]}
    report["metrics"] = metrics
    report["per"] = [measure(t["ans"], t.get("sec") or 0, kind.lang, _ref(t)) for t in turns]
    iv.report = report
    iv.status = "done"
    iv.finished_at = datetime.now(timezone.utc)
    db.flush()

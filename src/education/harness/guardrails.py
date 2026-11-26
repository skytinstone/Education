"""가드레일 — 모델 앞뒤에서 규칙으로 거르는 층 (하네스 4단계). 모두 AI 없이, 빠르고 결정적으로 동작한다.

입력 (scan_input) — 학생이 보낸 글을 AI 에 넘기기 전에
- 프롬프트 주입 시도(지시 무시 · 역할 바꾸기 · 시스템 프롬프트 요구)를 찾아 표시한다 (막지는 않음 — 지시문이 이미 '자료일 뿐' 으로 다룬다)
- 개인정보(이메일 · 전화번호 · 주민등록번호 · 카드 번호)를 가린다 — 가린 글만 AI 에 보낸다 (저장되는 원문은 그대로)

출력 (check_problem) — 생성 AI 가 만든 문제를 검증 AI 에 보내기 전에
- 수식 표기가 깨졌는지 ($ 짝 · 괄호 짝), 보기가 겹치거나 비었는지, 본문에 정답을 흘렸는지, 너무 긴지, 부적절한 말이 있는지
- 걸리면 그 이유로 떨어뜨리고, 자기 수정 루프가 이유를 생성 AI 에 알려 고치게 한다

실행 (CircuitBreaker) — services/llm.py
- 같은 모델 호출이 연속으로 실패하면 잠시 호출을 멈추고 바로 대체 경로(문제 은행 · 한 번 답)로 가게 한다
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field

# ---------- 입력 ----------
INJECTION = [
    (re.compile(r"(이전|위|앞|기존)\S*\s*(의\s*)?(모든\s*)?(지시|명령|규칙|설정|프롬프트)\S*\s*(모두\s*|다\s*|전부\s*)?(무시|잊)"), "지시 무시 요구"),
    (re.compile(r"ignore\s+(all\s+|the\s+)?(previous|above|prior)\s+(instructions|rules|prompts?)", re.I), "지시 무시 요구"),
    (re.compile(r"(시스템|system)\s*(프롬프트|prompt|메시지|message)", re.I), "시스템 프롬프트 요구"),
    (re.compile(r"(너는|넌)\s*이제(부터)?\s|역할을\s*바꿔|지금부터\s*너는|you\s+are\s+now\s", re.I), "역할 바꾸기"),
    (re.compile(r"developer\s*mode|개발자\s*모드|jailbreak|탈옥|\bDAN\b", re.I), "탈옥 시도"),
]
PII = [
    (re.compile(r"\b\d{6}\s*-\s*[1-4]\d{6}\b"), "[주민번호]", "주민번호"),
    (re.compile(r"\b(?:\d{4}[- ]){3}\d{4}\b"), "[카드번호]", "카드번호"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[이메일]", "이메일"),
    (re.compile(r"\b01[016789][- ]?\d{3,4}[- ]?\d{4}\b"), "[전화번호]", "전화번호"),
]


@dataclass
class InputScan:
    text: str  # AI 에 보낼 글 (개인정보를 가림)
    flags: list[str] = field(default_factory=list)

    @property
    def injection(self) -> bool:
        return any(f.startswith("주입:") for f in self.flags)


def scan_input(text: str) -> InputScan:
    flags: list[str] = []
    for pat, name in INJECTION:
        if pat.search(text or "") and f"주입: {name}" not in flags:
            flags.append(f"주입: {name}")
    masked = text or ""
    for pat, repl, name in PII:
        masked, n = pat.subn(repl, masked)
        if n:
            flags.append(f"개인정보: {name}")
    return InputScan(masked, flags)


# ---------- 출력 ----------
MAX_STEM = 1500
BANNED = re.compile(r"(시발|씨발|병신|좆|개새끼|fuck|shit)", re.I)
_SPACE = re.compile(r"[\s$\\{}]+")


def _unescaped_dollars(s: str) -> int:
    return len(re.findall(r"(?<!\\)\$", s))


def _brace_balanced(s: str) -> bool:
    depth = 0
    for i, ch in enumerate(s):
        if ch == "{" and (i == 0 or s[i - 1] != "\\"):
            depth += 1
        elif ch == "}" and (i == 0 or s[i - 1] != "\\"):
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


_MATH = re.compile(r"\$[^$]*\$")


def not_korean(text: str) -> bool:
    """수식($…$)을 뺀 글이 대부분 외국어(로마자)인지 — 한국어 문장에 원어를 괄호로 덧붙인 정도는 통과."""
    t = _MATH.sub(" ", text or "")
    latin, hangul = len(re.findall(r"[A-Za-z]", t)), len(re.findall(r"[가-힣]", t))
    return latin >= 20 and hangul * 4 < latin


def check_problem(problem, korean: bool = True) -> list[str]:
    """생성된 문제의 규칙 위반 (없으면 빈 목록). korean: 문제·해설을 한국어로 써야 하는지 (어학 코스만 False)."""
    issues: list[str] = []
    stem = problem.stem or ""
    choices = list(getattr(problem, "choices", None) or [])
    texts = [stem, *choices, getattr(problem, "solution", "") or ""]
    if len(stem) > MAX_STEM:
        issues.append(f"본문이 너무 길어요 ({len(stem)}자)")
    for t in texts:
        if _unescaped_dollars(t) % 2:
            issues.append("수식 표기 $ 짝이 맞지 않아요")
            break
    for t in texts:
        if not _brace_balanced(t):
            issues.append("수식 괄호 { } 짝이 맞지 않아요")
            break
    if choices:
        norm = [_SPACE.sub("", c) for c in choices]
        if any(not n for n in norm):
            issues.append("빈 보기가 있어요")
        elif len(set(norm)) < len(norm):
            issues.append("같은 보기가 두 번 있어요")
    if re.search(r"정답\s*(은|는|:)\s*[①②③④⑤0-9]", stem):
        issues.append("본문에 정답을 적었어요")
    if any(BANNED.search(t) for t in texts):
        issues.append("부적절한 표현이 있어요")
    if korean and (not_korean(stem) or not_korean(getattr(problem, "solution", "") or "")):
        issues.append("문제와 해설을 한국어로 쓰지 않았어요 — 영어 교재·기출이어도 우리말로 옮겨 쓰세요")
    return issues


# ---------- 실행 ----------
class CircuitBreaker:
    """연속 실패가 threshold 번이면 cooldown 초 동안 열린다 (호출을 바로 거절). 지나면 한 번 시험해 보고, 성공하면 닫힌다."""

    def __init__(self, threshold: int = 5, cooldown: float = 60.0, clock=time.monotonic):
        self.threshold, self.cooldown, self.clock = threshold, cooldown, clock
        self.failures: dict[str, int] = {}
        self.opened: dict[str, float] = {}
        self.lock = threading.Lock()

    def allow(self, key: str) -> float | None:
        """호출해도 되면 None, 막혔으면 남은 초."""
        with self.lock:
            at = self.opened.get(key)
            if at is None:
                return None
            left = self.cooldown - (self.clock() - at)
            if left > 0:
                return left
            del self.opened[key]  # 반쯤 열림 — 한 번 시험해 본다
            self.failures[key] = self.threshold - 1
            return None

    def record(self, key: str, ok: bool) -> None:
        with self.lock:
            if ok:
                self.failures.pop(key, None)
                self.opened.pop(key, None)
                return
            self.failures[key] = self.failures.get(key, 0) + 1
            if self.failures[key] >= self.threshold:
                self.opened[key] = self.clock()

    def state(self) -> dict:
        with self.lock:
            now = self.clock()
            return {k: {"failures": self.failures.get(k, 0),
                        "open_for_s": max(0, round(self.cooldown - (now - self.opened[k]))) if k in self.opened else 0}
                    for k in set(self.failures) | set(self.opened)}


BREAKER = CircuitBreaker()

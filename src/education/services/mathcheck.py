"""AI 가 낸 수식을 안전하게 읽어 그래프 점을 찍고, 계산 결과를 SymPy 로 검산한다.

AI 가 준 문자열을 그대로 실행하지 않는다. 숫자·x·사칙연산·괄호·허용된 함수 이름만 있는지
토큰 단위로 먼저 확인하고(밑줄·점 접근·따옴표 등은 아예 통과하지 못함), 통과한 것만 SymPy 식으로 만든다.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import sympy as sp
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

X = sp.Symbol("x", real=True)

FUNCS: dict[str, object] = {
    "sin": sp.sin, "cos": sp.cos, "tan": sp.tan, "sec": sp.sec, "csc": sp.csc, "cot": sp.cot,
    "asin": sp.asin, "acos": sp.acos, "atan": sp.atan, "arcsin": sp.asin, "arccos": sp.acos, "arctan": sp.atan,
    "sinh": sp.sinh, "cosh": sp.cosh, "tanh": sp.tanh,
    "exp": sp.exp, "log": sp.log, "ln": sp.log, "sqrt": sp.sqrt, "abs": sp.Abs, "Abs": sp.Abs,
}
CONSTS: dict[str, object] = {"pi": sp.pi, "e": sp.E, "E": sp.E, "x": X}
_TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d+)?)|([A-Za-z]+)|(\*\*|[-+*/^(),]))")
_TRANSFORMS = standard_transformations + (implicit_multiplication_application, convert_xor)
MAX_LEN = 200


class MathParseError(ValueError):
    pass


def parse(text: str) -> sp.Expr:
    """허용된 기호만으로 된 x 의 식을 SymPy 식으로. 아니면 MathParseError."""
    s = (text or "").strip().replace("×", "*").replace("·", "*").replace("−", "-").replace("π", "pi")
    if not s or len(s) > MAX_LEN:
        raise MathParseError("식이 비었거나 너무 길어요")
    pos = 0
    while pos < len(s):
        m = _TOKEN.match(s, pos)
        if not m or m.end() == pos:
            raise MathParseError(f"허용되지 않는 기호: {s[pos:pos + 10]!r}")
        if m.group(2) and m.group(2) not in FUNCS and m.group(2) not in CONSTS:
            raise MathParseError(f"허용되지 않는 이름: {m.group(2)}")
        pos = m.end()
    try:
        expr = parse_expr(s, local_dict={**FUNCS, **CONSTS}, transformations=_TRANSFORMS, evaluate=True)
    except Exception as e:  # SymPy 문법 오류 (괄호 짝 등)
        raise MathParseError(f"식을 읽지 못했어요: {e}") from e
    if not isinstance(expr, sp.Expr) or expr.free_symbols - {X}:
        raise MathParseError("x 만 쓰는 식이어야 해요")
    return expr


def _fn(expr: sp.Expr):
    f = sp.lambdify(X, expr, modules="math")

    def safe(x: float) -> float | None:
        try:
            y = f(x)
        except (ValueError, ZeroDivisionError, OverflowError, TypeError):
            return None
        if isinstance(y, complex) or y is None:
            return None
        y = float(y)
        return y if math.isfinite(y) and abs(y) < 1e6 else None
    return safe


def value(expr: sp.Expr, x: float) -> float | None:
    return _fn(expr)(x)


def sample(expr: sp.Expr, x_min: float, x_max: float, n: int = 241) -> tuple[list[float], list[float | None]]:
    """그래프 점. 정의되지 않는 곳(분모 0, 로그의 음수 등)은 None 으로 두어 선을 끊는다."""
    f = _fn(expr)
    xs = [x_min + (x_max - x_min) * i / (n - 1) for i in range(n)]
    return [round(x, 6) for x in xs], [None if (y := f(x)) is None else round(y, 6) for x in xs]


# ---------- 검산 ----------
@dataclass
class CheckResult:
    status: str  # verified · mismatch · unchecked
    note: str


_PROBES = [-2.7, -1.3, -0.6, 0.35, 0.9, 1.7, 2.4, 3.1]


def _same_function(a: sp.Expr, b: sp.Expr) -> bool | None:
    """두 식이 같은 함수인지 여러 x 에서 값을 비교 (정의되는 점이 3개 미만이면 판단 보류)."""
    fa, fb = _fn(a), _fn(b)
    seen = 0
    for x in _PROBES:
        ya, yb = fa(x), fb(x)
        if ya is None or yb is None:
            continue
        seen += 1
        if abs(ya - yb) > 1e-6 * max(1.0, abs(ya), abs(yb)):
            return False
    return True if seen >= 3 else None


def _close(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(a - b) <= 1e-6 * max(1.0, abs(a), abs(b))


def _num(text: str) -> float | None:
    try:
        v = complex(parse(text).evalf())
    except (MathParseError, TypeError, ValueError):
        return None
    return v.real if abs(v.imag) < 1e-12 else None


def verify(kind: str, expr: str, answer: str, a: str = "", b: str = "") -> CheckResult:
    """AI 가 낸 답을 수학적으로 확인한다. 확인할 수 없는 종류·식이면 unchecked."""
    try:
        if kind == "antiderivative":  # 부정적분: 답을 미분하면 원래 식
            same = _same_function(sp.diff(parse(answer), X), parse(expr))
            note = "답을 미분하면 원래 식과 같아요" if same else "답을 미분한 결과가 원래 식과 달라요"
        elif kind == "derivative":  # 미분
            same = _same_function(sp.diff(parse(expr), X), parse(answer))
            note = "직접 미분한 결과와 같아요" if same else "직접 미분한 결과와 달라요"
        elif kind == "definite_integral":  # 정적분: 수치 적분과 비교
            lo, hi, got = _num(a), _num(b), _num(answer)
            if lo is None or hi is None or got is None:
                return CheckResult("unchecked", "")
            real = float(sp.Integral(parse(expr), (X, lo, hi)).evalf(15))
            same = _close(real, got)
            note = f"수치로 적분한 값 {real:.6g}과 같아요" if same else f"수치로 적분하면 {real:.6g}이에요"
        elif kind == "limit":
            point, got = _num(a), _num(answer)
            if point is None or got is None:
                return CheckResult("unchecked", "")
            real = sp.limit(parse(expr), X, point)
            same = real.is_finite and _close(float(real), got)
            note = "극한값을 다시 계산해도 같아요" if same else "극한값을 다시 계산한 결과와 달라요"
        elif kind == "equation":  # expr = 0 의 해. answer 는 쉼표로 구분
            f = parse(expr)
            roots = [_num(r) for r in answer.split(",") if r.strip()]
            if not roots or any(r is None for r in roots):
                return CheckResult("unchecked", "")
            same = all(v is not None and abs(v) < 1e-7 for v in (value(f, r) for r in roots))
            note = "구한 해를 대입하면 식이 성립해요" if same else "구한 해 중 식을 만족하지 않는 값이 있어요"
        elif kind == "value":  # 식의 값 계산
            same = _close(_num(expr), _num(answer))
            note = "값을 다시 계산해도 같아요" if same else "값을 다시 계산한 결과와 달라요"
        else:
            return CheckResult("unchecked", "")
    except (MathParseError, TypeError, ValueError, NotImplementedError, ZeroDivisionError):
        return CheckResult("unchecked", "")
    if same is None:
        return CheckResult("unchecked", "")
    return CheckResult("verified" if same else "mismatch", note)

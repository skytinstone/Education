"""계산 도구 (LangChain Tool) — 검산 에이전트와 대화 에이전트가 쓴다.

AI 가 준 문자열을 그대로 실행하지 않는다. 숫자 · 한 글자 변수 · 사칙연산 · 괄호 · 허용된 함수 이름만 있는지
토큰 단위로 먼저 확인하고 (밑줄 · 점 접근 · 따옴표 등은 통과 못 함), 통과한 것만 SymPy 식으로 만든다.
도구는 실패해도 예외 대신 '오류: …' 글을 돌려준다 — 에이전트가 읽고 식을 고쳐 다시 부를 수 있게.
"""

from __future__ import annotations

import re

import sympy as sp
from langchain.tools import tool
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

from education.services.mathcheck import FUNCS

MAX_LEN = 300
CONSTS = {"pi": sp.pi, "e": sp.E, "E": sp.E, "oo": sp.oo, "inf": sp.oo, "I": sp.I}
_TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d+)?)|([A-Za-z]+)|(\*\*|[-+*/^(),]))")
_TRANSFORMS = standard_transformations + (implicit_multiplication_application, convert_xor)


class ToolInputError(ValueError):
    pass


def _symbols(names: set[str]) -> dict[str, sp.Symbol]:
    return {n: sp.Symbol(n) for n in names}


def safe_parse(text: str) -> sp.Expr:
    s = (text or "").strip().replace("×", "*").replace("·", "*").replace("−", "-").replace("π", "pi").replace("∞", "oo")
    if not s or len(s) > MAX_LEN:
        raise ToolInputError("식이 비었거나 너무 길어요")
    names: set[str] = set()
    pos = 0
    while pos < len(s):
        m = _TOKEN.match(s, pos)
        if not m or m.end() == pos:
            raise ToolInputError(f"허용되지 않는 기호: {s[pos:pos + 10]!r}")
        if (name := m.group(2)) and name not in FUNCS and name not in CONSTS:
            if len(name) != 1:
                raise ToolInputError(f"허용되지 않는 이름: {name} (변수는 한 글자, 함수는 sin·log·sqrt 등)")
            names.add(name)
        pos = m.end()
    try:
        expr = parse_expr(s, local_dict={**FUNCS, **CONSTS, **_symbols(names)}, transformations=_TRANSFORMS, evaluate=True)
    except Exception as e:
        raise ToolInputError(f"식을 읽지 못했어요: {e}") from e
    if not isinstance(expr, sp.Basic):
        raise ToolInputError("식이 아니에요")
    return expr


def _var(name: str) -> sp.Symbol:
    if not re.fullmatch(r"[A-Za-z]", name or ""):
        raise ToolInputError("변수는 한 글자로 (예: x)")
    return sp.Symbol(name)


def _fmt(v: sp.Basic) -> str:
    out = str(sp.simplify(v))
    try:
        if v.is_number and not v.is_Integer:
            out += f" ≈ {float(sp.N(v)):.6g}"
    except (TypeError, ValueError):
        pass
    return out


def _safe(fn):
    def run(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolInputError as e:
            return f"오류: {e}"
        except Exception as e:  # SymPy 계산 실패
            return f"오류: 계산하지 못했어요 ({type(e).__name__})"
    run.__name__, run.__doc__ = fn.__name__, fn.__doc__
    return run


@tool
def calculate(expression: str) -> str:
    """수식을 정확히 계산·정리한다. 예: '2^10 - 1', 'log(8)/log(2)', 'sqrt(18) + sqrt(2)'. 곱셈은 *, 거듭제곱은 ^."""
    return _safe(lambda: _fmt(safe_parse(expression)))()


@tool
def solve_equation(equation: str, variable: str = "x") -> str:
    """방정식을 푼다. '=' 로 양변을 쓴다. 예: equation='x^2 - 5x + 6 = 0', variable='x'."""
    def run():
        v = _var(variable)
        left, _, right = equation.partition("=")
        sols = sp.solve(sp.Eq(safe_parse(left), safe_parse(right or "0")), v)
        return "해 없음" if not sols else ", ".join(_fmt(x) for x in sols)
    return _safe(run)()


@tool
def definite_integral(expression: str, variable: str, lower: str, upper: str) -> str:
    """정적분을 계산한다. 예: expression='2x e^(x^2)', variable='x', lower='0', upper='1'. 무한대는 oo."""
    return _safe(lambda: _fmt(sp.integrate(safe_parse(expression), (_var(variable), safe_parse(lower), safe_parse(upper)))))()


@tool
def derivative(expression: str, variable: str = "x", at: str = "") -> str:
    """도함수를 구한다. at 을 주면 그 점에서의 미분계수. 예: expression='x^3 - 3x', at='2'."""
    def run():
        v = _var(variable)
        d = sp.diff(safe_parse(expression), v)
        return _fmt(d.subs(v, safe_parse(at))) if at.strip() else str(sp.simplify(d))
    return _safe(run)()


@tool
def limit_of(expression: str, variable: str, point: str) -> str:
    """극한을 구한다. 예: expression='sin(x)/x', variable='x', point='0'. 무한대는 oo."""
    return _safe(lambda: _fmt(sp.limit(safe_parse(expression), _var(variable), safe_parse(point))))()


@tool
def are_equal(a: str, b: str) -> str:
    """두 식(또는 값)이 수학적으로 같은지 확인한다. 예: a='e - 1', b='1.71828'. 소수는 1e-6 오차까지 같다고 본다."""
    def run():
        x, y = safe_parse(a), safe_parse(b)
        diff = sp.simplify(x - y)
        if diff == 0:
            return "같아요"
        try:
            if diff.is_number and abs(float(sp.N(diff))) < 1e-6 * max(1.0, abs(float(sp.N(y)))):
                return "같아요 (소수 오차 범위)"
        except (TypeError, ValueError):
            pass
        return f"달라요 (차이: {_fmt(diff)})"
    return _safe(run)()


MATH_TOOLS = [calculate, solve_equation, definite_integral, derivative, limit_of, are_equal]

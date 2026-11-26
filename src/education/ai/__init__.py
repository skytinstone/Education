"""Eureka AI 에이전트 계층 — LangChain · LangGraph · RAG(pgvector) · Tool Calling.

기존 services/llm.py(구조화 출력 한 번 호출)는 그대로 두고, 도구를 쓰거나 검색이 필요한 일만 여기서 한다.

    models.py       LangChain 모델·임베딩 만들기, 토큰·비용 집계
    sympy_tools.py  계산 도구 (SymPy) — AI 가 코드를 짜서 실행하는 대신 우리가 만든 안전한 함수만 부른다
    math_check.py   검산 에이전트 — 생성·검증을 통과한 수학·물리 문제를 도구로 다시 계산해 확인 (Tool Calling)
    rag.py          문제 임베딩 저장·검색 (pgvector) — 비슷한 좋은 문제를 본보기로, 거의 같은 문제는 중복으로
    tutor_agent.py  대화 에이전트 — 학습 현황·플래너·오답·문제 검색·계산 도구를 골라 쓰며 답한다

모든 도구는 서버가 정한 '지금 사용자' 범위 안에서만 동작한다 (AI 가 다른 사람 id 를 넘겨도 소용없음).
"""

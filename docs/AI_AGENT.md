# AI 에이전트 계층 — LangChain · RAG · Tool Calling

`src/education/ai/` 에 있다. 기존 `services/llm.py`(구조화 출력 한 번 호출)는 그대로 두고, **도구를 쓰거나 검색이 필요한 일**만 여기서 한다.

## 버전

| 구성 | 패키지 | 버전 |
|---|---|---|
| 에이전트 · 도구 호출 루프 | `langchain` (`create_agent`) | 1.5.2 |
| 메시지 · 도구 · 임베딩 인터페이스 | `langchain-core` | 1.8.5 |
| OpenAI 모델 · 임베딩 | `langchain-openai` (`ChatOpenAI`, `OpenAIEmbeddings`) | 1.8.5 |
| 에이전트 실행 그래프 | `langgraph` | 1.2.24 |
| OpenAI SDK | `openai` | 3.59.0 |
| 벡터 저장 · 검색 | pgvector 확장 (DB 이미지 `pgvector/pgvector:0.8.7-pg17-trixie`) · `pgvector` (SQLAlchemy) | 0.8.7 · 0.5.1 |
| 임베딩 모델 | `text-embedding-3-small` (1536차원) | — |
| 계산 | `sympy` | 1.14.0 |

## 어디에 쓰나

| 기능 | RAG | Tool Calling | LangChain |
|---|---|---|---|
| **검산 에이전트** (`math_check.py`) — 생성·검증을 통과한 수학·물리 문제를 SymPy 도구로 다시 계산, 정답과 다르면 버림 | – | `calculate` · `solve_equation` · `definite_integral` · `derivative` · `limit_of` · `are_equal` | `create_agent` + `ToolStrategy(MathCheck)` |
| **문제 생성 본보기** (`generator.py`) — 요청과 의미가 비슷한 좋은 문제(성적표 C·D 제외)를 참고 문제로, 올린 기출이 많으면 가장 비슷한 3개 | `rag.search` · `rag.similar` | – | `OpenAIEmbeddings` |
| **중복 문제 거르기** — 같은 개념에 유사도 0.95 이상인 문제가 있으면 새 문제를 버림 | `rag.duplicates` | – | `OpenAIEmbeddings` |
| **대화 에이전트** (`tutor_agent.py`) — 현황·상담 질문에 필요한 것만 도구로 찾아보고 답 | `search_problems` | `get_study_status` · `get_today_plan` · `get_wrong_notes` · 계산 도구 | `create_agent` + `ToolStrategy(AgentReply)` + `context_schema` |

## 설계 원칙

- **사람이 확인하는 실행**: 대화 에이전트는 데이터를 바꾸지 않는다. 문제 만들기·시험 시작은 `suggestions` 버튼과 `start_exam` 으로 돌려주고, 학생이 눌렀을 때 기존 경로가 실행된다.
- **사용자 범위**: 도구는 `ToolRuntime.context` 의 서버가 정한 사용자로만 조회한다. RAG 검색도 `problems` 와 조인해 공용 문제 + 내가 올린 기출만 본다.
- **안전한 계산**: AI 가 코드를 짜서 실행하지 않는다. 식은 토큰 단위로 허용 기호만 통과시킨 뒤 SymPy 로 만든다.
- **실패해도 서비스는 그대로**: 에이전트·임베딩이 실패하면 기존 경로(한 번 답 · 개념 ID 로 본보기 고르기)로 돌아간다. 검산이 실패해도 이미 독립 검증을 통과한 문제는 막지 않는다.
- **비용 기록**: 모든 호출은 `llm_calls` 에 `math_check` · `embed` · `agent` 로 남고 운영 콘솔 AI 사용량에 보인다.
- **테스트**: 실제 API 없이 — 가짜 채팅 모델이 도구 호출 순서를 재생하고, 가짜 임베딩이 같은 글에 같은 벡터를 준다 (`tests/test_ai_stack.py`).

## 운영

```sh
python -m education.ai.index          # 임베딩이 없는 문제를 채운다 (매일 아침 알림 작업에서도 자동)
```

설정 (`.env`): `AI_TOOL_CHECK`, `AI_TOOL_CHECK_DOMAINS`, `AI_CHAT_AGENT`, `EMBEDDING_MODEL`, `RAG_DUPLICATE_SIMILARITY`.

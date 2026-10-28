# Eureka

Horcrux Technologies의 시험 준비 AI 학습 에이전트. MVP는 **고등 / 수능 수준의 수학 + 과학(물리학I, 화학I, 생명과학I, 지구과학I)** 을 대상으로 하고, 이후 CPA, 의전원, 대학 전공, 영어, 한국어 등으로 확장한다.

## 핵심 기능
1. **문제 생성**: 과목, 개념, 난이도를 지정하면 문제, 정답, 해설을 만든다
2. **오답노트**: 틀린 원인을 분류하고, 같은 개념을 다른 형태로 바꾼 변형 문제를 만든다
3. **약점 분석**: 개념별 정답률로 약점을 찾고, 개념 정리와 필수 암기 카드를 만든다
4. **기출 기반 생성**: 기출의 구조를 분석해서 같은 수준이나 그 이상의 신규 문제를 만든다

모든 생성 문제는 **검증 에이전트**를 통과해야 학습자에게 보여준다 (독립 재풀이, 계산 문제는 코드로 확인).

## 구조
```
data/concepts/*.yaml        개념 트리 (과목 > 단원 > 개념, 선수 개념 포함)
data/problems/sample.yaml   샘플 문제 은행 (직접 만들고 검증한 12문제, 초기 시드)

src/education/
  schemas.py                공용 스키마 (Pydantic)
  concepts.py               개념 트리 로더와 검증
  config.py · security.py   설정(.env), 비밀번호 해시(Argon2), 로그인 토큰(JWT)
  db/models.py              PostgreSQL 테이블 (SQLAlchemy 2.0)
  api/                      FastAPI — main.py, dto.py(요청·응답), routers/
  services/learning.py      채점, 오답노트, 약점 통계
  services/tutor.py         대화 답변 (AI 연결 전 임시: 문제 은행에서 고르기)
  services/notes.py         내 맞춤 개념 정리 + 암기 카드 (생성 → 검증 에이전트)
  services/review.py        서술형 풀이 확인 (손글씨 사진도 읽음, 처음 틀린 단계 표시)
  seed.py                   개념·문제·데모 계정 적재
migrations/                 Alembic 마이그레이션
docker-compose.yml          개발용 PostgreSQL 17 (127.0.0.1:5433)
Dockerfile · docker-compose.prod.yml · deploy/Caddyfile   운영 배포 (docs/DEPLOY.md)
scripts/export_concepts.py  개념 트리 → prototype/concepts.js
scripts/backup.sh           운영 서버 DB·업로드 백업 (+ S3)
scripts/auto_deploy.sh      운영 서버 자동 배포 (main 새 커밋 → 다시 빌드)
scripts/harden_server.sh    운영 서버 보안 기본 설정
.github/workflows/ci.yml    push 마다 전체 테스트
tests/                      API·마이그레이션 테스트 (테스트 전용 DB 사용)

prototype/                  화면 — 서버(localhost:8000/app)로 열면 로그인한 계정의 DB 데이터, 파일로 열면 localStorage 샘플 데이터
  login.html · index.html   로그인 / 학습자 앱
  terms.html · privacy.html · consent.html   이용약관 / 개인정보처리방침 / 가입 동의 안내 (legal.css)
  app.js · app.css · store.js · dots.js · concepts.js(자동 생성)
```

## 처음 실행
```bash
cp .env.example .env                 # 비밀번호·JWT 키를 채운다
docker compose up -d                 # PostgreSQL (eureka, eureka_test DB)
uv sync
uv run alembic upgrade head          # 테이블 만들기
uv run python -m education.seed --demo   # 개념·문제 + 데모 계정 (demo@example.com / eureka-demo)
uv run uvicorn education.api.main:app --reload
```
- API 문서: http://127.0.0.1:8000/docs
- 프로토타입: http://127.0.0.1:8000/app/login.html

## 운영 배포
https://eurekai.cloud — AWS EC2(시드니) 한 대에 Caddy(HTTPS) + API + PostgreSQL 을 Docker Compose 로 띄우고, 백업은 S3 에 둔다. 순서는 [docs/DEPLOY.md](docs/DEPLOY.md).

## 개발
```bash
uv run pytest                                      # 전체 테스트 (eureka_test DB를 비우고 마이그레이션으로 다시 만듦)
uv run alembic revision --autogenerate -m "설명"   # 모델을 바꿨을 때 → 생성된 파일을 꼭 검토
uv run python scripts/export_concepts.py           # 개념 트리를 바꿨을 때
```
모델을 바꾸고 마이그레이션을 만들지 않으면 `test_models_match_migrations` 가 실패한다.

## API 요약 (`/api`)
| 영역 | 엔드포인트 |
|---|---|
| 인증 | `POST /auth/signup` · `POST /auth/login` · `GET/PATCH /me` · `DELETE /me` (회원 탈퇴, `{confirm_email}`) |
| 간편 로그인 | `GET /auth/providers` · `GET /auth/{google\|kakao}/start` → `/callback` · `POST /auth/social/exchange` · `POST /auth/social/complete` |
| 프로젝트 | `GET/POST /projects` · `GET/PATCH/DELETE /projects/{id}` (GET 은 정답률·약점 요약 포함) |
| 대화 | `GET/POST /sessions` · `GET/PATCH/DELETE /sessions/{id}` · `POST /sessions/{id}/messages` |
| 문제·풀이 | `GET /problems` · `GET /problems/{id}` · `POST /attempts` · `POST /problems/{id}/review` (서술형 풀이 확인, 글 또는 손글씨 PNG) |
| 오답노트 | `GET /wrong-notes` (과목·이유·안 푼 것만·프로젝트 필터) · `PATCH/DELETE /wrong-notes/{id}` |
| 라이브러리 | `GET /concepts` · `GET /concepts/{id}` · `GET/POST /concepts/{id}/note` (내 맞춤 개념 정리, 만들 때 카드도 덱에) · `GET /saved` · `PUT/DELETE /saved/{problem_id}` · `GET /cards` · `PATCH /cards/{id}` · `POST /cards/reset` |
| 통계 | `GET /stats` (오늘 푼 문제, 연속 학습일, 과목별 정답률, 약점) |
| 기출 | `POST /projects/{id}/materials` (PDF·사진 업로드 → AI 분석) · `GET /projects/{id}/materials` · `GET /projects/{id}/past-problems` · `DELETE /materials/{id}` |
| 기출 기반 생성 | `POST /projects/{id}/generate` `{level: easier\|same\|harder, count}` → 결과를 프로젝트의 새 대화로 |
| 계정 | `PATCH /me` (생년월일·학교·전공·주소·캐릭터) · `POST /me/avatar` (사진) · `GET /users/{id}/avatar` · `GET /search/schools?q=` (나이스 학교 검색) |
| 화면 동기화 | `GET /sync` — 로그인한 화면이 처음 열릴 때 내 데이터를 한 번에 |

- 문제의 **정답과 해설은 답을 제출한 뒤에만** 응답에 들어간다
- 올린 기출과 그것을 본보기로 만든 문제는 **올린 사람에게만** 보인다 (`problems.owner_user_id`)
- 프로필 사진은 256px WEBP 로 다시 만들어 저장해 **위치·기기 정보(EXIF)가 남지 않는다**
- AI 호출은 모두 `llm_calls` 에 토큰·비용·시간을 기록한다 (`uv run python -m education.generate` 로 문제 은행 채우기)
- 모든 사용자 데이터는 본인 것만 보이고, 남의 데이터는 존재 여부와 상관없이 404
- '오늘'의 기준 시간대는 `Asia/Seoul` (`TIMEZONE` 으로 변경)

## 간편 로그인 (Google · 카카오)
1. 아래 콘솔에서 앱을 등록하고 키를 받아 `.env` 에 넣는다 (키는 채팅·코드에 붙여넣지 말 것)
2. 서버를 다시 켜고 **http://localhost:8000/app/login.html** 로 연다 (`127.0.0.1` 이 아니라 `localhost` — Google 이 IP 주소를 허용하지 않음)

| | Google Cloud Console | Kakao Developers |
|---|---|---|
| 등록 | 프로젝트 → OAuth 동의 화면(외부, 범위 `openid` `email` `profile`, 테스트 사용자 추가) → OAuth 클라이언트 ID(웹 애플리케이션) | 애플리케이션 추가 → 카카오 로그인 활성화 → 플랫폼 Web 에 `http://localhost:8000` |
| Redirect URI | `http://localhost:8000/api/auth/google/callback` | `http://localhost:8000/api/auth/kakao/callback` |
| `.env` | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | `KAKAO_REST_API_KEY`, `KAKAO_CLIENT_SECRET`(보안 메뉴, 선택) |
| 동의 항목 | — | 닉네임(필수), 카카오계정 이메일(비즈 앱 전환 필요할 수 있음) |

동작 방식
- 처음 온 사용자는 약관 동의 화면을 한 번 거쳐 가입되고, 다음부터는 버튼 하나로 로그인된다
- 카카오에서 이메일을 못 받으면 동의 화면에서 이메일을 입력받는다
- 같은 이메일의 기존 계정에는 **양쪽 모두 인증된 이메일일 때만** 자동 연결한다 (남의 이메일로 미리 가입한 계정 가로채기 방지). 이메일로 가입한 계정은 인증 메일 기능 전까지 자동 연결하지 않고 '이메일로 로그인' 안내를 한다
- 위조 방지: 로그인 시작 시 state 쿠키를 발급해 콜백에서 확인하고, 로그인 결과는 2분짜리 일회성 티켓으로만 화면에 전달한다
- 실제 서비스 공개 전: Google 은 앱 게시(그전엔 테스트 사용자 100명), 카카오는 실제 도메인 등록·검수, 둘 다 개인정보처리방침 URL 필요

## 로드맵
- [x] Phase 0: 개념 트리, 데이터 스키마
- [x] UI 프로토타입: 로그인, 메인, 메뉴별 화면
- [x] 백엔드: PostgreSQL + FastAPI, 인증, 풀이·오답노트·통계 API
- [x] 로그인 화면 API 연결: 이메일 로그인·가입, Google·카카오 간편 로그인 (키 발급 후 바로 사용)
- [x] 메인 화면 API 연결, AI 문제 생성 + 검증 (OpenAI), 기출 업로드·분석·기출 기반 생성, 주관식, 계정 설정·프로필 사진
- [x] Phase 3: ③ 내 맞춤 개념 정리 / 암기 카드 생성 (풀이·오답 기록 반영, 검증 에이전트 통과분만)
- [ ] Phase 4: ④ 기출 RAG + 난이도 조절 생성
- [ ] Phase 5: 과목 확장

## 메모
- 개념 트리는 2015 개정 교육과정 기준이다. 2028학년도 수능부터는 2022 개정 교육과정이 적용되므로, 그때 `curriculum` 필드로 버전을 나눠 추가한다.
- 기출 원문은 저작권 때문에 내부 분석용으로만 쓰고, 학습자에게는 새로 생성한 문제만 보여준다.
- 샘플 문제 은행은 `data/problems/sample.yaml` 과 `prototype/store.js` 에 함께 있다. 프로토타입을 API에 연결하면 store.js 쪽은 지운다.

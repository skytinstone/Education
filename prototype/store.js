// 데이터 저장소 — 두 가지 모드
// - 서버 모드: API 서버(http://…/app/)로 열고 로그인했으면, /api/sync 로 내 데이터를 받아 오고 변경은 API 로 보낸다
// - 로컬 모드: 파일로 직접 열면(file://) 브라우저 localStorage 의 샘플 데이터로 동작한다 (디자인 확인용)
// 화면(app.js)은 어느 모드든 같은 함수(Store.project, Store.answer …)를 쓴다.
// 변경 함수는 서버 모드에서 Promise 를 돌려주므로, 결과가 필요한 곳은 await 한다.

// ---------- 샘플 문제 은행 (AI 연결 전까지 사용) ----------
// 수식은 LaTeX — 인라인 $…$, 크게 보일 식은 \displaystyle. 화면에서 KaTeX 로 렌더링한다.
const T = String.raw;
const PROBLEM_BANK = [
  {
    id: "pb_log", domain: "math", conceptIds: ["math.math1.exp_log.log_properties"], difficulty: 1,
    stem: T`$\log_2 8 + \log_3 9$의 값은?`, choices: ["3", "4", "5", "6", "7"], answer: "3",
    solution: T`$\log_2 8 = \log_2 2^3 = 3$, $\log_3 9 = \log_3 3^2 = 2$이므로 $3 + 2 = 5$`,
  },
  {
    id: "pb_subst", domain: "math", conceptIds: ["math.calculus.int_methods.substitution_parts"], difficulty: 2,
    stem: T`$\displaystyle\int_0^1 2x\,e^{x^2}\,dx$의 값은?`,
    choices: [T`$e-1$`, T`$e$`, T`$e+1$`, T`$2e-1$`, T`$\dfrac{e-1}{2}$`], answer: "1",
    solution: T`$t = x^2$으로 치환하면 $dt = 2x\,dx$이고, $x$가 $0 \to 1$일 때 $t$도 $0 \to 1$이다. 따라서 $\displaystyle\int_0^1 e^t\,dt = e - 1$`,
  },
  {
    id: "pb_defint", domain: "math", conceptIds: ["math.math2.integration.definite_integral"], difficulty: 3,
    stem: T`함수 $f(x) = \displaystyle\int_1^x (3t^2 - 2t)\,dt$에 대하여 $f'(2)$의 값은?`, choices: ["4", "6", "8", "10", "12"], answer: "3",
    solution: T`정적분으로 정의된 함수를 미분하면 $f'(x) = 3x^2 - 2x$이므로 $f'(2) = 12 - 4 = 8$`,
  },
  {
    id: "pb_seq", domain: "math", conceptIds: ["math.math1.sequence.arithmetic_geometric"], difficulty: 1,
    stem: T`첫째항이 $3$, 공차가 $4$인 등차수열의 제$10$항은?`, choices: ["35", "37", "39", "41", "43"], answer: "3",
    solution: T`$a_n = a_1 + (n-1)d$이므로 $a_{10} = 3 + 9 \times 4 = 39$`,
  },
  {
    id: "pb_cond", domain: "math", conceptIds: ["math.prob_stat.probability.conditional_probability"], difficulty: 2,
    stem: T`두 사건 $A$, $B$에 대하여 $P(A) = 0.5$, $P(A \cap B) = 0.2$일 때, $P(B \mid A)$의 값은?`,
    choices: ["0.2", "0.3", "0.4", "0.5", "0.6"], answer: "3",
    solution: T`$P(B \mid A) = \dfrac{P(A \cap B)}{P(A)} = \dfrac{0.2}{0.5} = 0.4$`,
  },
  {
    id: "pb_kin", domain: "physics", conceptIds: ["physics.physics1.mechanics_energy.kinematics"], difficulty: 1,
    stem: T`정지 상태에서 출발한 물체가 $2\,\mathrm{m/s^2}$의 등가속도로 $5$초 동안 이동한 거리는?`,
    choices: [T`$10\,\mathrm{m}$`, T`$20\,\mathrm{m}$`, T`$25\,\mathrm{m}$`, T`$50\,\mathrm{m}$`, T`$100\,\mathrm{m}$`], answer: "3",
    solution: T`$s = \dfrac{1}{2}at^2 = \dfrac{1}{2} \times 2 \times 5^2 = 25\,\mathrm{m}$`,
  },
  {
    id: "pb_mom", domain: "physics", conceptIds: ["physics.physics1.mechanics_energy.momentum_impulse"], difficulty: 2,
    stem: T`$3\,\mathrm{m/s}$로 움직이는 $2\,\mathrm{kg}$ 물체가 정지한 $1\,\mathrm{kg}$ 물체와 충돌한 뒤 한 덩어리가 되었다. 충돌 직후 속력은?`,
    choices: [T`$1\,\mathrm{m/s}$`, T`$1.5\,\mathrm{m/s}$`, T`$2\,\mathrm{m/s}$`, T`$3\,\mathrm{m/s}$`, T`$6\,\mathrm{m/s}$`], answer: "3",
    solution: T`운동량 보존: $2 \times 3 = (2 + 1)\,v$이므로 $v = 2\,\mathrm{m/s}$`,
  },
  {
    id: "pb_mole", domain: "chemistry", conceptIds: ["chemistry.chemistry1.first_steps.mole"], difficulty: 1,
    stem: T`물$(\mathrm{H_2O})$ $36\,\mathrm{g}$의 양은 몇 $\mathrm{mol}$인가? (단, $\mathrm{H}$, $\mathrm{O}$의 원자량은 각각 $1$, $16$이다.)`,
    choices: [T`$0.5\,\mathrm{mol}$`, T`$1\,\mathrm{mol}$`, T`$2\,\mathrm{mol}$`, T`$3\,\mathrm{mol}$`, T`$4\,\mathrm{mol}$`], answer: "3",
    solution: T`$\mathrm{H_2O}$의 몰 질량은 $18\,\mathrm{g/mol}$이므로 $36 \div 18 = 2\,\mathrm{mol}$`,
  },
  {
    id: "pb_neut", domain: "chemistry", conceptIds: ["chemistry.chemistry1.dynamic_reactions.neutralization"], difficulty: 2,
    stem: T`$0.1\,\mathrm{M}$ $\mathrm{HCl}(aq)$ $20\,\mathrm{mL}$를 완전히 중화하는 데 필요한 $0.2\,\mathrm{M}$ $\mathrm{NaOH}(aq)$의 부피는?`,
    choices: [T`$5\,\mathrm{mL}$`, T`$10\,\mathrm{mL}$`, T`$20\,\mathrm{mL}$`, T`$40\,\mathrm{mL}$`, T`$50\,\mathrm{mL}$`], answer: "2",
    solution: T`$\mathrm{H^+}$의 양은 $0.1 \times 0.020 = 0.002\,\mathrm{mol}$. $\mathrm{OH^-}$도 $0.002\,\mathrm{mol}$이 필요하므로 $0.002 \div 0.2 = 0.010\,\mathrm{L} = 10\,\mathrm{mL}$`,
  },
  {
    id: "pb_chrom", domain: "biology", conceptIds: ["biology.biology1.genetics.chromosome_cell_division"], difficulty: 1,
    stem: T`사람의 체세포 염색체 수가 $46$개일 때, 정자 하나에 들어 있는 염색체 수는?`, choices: ["22개", "23개", "44개", "46개", "92개"], answer: "2",
    solution: T`감수 분열로 염색체 수가 절반이 되므로 $46 \div 2 = 23$개`,
  },
  {
    id: "pb_half", domain: "earth_science", conceptIds: ["earth_science.earth1.solid_earth.relative_absolute_age"], difficulty: 2,
    stem: T`반감기가 $1$억 년인 방사성 원소가 $3$억 년이 지나면 처음 양의 몇 배가 남는가?`,
    choices: [T`$\dfrac{1}{2}$`, T`$\dfrac{1}{3}$`, T`$\dfrac{1}{4}$`, T`$\dfrac{1}{6}$`, T`$\dfrac{1}{8}$`], answer: "5",
    solution: T`반감기가 $3$번 지났으므로 $\left(\dfrac{1}{2}\right)^3 = \dfrac{1}{8}$`,
  },
  {
    id: "pb_hr", domain: "earth_science", conceptIds: ["earth_science.earth1.space.stellar_properties"], difficulty: 2,
    stem: "H-R도의 주계열성에서 표면 온도가 높은 별일수록 광도는 어떠한가?", choices: ["작다", "크다", "같다", "온도와 관계없다", "알 수 없다"], answer: "2",
    solution: "주계열성은 H-R도에서 왼쪽 위(고온, 고광도)부터 오른쪽 아래(저온, 저광도)로 이어지므로, 표면 온도가 높을수록 광도가 크다",
  },
];

const ERROR_TYPES = {
  concept_gap: "개념 부족",
  misapplication: "적용 실수",
  calculation: "계산 실수",
  misread: "문제 오독",
  trap: "함정",
  time_pressure: "시간 부족",
  unknown: "미분류",
};

const Store = (() => {
  const KEY = "eureka.v1";
  const DAY = 864e5;
  const listeners = new Set();
  const uid = (p) => `${p}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
  const TOKEN = (() => { try { return localStorage.getItem("eureka.token"); } catch { return null; } })();
  const MODE = location.protocol.startsWith("http") ? "api" : "local";

  let state = null;
  let bank = {};              // 문제 id → 문제 (서버 모드에선 정답·해설은 푼 문제만)
  const pending = new Set();  // 답변을 기다리는 대화 id
  const renamed = {};         // 임시 대화 id → 서버가 준 id
  let onError = () => {};

  function commit() {
    if (MODE === "local") {
      try { localStorage.setItem(KEY, JSON.stringify(state)); } catch { /* 저장 불가 — 메모리에서만 유지 */ }
    }
    listeners.forEach((fn) => fn(state));
  }
  const startOfDay = (t) => new Date(new Date(t).toDateString()).getTime();

  // ================= 서버 통신 =================
  async function api(path, { method = "GET", body, form } = {}) {
    const headers = { Authorization: `Bearer ${TOKEN}` };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const res = await fetch(`/api${path}`, { method, headers, body: form ?? (body !== undefined ? JSON.stringify(body) : undefined) });
    if (res.status === 401) {
      try { localStorage.removeItem("eureka.token"); } catch { /* 무시 */ }
      location.href = "login.html";
      throw new Error("로그인이 필요해요");
    }
    if (res.status === 204) return null;
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const d = data.detail;
      throw new Error(typeof d === "string" ? d : Array.isArray(d) ? (d[0]?.msg ?? "").replace(/^Value error, /, "") : "잠시 후 다시 시도해 주세요");
    }
    return data;
  }
  // 낙관적 변경 뒤 서버 요청 — 실패하면 서버 데이터로 되돌리고 알린다
  const send = (path, opts) => api(path, opts).catch(async (e) => { onError(e.message); await boot(); throw e; });

  const toProblem = (p) => ({
    id: p.id, domain: p.domain, conceptIds: p.concept_ids ?? p.conceptIds, difficulty: p.difficulty,
    problemType: p.problem_type ?? p.problemType, stem: p.stem, choices: p.choices, source: p.source,
    answer: p.answer ?? null, solution: p.solution ?? null,
  });
  function mergeProblem(raw) {
    const p = toProblem(raw);
    const old = bank[p.id];
    bank[p.id] = { ...old, ...p, answer: p.answer ?? old?.answer ?? null, solution: p.solution ?? old?.solution ?? null };
  }
  const toProject = (p) => ({
    id: p.id, name: p.name, subjectId: p.subject_id, unitIds: p.unit_ids, goal: p.goal, examDate: p.exam_date,
    questionType: p.question_type, pinned: p.pinned, createdAt: Date.parse(p.created_at),
  });
  function toSession(s) {
    s.messages.forEach((msg) => msg.problems.forEach(mergeProblem));
    return {
      id: s.id, projectId: s.project_id, title: s.title, createdAt: Date.parse(s.created_at), updatedAt: Date.parse(s.updated_at),
      messages: s.messages.map((msg) => ({ role: msg.role, text: msg.text, problemIds: msg.problems.map((p) => p.id), at: Date.parse(msg.created_at) })),
    };
  }
  const PROJECT_KEYS = { name: "name", subjectId: "subject_id", unitIds: "unit_ids", goal: "goal", examDate: "exam_date", questionType: "question_type", pinned: "pinned" };
  const snake = (patch) => Object.fromEntries(Object.entries(patch).filter(([k]) => PROJECT_KEYS[k]).map(([k, v]) => [PROJECT_KEYS[k], v]));

  async function boot() {
    if (MODE === "local") {
      try { state = JSON.parse(localStorage.getItem(KEY)); } catch { state = null; }
      state ??= seed();
      bank = Object.fromEntries(PROBLEM_BANK.map((p) => [p.id, { problemType: "multiple_choice", ...p }]));
      return;
    }
    if (!TOKEN) {
      location.href = "login.html";
      return new Promise(() => {}); // 이동하는 동안 화면을 그리지 않음
    }
    const d = await api("/sync");
    bank = {};
    d.problems.forEach(mergeProblem);
    delete d.problems;
    state = d;
    listeners.forEach((fn) => fn(state));
  }

  // ================= 로컬 모드: AI 대신 샘플 문제 고르기 =================
  const KEYWORDS = [
    ["math", /수학|미적|적분|미분|로그|수열|확률|함수|모의고사/],
    ["physics", /물리|운동|역학|가속|운동량|속력/],
    ["chemistry", /화학|몰|중화|산화|염기|분자/],
    ["biology", /생명|생물|염색체|유전|세포/],
    ["earth_science", /지구|별|H-R|반감기|지층|은하/],
  ];
  function localReply(text, projectDomain) {
    let domain = projectDomain;
    for (const [d, re] of KEYWORDS) if (re.test(text)) { domain = d; break; }
    const pool = PROBLEM_BANK.filter((p) => !domain || p.domain === domain);
    const n = Math.min(Number(text.match(/(\d+)\s*(문제|문항|개)/)?.[1]) || 2, 3, pool.length);
    const ids = [...pool].sort(() => Math.random() - 0.5).slice(0, n).map((p) => p.id);
    return { role: "ai", text: `AI 연결 전이라 문제 은행의 샘플 문제 ${ids.length}개를 보여드려요. 틀린 문제는 오답노트에 자동으로 저장돼요.`, problemIds: ids };
  }

  // ---------- 처음 열었을 때 보여줄 샘플 데이터 (로컬 모드) ----------
  function seed() {
    const now = Date.now();
    const at = (daysAgo, h = 0) => now - daysAgo * DAY - h * 36e5;
    const isoDate = (daysAhead) => new Date(now + daysAhead * DAY).toISOString().slice(0, 10);

    const projects = [
      { id: "p_math", name: "2027 수능 미적분", subjectId: "math.calculus", unitIds: [], goal: "1등급", examDate: isoDate(24), pinned: false, createdAt: at(20) },
      { id: "p_chem", name: "화학I 중간고사", subjectId: "chemistry.chemistry1", unitIds: [], goal: "90점 이상", examDate: isoDate(12), pinned: false, createdAt: at(15) },
      { id: "p_phys", name: "물리 역학 기초 다지기", subjectId: "physics.physics1", unitIds: ["physics.physics1.mechanics_energy"], goal: "", examDate: null, pinned: false, createdAt: at(9) },
    ];

    const reply = (problemIds) => ({ role: "ai", text: "AI 연결 전이라 문제 은행의 샘플 문제를 보여드려요.", problemIds, at: 0 });
    const session = (id, projectId, title, daysAgo, ask, problemIds) => ({
      id, projectId, title, createdAt: at(daysAgo, 1), updatedAt: at(daysAgo),
      messages: [{ role: "user", text: ask, at: at(daysAgo, 1) }, { ...reply(problemIds), at: at(daysAgo) }],
    });
    const sessions = [
      session("s1", "p_math", "치환적분 변형 문제", 0, "치환적분 3점짜리 문제 내줘", ["pb_subst", "pb_defint"]),
      session("s2", "p_chem", "중화반응 왜 틀렸는지", 0.4, "중화반응 문제 다시 풀어볼래", ["pb_neut", "pb_mole"]),
      session("s3", null, "로그 성질 개념 정리", 1, "로그 성질 문제 하나 내줘", ["pb_log"]),
      session("s4", "p_math", "6월 모의고사 약점 분석", 3, "수열이랑 확률 문제 섞어서 내줘", ["pb_seq", "pb_cond"]),
      session("s5", null, "H-R도 암기 카드 만들기", 5, "H-R도 문제 내줘", ["pb_hr", "pb_half"]),
      session("s6", "p_phys", "등가속도 운동 그래프 문제", 10, "등가속도 운동 문제 내줘", ["pb_kin", "pb_mom"]),
    ];

    // 최근 7일 풀이 기록 (연속 학습 7일, 오늘 12문제)
    const projectOf = { math: "p_math", chemistry: "p_chem", physics: "p_phys" };
    const ids = PROBLEM_BANK.map((p) => p.id);
    const bank = Object.fromEntries(PROBLEM_BANK.map((p) => [p.id, p]));
    const attempts = [];
    for (let d = 6; d >= 0; d--) {
      const n = d === 0 ? 12 : 6;
      for (let i = 0; i < n; i++) {
        const pid = ids[(i * 5 + d * 3) % ids.length];
        attempts.push({
          id: uid("a"), problemId: pid, projectId: projectOf[bank[pid].domain] ?? null, sessionId: null,
          answer: "", correct: (i + d) % 3 !== 0, at: at(d, 10 - i * 0.5),
        });
      }
    }

    const wrongNotes = [
      { id: "w1", problemId: "pb_subst", projectId: "p_math", answer: "2", errorType: "calculation", createdAt: at(0, 2), resolvedAt: null },
      { id: "w2", problemId: "pb_defint", projectId: "p_math", answer: "1", errorType: "concept_gap", createdAt: at(2), resolvedAt: null },
      { id: "w3", problemId: "pb_neut", projectId: "p_chem", answer: "3", errorType: "misapplication", createdAt: at(3), resolvedAt: null },
      { id: "w4", problemId: "pb_hr", projectId: null, answer: "1", errorType: "concept_gap", createdAt: at(6), resolvedAt: at(4) },
    ];

    const cards = [
      ["math.math1.exp_log.log_properties", "로그의 밑 변환 공식", "log_a b = log_c b ÷ log_c a"],
      ["math.math1.exp_log.log_properties", "log_a (MN) = ?", "log_a M + log_a N"],
      ["chemistry.chemistry1.atomic_world.periodic_trends", "같은 주기에서 원자 번호가 커지면 원자 반지름은?", "작아진다 (유효 핵전하가 커지기 때문)"],
      ["chemistry.chemistry1.atomic_world.periodic_trends", "같은 족에서 아래로 갈수록 이온화 에너지는?", "작아진다 (전자 껍질 수가 늘어나기 때문)"],
      ["earth_science.earth1.space.stellar_properties", "H-R도 왼쪽 위에 있는 별의 특징은?", "표면 온도가 높고 광도가 크다"],
      ["earth_science.earth1.space.stellar_properties", "백색 왜성은 H-R도의 어디에 있나?", "왼쪽 아래 (온도는 높고 광도는 작다)"],
      ["physics.physics1.mechanics_energy.momentum_impulse", "운동량의 정의는?", "p = mv (방향이 있는 벡터량)"],
      ["physics.physics1.mechanics_energy.momentum_impulse", "충격량과 운동량의 관계는?", "충격량 = 운동량의 변화량 (FΔt = Δp)"],
    ].map(([conceptId, front, back], i) => ({ id: `c${i + 1}`, conceptId, front, back, known: null }));

    return {
      version: 1,
      user: { name: "민석", dailyGoal: 20 },
      projects, sessions, attempts, wrongNotes, cards,
      savedProblemIds: ["pb_log", "pb_kin"],
    };
  }

  // ================= 조회 (두 모드 공통) =================
  const q = {
    problem: (id) => bank[id],
    project: (id) => state.projects.find((p) => p.id === id),
    session: (id) => state.sessions.find((s) => s.id === id),
    isPending: (sessionId) => pending.has(sessionId),
    resolveId: (id) => renamed[id] ?? id,
    openNotes: () => state.wrongNotes.filter((n) => !n.resolvedAt),
    todayCount: () => state.attempts.filter((a) => a.at >= startOfDay(Date.now())).length,
    streak() {
      const days = new Set(state.attempts.map((a) => startOfDay(a.at)));
      let n = 0;
      for (let d = startOfDay(Date.now()); days.has(d); d -= DAY) n++;
      return n;
    },
    // 개념별 정답률 (낮은 순) — 약점 분석
    conceptStats({ projectId, domain } = {}) {
      const stats = {};
      for (const a of state.attempts) {
        if (projectId && a.projectId !== projectId) continue;
        const p = bank[a.problemId];
        if (!p || (domain && p.domain !== domain)) continue;
        for (const c of p.conceptIds) {
          stats[c] ??= { conceptId: c, attempts: 0, correct: 0 };
          stats[c].attempts++;
          stats[c].correct += a.correct ? 1 : 0;
        }
      }
      return Object.values(stats)
        .map((s) => ({ ...s, accuracy: s.correct / s.attempts }))
        .sort((a, b) => a.accuracy - b.accuracy || b.attempts - a.attempts);
    },
    accuracy({ projectId, domain } = {}) {
      const list = state.attempts.filter((a) =>
        (!projectId || a.projectId === projectId) && (!domain || bank[a.problemId]?.domain === domain));
      return list.length ? list.filter((a) => a.correct).length / list.length : null;
    },
    lastAttempt: (sessionId, problemId) =>
      [...state.attempts].reverse().find((a) => a.sessionId === sessionId && a.problemId === problemId),
  };

  // ================= 변경 =================
  const local = MODE === "local";
  const ops = {
    async createProject({ name, subjectId, unitIds = [], goal = "", examDate = null, questionType = "multiple_choice" }) {
      if (local) {
        const p = { id: uid("p"), name, subjectId, unitIds, goal, examDate, questionType, pinned: false, createdAt: Date.now() };
        state.projects.push(p);
        commit();
        return p.id;
      }
      const p = toProject(await api("/projects", { method: "POST", body: snake({ name, subjectId, unitIds, goal, examDate, questionType }) }));
      state.projects.push(p);
      commit();
      return p.id;
    },
    updateProject(id, patch) {
      Object.assign(q.project(id), patch);
      commit();
      if (!local) return send(`/projects/${id}`, { method: "PATCH", body: snake(patch) });
    },
    deleteProject(id) {
      state.projects = state.projects.filter((p) => p.id !== id);
      state.sessions = state.sessions.filter((s) => s.projectId !== id);
      state.attempts.forEach((a) => { if (a.projectId === id) a.projectId = null; });
      state.wrongNotes.forEach((n) => { if (n.projectId === id) n.projectId = null; });
      commit();
      if (!local) return send(`/projects/${id}`, { method: "DELETE" });
    },

    // 질문 보내기 — 새 대화면 sessionId 없이. 바로 대화 id 를 돌려주고, 답은 나중에 도착한다(Store.isPending)
    sendMessage({ sessionId = null, projectId = null, text }) {
      const now = Date.now();
      let s = sessionId && q.session(sessionId);
      if (!s) {
        s = { id: uid(local ? "s" : "tmp"), projectId, title: text.length > 24 ? `${text.slice(0, 24)}…` : text,
          createdAt: now, updatedAt: now, messages: [] };
        state.sessions.push(s);
      }
      s.messages.push({ role: "user", text, at: now });
      s.updatedAt = now;
      const id = s.id;
      pending.add(id);
      commit();

      const done = local
        ? new Promise((resolve) => setTimeout(() => {
            const domain = CONCEPTS.find((c) => c.id === q.project(s.projectId)?.subjectId)?.domain;
            s.messages.push({ ...localReply(text, domain), at: Date.now() });
            s.updatedAt = Date.now();
            resolve(id);
          }, 800))
        : (sessionId
            ? api(`/sessions/${id}/messages`, { method: "POST", body: { text } }).then((msgs) => {
                msgs.forEach((msg) => msg.problems.forEach(mergeProblem));
                s.messages.splice(-1, 1, ...msgs.map((msg) => ({ role: msg.role, text: msg.text, problemIds: msg.problems.map((p) => p.id), at: Date.parse(msg.created_at) })));
                s.updatedAt = Date.now();
                return id;
              })
            : api("/sessions", { method: "POST", body: { text, project_id: projectId } }).then((detail) => {
                const real = toSession(detail);
                state.sessions = state.sessions.map((x) => (x.id === id ? real : x));
                renamed[id] = real.id;
                return real.id;
              }));
      done.catch((e) => {
        s.messages.push({ role: "ai", text: `답변을 만들지 못했어요: ${e.message}`, problemIds: [], at: Date.now() });
      }).finally(() => { pending.delete(id); commit(); });
      return { id, done };
    },
    updateSession(id, patch) {
      Object.assign(q.session(id), patch);
      commit();
      if (!local) {
        const body = {};
        if ("title" in patch) body.title = patch.title;
        if ("projectId" in patch) body.project_id = patch.projectId;
        return send(`/sessions/${id}`, { method: "PATCH", body });
      }
    },
    deleteSession(id) {
      state.sessions = state.sessions.filter((s) => s.id !== id);
      commit();
      if (!local) return send(`/sessions/${id}`, { method: "DELETE" });
    },

    // 문제 풀이 기록. 틀리면 오답노트에 넣고, 오답노트 문제를 다시 맞히면 극복 처리
    async answer({ problemId, answer, projectId = null, sessionId = null }) {
      const open = () => state.wrongNotes.find((n) => n.problemId === problemId && !n.resolvedAt);
      let correct, noteId = null, resolved = false;
      if (local) {
        const p = bank[problemId];
        correct = p.problemType === "short_answer" ? Number(String(answer).replace(/,/g, "")) === Number(p.answer) : p.answer === answer;
        if (!correct && !open()) state.wrongNotes.push({ id: uid("w"), problemId, projectId, answer, errorType: "unknown", createdAt: Date.now(), resolvedAt: null });
        else if (correct && open()) { open().resolvedAt = Date.now(); resolved = true; }
        noteId = open()?.id ?? null;
      } else {
        const r = await api("/attempts", { method: "POST", body: { problem_id: problemId, answer, project_id: projectId, session_id: sessionId } });
        correct = r.correct;
        Object.assign(bank[problemId], { answer: r.answer, solution: r.solution });
        if (r.resolved && open()) { open().resolvedAt = Date.now(); resolved = true; }
        if (!correct && r.wrong_note_id && !open()) {
          state.wrongNotes.push({ id: r.wrong_note_id, problemId, projectId, answer, errorType: "unknown", createdAt: Date.now(), resolvedAt: null });
        }
        noteId = r.wrong_note_id;
      }
      state.attempts.push({ id: uid("a"), problemId, projectId, sessionId, answer, correct, at: Date.now() });
      commit();
      return { correct, resolved, noteId };
    },
    setErrorType(noteId, errorType) {
      state.wrongNotes.find((n) => n.id === noteId).errorType = errorType;
      commit();
      if (!local) return send(`/wrong-notes/${noteId}`, { method: "PATCH", body: { error_type: errorType } });
    },
    deleteNote(noteId) {
      state.wrongNotes = state.wrongNotes.filter((n) => n.id !== noteId);
      commit();
      if (!local) return send(`/wrong-notes/${noteId}`, { method: "DELETE" });
    },

    toggleSaved(problemId) {
      const on = !state.savedProblemIds.includes(problemId);
      state.savedProblemIds = on ? [...state.savedProblemIds, problemId] : state.savedProblemIds.filter((id) => id !== problemId);
      commit();
      if (!local) return send(`/saved/${problemId}`, { method: on ? "PUT" : "DELETE" });
    },
    markCard(id, known) {
      state.cards.find((c) => c.id === id).known = known;
      commit();
      if (!local) return send(`/cards/${id}`, { method: "PATCH", body: { known } });
    },
    resetCards() {
      state.cards.forEach((c) => (c.known = null));
      commit();
      if (!local) return send("/cards/reset", { method: "POST" });
    },
    // 계정 정보 — name, dailyGoal, birthDate, school, major, address (빈 문자열이면 지움)
    updateUser(patch) {
      Object.assign(state.user, patch);
      commit();
      if (!local) {
        const body = { name: patch.name, daily_goal: patch.dailyGoal, birth_date: patch.birthDate, school: patch.school, major: patch.major, address: patch.address };
        if ("birthDate" in patch && !patch.birthDate) body.birth_date = null;
        return send("/me", { method: "PATCH", body });
      }
    },
    // 내 맞춤 개념 정리 — 서버 모드에서만 (없으면 null)
    getNote(conceptId) {
      return local ? Promise.resolve(null) : api(`/concepts/${conceptId}/note`);
    },
    // 개념 정리 + 암기 카드를 만들고 검증 (1~2분). 새 카드는 내 덱에 바로 넣는다
    async createNote(conceptId) {
      const r = await api(`/concepts/${conceptId}/note`, { method: "POST" });
      state.cards.push(...r.added_cards.map((c) => ({ id: c.id, conceptId: c.concept_id, front: c.front, back: c.back, known: c.known })));
      commit();
      return r;
    },
    // 서술형 풀이 확인 — { text } 또는 { image: PNG data URL }. 서버 모드에서만
    reviewSolution(problemId, body) {
      if (local) return Promise.reject(new Error("서술형 풀이 확인은 로그인한 서버 화면에서 쓸 수 있어요"));
      return api(`/problems/${problemId}/review`, { method: "POST", body });
    },
    // 학교 검색 (나이스, 서버가 대신 물음) — 로컬 모드에선 빈 목록
    searchSchools(q) {
      return local ? Promise.resolve([]) : api(`/search/schools?q=${encodeURIComponent(q)}`);
    },
    // 회원 탈퇴 — 확인용으로 내 이메일을 그대로 보낸다
    async deleteAccount(confirmEmail) {
      await api("/me", { method: "DELETE", body: { confirm_email: confirmEmail } });
    },
    // 프로필 사진: "initial" 또는 Eureka 캐릭터 이름
    async setAvatar(key) {
      if (local) {
        Object.assign(state.user, { avatarType: key === "initial" ? "initial" : "preset", avatarPreset: key === "initial" ? null : key, avatarUrl: null });
      } else {
        const u = await api("/me", { method: "PATCH", body: { avatar: key } });
        Object.assign(state.user, { avatarType: u.avatar_type, avatarPreset: u.avatar_preset, avatarUrl: u.avatar_url });
      }
      commit();
    },
    // 내 사진: 서버 모드는 서버가 256px 로 다시 만들고(메타데이터 제거), 로컬 모드는 브라우저에서 줄여 저장한다
    async setAvatarPhoto(file) {
      if (local) {
        const bmp = await createImageBitmap(file);
        const size = Math.min(bmp.width, bmp.height);
        const canvas = Object.assign(document.createElement("canvas"), { width: 256, height: 256 });
        canvas.getContext("2d").drawImage(bmp, (bmp.width - size) / 2, (bmp.height - size) / 2, size, size, 0, 0, 256, 256);
        Object.assign(state.user, { avatarType: "photo", avatarPreset: null, avatarUrl: canvas.toDataURL("image/webp", 0.85) });
      } else {
        const form = new FormData();
        form.append("file", file);
        const u = await api("/me/avatar", { method: "POST", form });
        Object.assign(state.user, { avatarType: u.avatar_type, avatarPreset: null, avatarUrl: u.avatar_url });
      }
      commit();
    },
    reset() {
      if (!local) throw new Error("서버 계정은 초기화할 수 없어요");
      state = seed();
      commit();
    },

    // ---------- 기출 업로드 · 기출 기반 생성 (서버 모드 전용) ----------
    listMaterials: (projectId) => api(`/projects/${projectId}/materials`),
    pastProblems: (projectId) => api(`/projects/${projectId}/past-problems`),
    uploadMaterial(projectId, file, rightsConfirmed) {
      const form = new FormData();
      form.append("file", file);
      form.append("rights_confirmed", rightsConfirmed ? "true" : "false");
      return api(`/projects/${projectId}/materials`, { method: "POST", form });
    },
    deleteMaterial: (id) => api(`/materials/${id}`, { method: "DELETE" }),
    async generateFromPast(projectId, { level, count }) {
      const s = toSession(await api(`/projects/${projectId}/generate`, { method: "POST", body: { level, count } }));
      state.sessions.push(s);
      commit();
      return s.id;
    },
  };

  return {
    mode: MODE,
    ready: boot(),
    get state() { return state; },
    get bank() { return Object.values(bank); },
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    onError(fn) { onError = fn; },
    ...q,
    ...ops,
  };
})();

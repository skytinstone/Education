// 프로토타입 데이터 저장소 — 브라우저 localStorage 에 저장한다.
// 구조는 src/education/schemas.py (Project, Session, Problem, Attempt) 와 맞춰 두어,
// 백엔드가 생기면 이 파일만 API 호출로 바꾸면 되게 한다.

// ---------- 샘플 문제 은행 (AI 연결 전까지 사용) ----------
const PROBLEM_BANK = [
  {
    id: "pb_log", domain: "math", conceptIds: ["math.math1.exp_log.log_properties"], difficulty: 1,
    stem: "log₂8 + log₃9 의 값은?", choices: ["3", "4", "5", "6", "7"], answer: "3",
    solution: "log₂8 = log₂2³ = 3, log₃9 = log₃3² = 2 이므로 3 + 2 = 5",
  },
  {
    id: "pb_subst", domain: "math", conceptIds: ["math.calculus.int_methods.substitution_parts"], difficulty: 2,
    stem: "∫₀¹ 2x·e^(x²) dx 의 값은?", choices: ["e − 1", "e", "e + 1", "2e − 1", "(e − 1)/2"], answer: "1",
    solution: "t = x² 로 치환하면 dt = 2x dx, x: 0→1 일 때 t: 0→1. ∫₀¹ eᵗ dt = e − 1",
  },
  {
    id: "pb_defint", domain: "math", conceptIds: ["math.math2.integration.definite_integral"], difficulty: 3,
    stem: "f(x) = ∫₁ˣ (3t² − 2t) dt 일 때, f′(2) 의 값은?", choices: ["4", "6", "8", "10", "12"], answer: "3",
    solution: "정적분으로 정의된 함수를 미분하면 f′(x) = 3x² − 2x. f′(2) = 12 − 4 = 8",
  },
  {
    id: "pb_seq", domain: "math", conceptIds: ["math.math1.sequence.arithmetic_geometric"], difficulty: 1,
    stem: "첫째항이 3, 공차가 4인 등차수열의 제10항은?", choices: ["35", "37", "39", "41", "43"], answer: "3",
    solution: "aₙ = a₁ + (n − 1)d 이므로 a₁₀ = 3 + 9 × 4 = 39",
  },
  {
    id: "pb_cond", domain: "math", conceptIds: ["math.prob_stat.probability.conditional_probability"], difficulty: 2,
    stem: "P(A) = 0.5, P(A ∩ B) = 0.2 일 때, P(B | A) 의 값은?", choices: ["0.2", "0.3", "0.4", "0.5", "0.6"], answer: "3",
    solution: "P(B | A) = P(A ∩ B) / P(A) = 0.2 / 0.5 = 0.4",
  },
  {
    id: "pb_kin", domain: "physics", conceptIds: ["physics.physics1.mechanics_energy.kinematics"], difficulty: 1,
    stem: "정지 상태에서 출발한 물체가 2 m/s² 의 등가속도로 5초 동안 이동한 거리는?", choices: ["10 m", "20 m", "25 m", "50 m", "100 m"], answer: "3",
    solution: "s = ½at² = ½ × 2 × 5² = 25 m",
  },
  {
    id: "pb_mom", domain: "physics", conceptIds: ["physics.physics1.mechanics_energy.momentum_impulse"], difficulty: 2,
    stem: "3 m/s 로 움직이는 2 kg 물체가 정지한 1 kg 물체와 충돌한 뒤 한 덩어리가 되었다. 충돌 직후 속력은?", choices: ["1 m/s", "1.5 m/s", "2 m/s", "3 m/s", "6 m/s"], answer: "3",
    solution: "운동량 보존: 2 × 3 = (2 + 1) × v 이므로 v = 2 m/s",
  },
  {
    id: "pb_mole", domain: "chemistry", conceptIds: ["chemistry.chemistry1.first_steps.mole"], difficulty: 1,
    stem: "물(H₂O) 36 g 의 양은 몇 mol 인가? (H = 1, O = 16)", choices: ["0.5 mol", "1 mol", "2 mol", "3 mol", "4 mol"], answer: "3",
    solution: "H₂O 의 몰 질량은 18 g/mol 이므로 36 ÷ 18 = 2 mol",
  },
  {
    id: "pb_neut", domain: "chemistry", conceptIds: ["chemistry.chemistry1.dynamic_reactions.neutralization"], difficulty: 2,
    stem: "0.1 M HCl 20 mL 를 완전히 중화하는 데 필요한 0.2 M NaOH 의 부피는?", choices: ["5 mL", "10 mL", "20 mL", "40 mL", "50 mL"], answer: "2",
    solution: "H⁺ 의 양 = 0.1 × 0.020 = 0.002 mol. OH⁻ 도 0.002 mol 필요하므로 0.002 ÷ 0.2 = 0.010 L = 10 mL",
  },
  {
    id: "pb_chrom", domain: "biology", conceptIds: ["biology.biology1.genetics.chromosome_cell_division"], difficulty: 1,
    stem: "사람의 체세포 염색체 수가 46개일 때, 정자 하나에 들어 있는 염색체 수는?", choices: ["22개", "23개", "44개", "46개", "92개"], answer: "2",
    solution: "감수 분열로 염색체 수가 절반이 되므로 46 ÷ 2 = 23개",
  },
  {
    id: "pb_half", domain: "earth_science", conceptIds: ["earth_science.earth1.solid_earth.relative_absolute_age"], difficulty: 2,
    stem: "반감기가 1억 년인 방사성 원소가 3억 년이 지나면 처음 양의 몇 배가 남는가?", choices: ["1/2", "1/3", "1/4", "1/6", "1/8"], answer: "5",
    solution: "반감기가 3번 지났으므로 (1/2)³ = 1/8",
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
  const bank = Object.fromEntries(PROBLEM_BANK.map((p) => [p.id, p]));

  // ---------- 처음 열었을 때 보여줄 샘플 데이터 ----------
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

  function load() {
    try { return JSON.parse(localStorage.getItem(KEY)); } catch { return null; }
  }
  let state = load() ?? seed();

  function commit() {
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch { /* 저장 불가(사생활 보호 모드 등) — 메모리에서만 유지 */ }
    listeners.forEach((fn) => fn(state));
  }

  const startOfDay = (t) => new Date(new Date(t).toDateString()).getTime();

  // ---------- 조회 ----------
  const q = {
    problem: (id) => bank[id],
    project: (id) => state.projects.find((p) => p.id === id),
    session: (id) => state.sessions.find((s) => s.id === id),
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

  // ---------- 변경 ----------
  const ops = {
    createProject({ name, subjectId, unitIds = [], goal = "", examDate = null }) {
      const p = { id: uid("p"), name, subjectId, unitIds, goal, examDate, pinned: false, createdAt: Date.now() };
      state.projects.push(p);
      commit();
      return p.id;
    },
    updateProject(id, patch) {
      Object.assign(q.project(id), patch);
      commit();
    },
    deleteProject(id) {
      state.projects = state.projects.filter((p) => p.id !== id);
      state.sessions = state.sessions.filter((s) => s.projectId !== id);
      state.attempts.forEach((a) => { if (a.projectId === id) a.projectId = null; });
      state.wrongNotes.forEach((n) => { if (n.projectId === id) n.projectId = null; });
      commit();
    },

    createSession({ projectId = null, text }) {
      const s = {
        id: uid("s"), projectId, title: text.length > 24 ? `${text.slice(0, 24)}…` : text,
        createdAt: Date.now(), updatedAt: Date.now(), messages: [],
      };
      state.sessions.push(s);
      ops.addMessage(s.id, { role: "user", text });
      return s.id;
    },
    addMessage(sessionId, msg) {
      const s = q.session(sessionId);
      s.messages.push({ ...msg, at: Date.now() });
      s.updatedAt = Date.now();
      commit();
    },
    updateSession(id, patch) {
      Object.assign(q.session(id), patch);
      commit();
    },
    deleteSession(id) {
      state.sessions = state.sessions.filter((s) => s.id !== id);
      commit();
    },

    // 문제 풀이 기록. 틀리면 오답노트에 넣고, 오답노트 문제를 다시 맞히면 극복 처리
    answer({ problemId, answer, projectId = null, sessionId = null }) {
      const correct = bank[problemId].answer === answer;
      state.attempts.push({ id: uid("a"), problemId, projectId, sessionId, answer, correct, at: Date.now() });
      const open = state.wrongNotes.find((n) => n.problemId === problemId && !n.resolvedAt);
      if (!correct && !open) {
        state.wrongNotes.push({ id: uid("w"), problemId, projectId, answer, errorType: "unknown", createdAt: Date.now(), resolvedAt: null });
      } else if (correct && open) {
        open.resolvedAt = Date.now();
      }
      commit();
      return { correct, note: !correct ? state.wrongNotes.find((n) => n.problemId === problemId && !n.resolvedAt) : null };
    },
    setErrorType(noteId, errorType) {
      state.wrongNotes.find((n) => n.id === noteId).errorType = errorType;
      commit();
    },
    deleteNote(noteId) {
      state.wrongNotes = state.wrongNotes.filter((n) => n.id !== noteId);
      commit();
    },

    toggleSaved(problemId) {
      const list = state.savedProblemIds;
      state.savedProblemIds = list.includes(problemId) ? list.filter((id) => id !== problemId) : [...list, problemId];
      commit();
    },
    markCard(id, known) {
      state.cards.find((c) => c.id === id).known = known;
      commit();
    },
    resetCards() {
      state.cards.forEach((c) => (c.known = null));
      commit();
    },
    updateUser(patch) {
      Object.assign(state.user, patch);
      commit();
    },
    reset() {
      state = seed();
      commit();
    },
  };

  return {
    get state() { return state; },
    bank: PROBLEM_BANK,
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    ...q,
    ...ops,
  };
})();

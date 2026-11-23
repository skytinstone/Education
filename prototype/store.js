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
  const inflight = {};        // 대화 id → { ref, stub } — '답변 멈추기' 에 쓴다 (ref: 서버에 보낸 요청 표시)
  const STOPPED_TEXT = "답변을 중단했어요."; // 서버(sessions.STOPPED_TEXT)와 같게
  const renamed = {};         // 임시 대화 id → 서버가 준 id
  let onError = () => {};

  function commit() {
    if (MODE === "local") {
      try { localStorage.setItem(KEY, JSON.stringify(state)); } catch { /* 저장 불가 — 메모리에서만 유지 */ }
    }
    listeners.forEach((fn) => fn(state));
  }
  const startOfDay = (t) => new Date(new Date(t).toDateString()).getTime();

  // 같은 계정으로 다른 PC에서 로그인 → 팝업을 띄우고 잠시 뒤 로그인 화면으로 (여러 요청이 동시에 와도 한 번만)
  let replacedShown = false;
  function sessionReplaced(kind = "1") {
    if (replacedShown) return;
    const forced = kind === "admin";
    replacedShown = true;
    const SEC = 5;
    const go = () => { location.href = forced ? "login.html#forced" : "login.html#replaced"; };
    const bd = document.createElement("div");
    bd.className = "backdrop session-out";
    bd.style.zIndex = "200";
    bd.innerHTML = `
      <div class="modal" role="alertdialog" aria-modal="true" aria-labelledby="so-title" style="max-width:380px;text-align:center">
        <div style="width:48px;height:48px;margin:4px auto 14px;border-radius:50%;display:grid;place-items:center;background:rgba(249,115,22,.12);color:#ea580c;font-size:22px">!</div>
        <h2 id="so-title" style="font-size:17px;font-weight:700;margin-bottom:8px">${forced ? "운영자가 로그아웃시켰어요." : "다른 PC에서 접속 중입니다."}</h2>
        <p style="font-size:14px;color:var(--ink-2);line-height:1.6">자동으로 로그아웃 됩니다.<br /><small style="color:var(--ink-3)"><b id="so-sec">${SEC}</b>초 뒤 로그인 화면으로 이동해요</small></p>
        <div class="modal-foot" style="justify-content:center"><button type="button" class="btn-primary" id="so-ok">확인</button></div>
      </div>`;
    document.body.append(bd);
    let left = SEC;
    const t = setInterval(() => { left -= 1; const el = document.getElementById("so-sec"); if (el) el.textContent = left; if (left <= 0) { clearInterval(t); go(); } }, 1000);
    document.getElementById("so-ok").onclick = () => { clearInterval(t); go(); };
    document.getElementById("so-ok").focus();
  }

  // ================= 서버 통신 =================
  async function api(path, { method = "GET", body, form } = {}) {
    const headers = { Authorization: `Bearer ${TOKEN}` };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const res = await fetch(`/api${path}`, { method, headers, body: form ?? (body !== undefined ? JSON.stringify(body) : undefined) });
    if (res.status === 401) {
      try { localStorage.removeItem("eureka.token"); } catch { /* 무시 */ }
      if (res.headers.get("X-Session-Replaced")) { sessionReplaced(res.headers.get("X-Session-Replaced")); throw new Error("로그아웃됐어요"); }
      const why = await res.clone().json().catch(() => ({}));
      location.href = String(why.detail ?? "").includes("정지") ? "login.html#suspended" : "login.html";
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
    answer: p.answer ?? null, solution: p.solution ?? null, unit: p.unit ?? null,
  });
  function mergeProblem(raw) {
    const p = toProblem(raw);
    const old = bank[p.id];
    bank[p.id] = { ...old, ...p, answer: p.answer ?? old?.answer ?? null, solution: p.solution ?? old?.solution ?? null };
  }
  const toProject = (p) => ({
    id: p.id, name: p.name, subjectId: p.subject_id, unitIds: p.unit_ids, goal: p.goal, textbook: p.textbook ?? "", textbookIsbn: p.textbook_isbn ?? p.textbookIsbn ?? null, examDate: p.exam_date,
    questionType: p.question_type, pinned: p.pinned, createdAt: Date.parse(p.created_at),
  });
  function toSession(s) {
    s.messages.forEach((msg) => msg.problems.forEach(mergeProblem));
    return {
      id: s.id, projectId: s.project_id, title: s.title, createdAt: Date.parse(s.created_at), updatedAt: Date.parse(s.updated_at),
      messages: s.messages.map(toMessage),
    };
  }
  const toFile = (f) => ({ id: f.id, name: f.filename, mime: f.content_type, size: f.size_bytes });
  const toMessage = (msg) => ({ id: msg.id, role: msg.role, text: msg.text, quote: msg.quote ?? null, problemIds: msg.problems.map((p) => p.id), explanation: msg.explanation ?? null,
    intent: msg.intent ?? null, suggestions: msg.suggestions ?? [], action: msg.action ?? null, files: (msg.attachments ?? []).map(toFile), at: Date.parse(msg.created_at) });
  const FILE_ONLY_TEXT = "첨부한 자료를 보고 풀이해 줘"; // 서버(dto.FILE_ONLY_TEXT)와 같게
  const QUOTE_ONLY_TEXT = "이 부분을 더 자세히 설명해 줘"; // 서버(dto.QUOTE_ONLY_TEXT)와 같게
  let drivePromise = null;
  const fileUrls = new Map(); // 첨부 id → blob URL (인증 헤더가 필요해 <img src> 로 바로 못 불러온다)
  const PROJECT_KEYS = { name: "name", subjectId: "subject_id", unitIds: "unit_ids", goal: "goal", textbook: "textbook", textbookIsbn: "textbook_isbn", examDate: "exam_date", questionType: "question_type", pinned: "pinned" };
  const snake = (patch) => Object.fromEntries(Object.entries(patch).filter(([k]) => PROJECT_KEYS[k]).map(([k, v]) => [PROJECT_KEYS[k], v]));

  function mergeCourse({ course, concepts }) {
    state.courses = [...state.courses.filter((c) => c.id !== course.id), course];
    const have = new Set(state.concepts.map((c) => c.id));
    state.concepts.push(...concepts.filter((c) => !have.has(c.id)));
    commit();
  }

  async function boot() {
    if (MODE === "local") {
      try { state = JSON.parse(localStorage.getItem(KEY)); } catch { state = null; }
      state ??= seed();
      state.courses = window.COURSES ?? [];
      state.concepts = window.CONCEPTS ?? [];
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
  // 질문을 보내고 답을 기다리는 공통 부분 — 바로 대화 id 를 돌려주고, 답은 나중에 도착한다(Store.isPending).
  // request(ref): 서버 요청 (새 대화·고치기면 대화 전체, 이어 묻기면 [질문, 답]). 로컬 모드면 null
  const uuid4 = () => crypto.randomUUID?.() ?? "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) =>
    (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16));
  function track(s, um, request) {
    const id = s.id;
    s.updatedAt = Date.now();
    pending.add(id);
    const f = (inflight[id] = { ref: local ? null : uuid4(), stub: null });
    commit();
    // 화면에 먼저 넣은 질문(과 멈췄으면 '중단했어요')을 서버가 돌려준 것으로 바꾼다
    const replace = (msgs) => {
      const i = s.messages.indexOf(um);
      if (i >= 0) s.messages.splice(i, f.stub && s.messages[i + 1] === f.stub ? 2 : 1, ...msgs);
    };
    const done = local
      ? new Promise((resolve) => setTimeout(() => {
          if (f.stub) return resolve(id);
          const domain = CONCEPTS.find((c) => c.id === q.project(s.projectId)?.subjectId)?.domain;
          s.messages.push({ ...localReply(um.text, domain), at: Date.now() });
          s.updatedAt = Date.now();
          resolve(id);
        }, 800))
      : request(f.ref).then((res) => {
          if (Array.isArray(res)) { // 이어 묻기: [질문, 답]
            res.forEach((msg) => msg.problems.forEach(mergeProblem));
            replace(res.map(toMessage));
            s.updatedAt = Date.now();
            return id;
          }
          const real = toSession(res); // 새 대화·고치기: 대화 전체
          if (real.id === id) { s.messages = real.messages; s.updatedAt = real.updatedAt; return id; }
          state.sessions = state.sessions.map((x) => (x.id === id ? real : x));
          renamed[id] = real.id;
          return real.id;
        });
    done.catch((e) => {
      if (!f.stub) s.messages.push({ role: "ai", text: `답변을 만들지 못했어요: ${e.message}`, problemIds: [], at: Date.now() });
    }).finally(() => { if (inflight[id] === f) delete inflight[id]; pending.delete(id); commit(); });
    return { id, done };
  }
  const ops = {
    async createProject({ name, subjectId, unitIds = [], goal = "", textbook = "", textbookIsbn = null, examDate = null, questionType = "auto" }) {
      if (local) {
        const p = { id: uid("p"), name, subjectId, unitIds, goal, textbook, textbookIsbn, examDate, questionType, pinned: false, createdAt: Date.now() };
        state.projects.push(p);
        commit();
        return p.id;
      }
      const p = toProject(await api("/projects", { method: "POST", body: snake({ name, subjectId, unitIds, goal, textbook, textbookIsbn, examDate, questionType }) }));
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
    // files: uploadChatFile 로 먼저 올린 첨부 [{ id, name, mime, size }] — 글 없이 첨부만 보내도 된다
    sendMessage({ sessionId = null, projectId = null, text, files = [], quote = null }) {
      const now = Date.now();
      if (!text && quote) text = QUOTE_ONLY_TEXT;
      else if (!text && files.length) text = FILE_ONLY_TEXT;
      let s = sessionId && q.session(sessionId);
      if (!s) {
        const title = text === FILE_ONLY_TEXT && files.length ? files[0].name : text;
        s = { id: uid(local ? "s" : "tmp"), projectId, title: title.length > 24 ? `${title.slice(0, 24)}…` : title,
          createdAt: now, updatedAt: now, messages: [] };
        state.sessions.push(s);
      }
      const um = { role: "user", text, quote, files, at: now };
      s.messages.push(um);
      const attachment_ids = files.map((f) => f.id);
      const isNew = !sessionId;
      return track(s, um, local ? null : (ref) => (isNew
        ? api("/sessions", { method: "POST", body: { text, attachment_ids, project_id: projectId, ref, quote } })
        : api(`/sessions/${s.id}/messages`, { method: "POST", body: { text, attachment_ids, ref, quote } })));
    },
    // 보낸 질문 고치기 — 그 질문부터 뒤를 지우고 고친 글로 다시 묻는다 (첨부는 그대로). index: 대화 안 메시지 위치
    editMessage({ sessionId, index, text }) {
      const s = q.session(sessionId), old = s?.messages[index];
      if (!old || old.role !== "user" || (!local && !old.id)) return null;
      const um = { role: "user", text, quote: old.quote ?? null, files: old.files ?? [], at: Date.now() };
      s.messages.splice(index, s.messages.length - index, um);
      return track(s, um, local ? null : (ref) =>
        api(`/sessions/${s.id}/messages/${old.id}/edit`, { method: "POST", body: { text, ref } }));
    },
    // 답변 멈추기 — 화면에서는 바로 멈추고, 서버에는 다음 단계 전에 멈추라고 알린다 (도착한 결과는 서버 기록을 따른다)
    stopMessage(id) {
      const f = inflight[id];
      if (!f || !pending.has(id)) return;
      const s = q.session(id);
      f.stub = { role: "ai", text: STOPPED_TEXT, intent: "stopped", problemIds: [], suggestions: [], at: Date.now() };
      s?.messages.push(f.stub);
      pending.delete(id);
      commit();
      if (f.ref) api("/sessions/stop", { method: "POST", body: { ref: f.ref } }).catch(() => {});
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
      let correct, noteId = null, resolved = false, score = null, feedback = null;
      if (local) {
        const p = bank[problemId];
        correct = p.problemType === "short_answer" ? Number(String(answer).replace(/,/g, "")) === Number(p.answer) : p.answer === answer;
        if (!correct && !open()) state.wrongNotes.push({ id: uid("w"), problemId, projectId, answer, errorType: "unknown", createdAt: Date.now(), resolvedAt: null });
        else if (correct && open()) { open().resolvedAt = Date.now(); resolved = true; }
        noteId = open()?.id ?? null;
      } else {
        const r = await api("/attempts", { method: "POST", body: { problem_id: problemId, answer, project_id: projectId, session_id: sessionId } });
        correct = r.correct;
        score = r.score ?? null;
        feedback = r.feedback ?? null;
        Object.assign(bank[problemId], { answer: r.answer, solution: r.solution });
        if (r.resolved && open()) { open().resolvedAt = Date.now(); resolved = true; }
        if (!correct && r.wrong_note_id && !open()) {
          state.wrongNotes.push({ id: r.wrong_note_id, problemId, projectId, answer, errorType: "unknown", createdAt: Date.now(), resolvedAt: null });
        }
        noteId = r.wrong_note_id;
      }
      state.attempts.push({ id: uid("a"), problemId, projectId, sessionId, answer, correct, score, feedback, at: Date.now() });
      commit();
      return { correct, resolved, noteId, score, feedback };
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
    // 코스: 다른 사람이 만든 코스의 개념 트리 받아 오기 / 출제 범위로 새 코스 만들기 (AI, 30초~1분)
    async loadCourse(id) {
      if (local || state.concepts.some((c) => c.id === id)) return;
      mergeCourse(await api(`/courses/${encodeURIComponent(id)}`));
    },
    async createCourse(body) {
      const d = await api("/courses", { method: "POST", body });
      mergeCourse(d);
      return d.course;
    },
    // 알림 — { unread, items } / 읽음 처리 (ids 를 비우면 모두)
    notifications() { return local ? Promise.resolve({ unread: 0, items: [] }) : api("/notifications"); },
    readNotifications(ids = null) { return local ? Promise.resolve() : api("/notifications/read", { method: "POST", body: { ids } }); },
    // 피드백·문제 신고 { kind, message, problem_id, page }
    sendFeedback(body) {
      return api("/feedback", { method: "POST", body });
    },
    // 서술형 풀이 확인 — { text } 또는 { image: PNG data URL }. 서버 모드에서만
    reviewSolution(problemId, body) {
      if (local) return Promise.reject(new Error("서술형 풀이 확인은 로그인한 서버 화면에서 쓸 수 있어요"));
      return api(`/problems/${problemId}/review`, { method: "POST", body });
    },
    // 책 검색 (제목·ISBN, 선택 기능 — 서지 정보만) — 로컬 모드에선 빈 목록
    searchBooks(q) {
      return local ? Promise.resolve([]) : api(`/books/search?q=${encodeURIComponent(q)}`);
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
    // ---------- 대화 첨부 (입력창 +) — 서버 모드에서만 ----------
    async uploadChatFile(file) {
      if (local) throw new Error("체험 모드에서는 파일을 첨부할 수 없어요. 로그인하면 쓸 수 있어요");
      const form = new FormData();
      form.append("file", file, file.name);
      return toFile(await api("/sessions/files", { method: "POST", form }));
    },
    removeChatFile(id) {
      if (!local) api(`/sessions/files/${id}`, { method: "DELETE" }).catch(() => {}); // 못 지워도 서버가 하루 뒤 거둔다
    },
    // 첨부 미리보기 주소 (blob URL, 한 번 받으면 재사용)
    chatFileUrl(id) {
      if (!fileUrls.has(id)) {
        fileUrls.set(id, fetch(`/api/sessions/files/${id}`, { headers: { Authorization: `Bearer ${TOKEN}` } })
          .then((r) => { if (!r.ok) throw new Error("파일을 불러오지 못했어요"); return r.blob(); })
          .then((b) => URL.createObjectURL(b))
          .catch((e) => { fileUrls.delete(id); throw e; }));
      }
      return fileUrls.get(id);
    },
    rememberChatFileUrl(id, url) { fileUrls.set(id, Promise.resolve(url)); },
    // Google Drive 에서 고르기 설정 (없으면 null)
    driveConfig() {
      if (local) return Promise.resolve(null);
      drivePromise ??= api("/sessions/drive-config").catch(() => null);
      return drivePromise;
    },
    reset() {
      if (!local) throw new Error("서버 계정은 초기화할 수 없어요");
      state = seed();
      commit();
    },

    // ---------- 로그인 방법 (서버 모드 전용) ----------
    connections: () => api("/me/connections"),
    // 서버가 연결 쿠키를 심고 제공자 로그인 주소를 돌려준다 → 그 주소로 이동, 끝나면 #/settings?linked=… 로 돌아온다
    startConnection: (provider) => api(`/me/connections/${provider}/start`, { method: "POST" }),
    removeConnection: (provider) => api(`/me/connections/${provider}`, { method: "DELETE" }),
    setPassword: (currentPassword, newPassword) =>
      api("/me/password", { method: "PUT", body: { current_password: currentPassword || null, new_password: newPassword } }),

    // ---------- 기출 업로드 · 기출 기반 생성 (서버 모드 전용) ----------
    listMaterials: (projectId) => api(`/projects/${projectId}/materials`),
    workspace: (projectId) => api(`/projects/${projectId}/workspace`),
    // 접속 상태 알림 (운영 콘솔 '지금 접속 중') — 실패해도 조용히 넘어간다
    // 시험 기록
    saveExam: (projectId, body) => api(`/projects/${projectId}/exams`, { method: "POST", body }),
    listExams: (projectId) => api(`/projects/${projectId}/exams`),
    exam: (id) => api(`/exams/${id}`),
    deleteExam: (id) => api(`/exams/${id}`, { method: "DELETE" }),
    ping: (page) => (MODE === "api" ? api("/me/ping", { method: "POST", body: { page } }).catch(() => {}) : Promise.resolve()),
    // 정답 연결 편집 — { manual_answer } · { reset_manual: true } · { number }
    editProblem: (materialId, problemId, body) => api(`/materials/${materialId}/problems/${encodeURIComponent(problemId)}`, { method: "PATCH", body }),
    // 올린 원본 파일 (그림 문항 원본 보기)
    async materialBlob(materialId) {
      const res = await fetch(`/api/materials/${materialId}/file`, { headers: { Authorization: `Bearer ${TOKEN}` } });
      if (!res.ok) throw new Error("원본 파일을 열지 못했어요");
      return res.blob();
    },
    // 다른 화면(작업 공간·시험)에서 받은 문항을 채점할 수 있게 문제 목록에 넣는다
    ensureProblems(list) {
      list.forEach((p) => { if (!bank[p.id]) mergeProblem({ ...p, answer: null, solution: null }); });
    },
    pastProblems: (projectId) => api(`/projects/${projectId}/past-problems`),
    // kind: past_exam(기출·시험지) | textbook(교재 페이지)
    uploadMaterial(projectId, file, rightsConfirmed, kind = "past_exam", answerFor = null) {
      const form = new FormData();
      form.append("file", file);
      form.append("rights_confirmed", rightsConfirmed ? "true" : "false");
      form.append("kind", kind);
      if (answerFor) form.append("answer_for", answerFor);
      return api(`/projects/${projectId}/materials`, { method: "POST", form });
    },
    deleteMaterial: (id) => api(`/materials/${id}`, { method: "DELETE" }),
    // 정답지 — 만들기 시작(백그라운드) / 정답·해설 보기
    startAnswerKey: (id) => api(`/materials/${id}/answer-key`, { method: "POST" }),
    answerKey: (id) => api(`/materials/${id}/answer-key`),
    // 정답지에서 고른 부분(인용)에 대해 묻기 → { line, explanation }
    askAnswerKey: (id, body) => (local ? Promise.reject(new Error("서버에 연결했을 때 쓸 수 있어요"))
      : api(`/materials/${id}/ask`, { method: "POST", body })),
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
    reload: () => boot(), // 서버 데이터를 다시 받는다 (예: 오른쪽 패널에서 시험을 마친 뒤)
    ...q,
    ...ops,
  };
})();

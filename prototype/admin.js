// Eureka 관리자 페이지 (/admin) — 운영자(ADMIN_EMAILS) 전용.
// 학습 화면과 같은 로그인 토큰을 쓰고, 운영자가 아니면 들어올 수 없다. API 는 /api/admin/*.
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s = "") => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const MATH_OPTS = { delimiters: [{ left: "$$", right: "$$", display: true }, { left: "$", right: "$", display: false }], throwOnError: false };
  const icons = () => {
    lucide.createIcons();
    if (window.renderMathInElement) $$("[data-math]").forEach((el) => renderMathInElement(el, MATH_OPTS));
  };
  const DAY = 864e5;
  const startOfToday = () => new Date(new Date().toDateString()).getTime();
  function relTime(t) {
    const m = (Date.now() - t) / 6e4;
    if (m < 1) return "방금";
    if (m < 60) return `${Math.floor(m)}분 전`;
    if (m < 60 * 24) return `${Math.floor(m / 60)}시간 전`;
    const d = Math.floor((startOfToday() - new Date(new Date(t).toDateString())) / DAY);
    if (d <= 1) return "어제";
    if (d < 30) return `${d}일 전`;
    return new Date(t).toLocaleDateString("ko-KR");
  }
  const pct = (x) => (x == null ? "–" : `${Math.round(x * 100)}%`);
  const FEEDBACK_KINDS = { problem: "문제·정답 오류", solution: "해설 오류", review: "서술형 채점 이상", feature: "기능 제안", bug: "버그", other: "기타" };

  function toast(msg) {
    $(".toast")?.remove();
    const t = document.createElement("div");
    t.className = "toast";
    t.textContent = msg;
    document.body.append(t);
    setTimeout(() => t.remove(), 2400);
  }

  // ---------- 서버 통신 ----------
  const TOKEN_KEY = "eureka.token";
  const getToken = () => { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } };
  class ApiError extends Error { constructor(status, msg) { super(msg); this.status = status; } }
  async function api(path, { method = "GET", body } = {}) {
    const headers = { Authorization: `Bearer ${getToken()}` };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const res = await fetch(`/api${path}`, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
    if (res.status === 204) return null;
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const d = data.detail;
      if (res.status === 401 && res.headers.get("X-Session-Replaced")) sessionReplaced();
      else if (res.status === 401) showGate("login", typeof d === "string" && d.includes("정지") ? d : "로그인이 필요해요");
      // 운영자가 아니면 서버가 운영자 경로를 '없는 것처럼' 404 + "찾을 수 없어요" 로 답한다 (없는 회원 404 와 구분)
      else if (res.status === 404 && path.startsWith("/admin/") && d === "찾을 수 없어요") showGate("denied");
      throw new ApiError(res.status, typeof d === "string" ? d : Array.isArray(d) ? (d[0]?.msg ?? "입력을 확인해 주세요") : "잠시 후 다시 시도해 주세요");
    }
    return data;
  }
  const qs = (params) => (params ? `?${new URLSearchParams(params)}` : "");
  const Store = {
    adminGet: (path, params) => api(`/admin${path}${qs(params)}`),
    adminPost: (path, body) => api(`/admin${path}`, { method: "POST", body }),
    adminDelete: (path, body) => api(`/admin${path}`, { method: "DELETE", body }),
    // 파일 내려받기 (CSV) — 로그인 토큰을 붙여 받아서 브라우저 저장으로 넘긴다
    async adminDownload(path, params) {
      const res = await fetch(`/api/admin${path}${qs(params)}`, { headers: { Authorization: `Bearer ${getToken()}` } });
      if (!res.ok) throw new ApiError(res.status, "파일을 만들지 못했어요");
      const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? "export.csv";
      const url = URL.createObjectURL(await res.blob());
      const a = Object.assign(document.createElement("a"), { href: url, download: name });
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      return name;
    },
    adminFeedback: (params) => api(`/admin/feedback${qs(params)}`),
    adminUpdateFeedback: (id, patch) => api(`/admin/feedback/${id}`, { method: "PATCH", body: patch }),
    adminRestoreProblem: (pid) => api(`/admin/problems/${encodeURIComponent(pid)}/restore`, { method: "POST" }),
    adminAnnounce: (body) => api("/admin/announcements", { method: "POST", body }),
  };

  // ---------- 모달 ----------
  function closeOverlays() { $$(".backdrop").forEach((b) => b.remove()); }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeOverlays(); });
  function invalid(input, msg) {
    input.classList.add("invalid");
    let err = input.parentElement.querySelector(".err");
    if (!err) { err = document.createElement("p"); err.className = "err"; input.after(err); }
    err.textContent = msg;
    input.focus();
    return false;
  }
  function formModal({ title, body, submit = "확인", danger = false, onSubmit }) {
    closeOverlays();
    const bd = document.createElement("div");
    bd.className = "backdrop";
    bd.innerHTML = `
      <form class="modal" novalidate role="dialog" aria-label="${esc(title)}">
        <div class="modal-head"><h2>${esc(title)}</h2><button type="button" class="icon-btn" data-close aria-label="닫기"><i data-lucide="x"></i></button></div>
        <div class="modal-body">${body}</div>
        <div class="modal-foot"><button type="button" class="btn-ghost" data-close>취소</button><button type="submit" class="btn-primary ${danger ? "danger" : ""}">${esc(submit)}</button></div>
      </form>`;
    document.body.append(bd);
    const form = $("form", bd);
    bd.addEventListener("mousedown", (e) => { if (e.target === bd) closeOverlays(); });
    $$("[data-close]", bd).forEach((x) => (x.onclick = closeOverlays));
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      if (onSubmit(form) !== false) closeOverlays();
    });
    icons();
    setTimeout(() => form.querySelector(".modal-body input, .modal-body textarea")?.focus(), 30);
  }

  const view = $("#view");

  // ================= 운영 콘솔 (운영자 계정만) =================
  // #/(개요) · #/users[/id] · #/ai · #/logins · #/voc
  const FB_STATUS = { open: "접수", reviewing: "확인 중", resolved: "해결" };
  const ADMIN_TABS = [["overview", "개요", "layout-dashboard"], ["users", "회원", "users"], ["revenue", "매출", "wallet"], ["ai", "AI 사용량", "cpu"], ["quality", "문제 품질", "gauge"], ["items", "문제 성적표", "clipboard-check"], ["runs", "AI 실행 기록", "activity"], ["evals", "하네스 평가", "target"], ["logins", "로그인 기록", "log-in"], ["voc", "VOC", "inbox"], ["actions", "관리 기록", "scroll-text"]];
  const METHOD_NAME = { password: "이메일", google: "Google", kakao: "카카오" };
  const PURPOSE_NAME = { generate: "문제 생성", verify: "문제 검증", note_generate: "개념 정리 생성", note_verify: "개념 정리 검증",
    course: "코스 만들기", extract: "기출·교재 분석", essay_grade: "서술형 채점", review: "풀이 확인", explain: "계산·설명 풀이", answer_key: "정답지 풀이", answer_verify: "정답지 검산",
    methods: "다른 풀이", plan: "학습 계획 검토", deep_dive: "Deep Dive", math_check: "계산 도구 검산 (에이전트)", embed: "임베딩 (RAG)",
    agent: "대화 에이전트 (도구)", route: "대화 의도 판단" };
  // 접속 상태
  const PAGE_NAME = { home: "홈", chat: "대화", project: "프로젝트", notes: "오답노트", library: "라이브러리", settings: "설정",
    "answer-key": "정답지", exam: "시험", admin: "운영 콘솔" };
  const PRESENCE = { online: ["접속 중", "on"], recent: ["방금 전까지", "recent"], offline: ["", "off"] };
  function presenceBadge(u, long = false) {
    const [label, tone] = PRESENCE[u.presence] ?? PRESENCE.offline;
    const text = u.presence === "offline" ? (u.last_seen_at ? ago(u.last_seen_at) : "기록 없음") : long && u.presence === "recent" ? `${ago(u.last_seen_at)} 활동` : label;
    return `<span class="presence ${tone}"><i></i>${esc(text)}</span>`;
  }
  const FAIL_REASON = { bad_credentials: "비밀번호 틀림", suspended: "정지된 계정", throttled: "여러 번 실패해 잠시 막음" };
  const adminState = {
    days: 30, aiDays: 30, revDays: 30, revTest: false,
    users: { q: "", state: "all", sort: "recent", offset: 0 },
    actions: { q: "", action: "" },
    logins: { q: "", result: "all", method: "" },
    voc: { state: "open", kind: "", q: "", user_id: "" },
    items: { flag: "", grade: "" },
    runs: { kind: "", status: "" },
  };
  const num = (n) => Number(n ?? 0).toLocaleString("ko-KR");
  const compact = (n) => new Intl.NumberFormat("ko-KR", { notation: "compact", maximumFractionDigits: 1 }).format(Number(n ?? 0));
  const usd = (x) => { const v = Number(x ?? 0); return `$${v >= 100 ? v.toFixed(0) : v >= 1 ? v.toFixed(2) : v.toFixed(v ? 4 : 2)}`; };
  const when = (iso) => (iso ? new Date(iso).toLocaleString("ko-KR", { year: "2-digit", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "–");
  const ago = (iso) => (iso ? relTime(Date.parse(iso)) : "없음");
  // 사용자 에이전트 → '크롬 · Windows' 정도로 짧게
  function device(ua = "") {
    if (!ua) return "–";
    const b = /Edg\//.test(ua) ? "Edge" : /Whale/.test(ua) ? "웨일" : /SamsungBrowser/.test(ua) ? "삼성 인터넷" : /KAKAOTALK/i.test(ua) ? "카카오톡" : /Chrome\//.test(ua) ? "Chrome" : /Firefox\//.test(ua) ? "Firefox" : /Safari\//.test(ua) ? "Safari" : "기타";
    const o = /iPhone|iPad/.test(ua) ? "iOS" : /Android/.test(ua) ? "Android" : /Windows/.test(ua) ? "Windows" : /Mac OS X/.test(ua) ? "macOS" : /Linux/.test(ua) ? "Linux" : "";
    return o ? `${b} · ${o}` : b;
  }
  const kpi = (label, value, sub = "", tone = "") => `<div class="kpi ${tone}"><span class="k">${label}</span><b>${value}</b>${sub ? `<small>${sub}</small>` : ""}</div>`;
  // 일별 막대 차트 — 같은 색 하나, 마우스를 올리면 날짜와 값
  function dayBars(rows, key, fmt = num) {
    const max = Math.max(...rows.map((r) => r[key]), 0);
    const label = (d) => `${Number(d.slice(5, 7))}/${Number(d.slice(8))}`;
    return `
      <div class="bars-chart" role="img" aria-label="일별 추이, 최대 ${fmt(max)}">
        ${rows.map((r) => `<span class="col" title="${label(r.date)} · ${fmt(r[key])}"><i style="height:${max ? Math.max(2, (r[key] / max) * 100) : 0}%"></i></span>`).join("")}
      </div>
      <div class="bars-axis"><span>${label(rows[0].date)}</span><span>최대 ${fmt(max)}</span><span>${label(rows.at(-1).date)}</span></div>`;
  }
  const userLink = (id, text) => (id ? `<a href="#/users/${id}">${esc(text)}</a>` : esc(text));
  const methodChips = (list) => list.map((k) => `<span class="mchip m-${k}">${METHOD_NAME[k] ?? k}</span>`).join("");
  const table = (head, rows, empty) => rows.length
    ? `<div class="tbl-wrap"><table class="tbl"><thead><tr>${head.map((h) => (h.startsWith("#") ? `<th class="n">${h.slice(1)}</th>` : `<th>${h}</th>`)).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`
    : `<p class="mini">${empty}</p>`;

  const TAB_DESC = { overview: "가입·이용 현황과 오늘 챙길 것", users: "회원 검색, 상세, 이용 정지·삭제", revenue: "월 구독 결제 매출 · 구독자 · AI 원가와 마진 (부가세·수수료·환율은 추정)", ai: "AI 호출 비용·토큰·실패",
    quality: "AI 가 만든 문제의 검산 통과율과 탈락 이유, 정답지 상태",
    evals: "골든셋으로 지금 하네스의 품질을 숫자로 — 망가진 문제를 거르는가 · 좋은 문제를 지키는가 · 검색이 맞는가",
    runs: "하네스 — AI 실행 한 번이 어떤 지시문 버전으로 어떤 단계(모델 · 도구 · 검사)를 거쳤는지",
    items: "학생 처음 풀이로 매긴 문제별 성적 — 학생 실력을 감안한 실제 난이도 · 변별도 · 보기 분석",
    logins: "로그인·가입 기록 (90일 보관)", voc: "의견·문제 신고 확인과 답변, 전체 공지",
    actions: "운영자가 한 조치 — 정지·해제·삭제·강제 로그아웃·VOC·공지 (누가 · 언제 · 누구에게)" };
  const ACTION_NAME = { suspend: ["이용 정지", "bad"], unsuspend: ["정지 해제", "ok"], delete: ["계정 삭제", "bad"], logout: ["강제 로그아웃", "warn"],
    voc_status: ["VOC 상태 변경", ""], voc_reply: ["VOC 답변", ""], announce: ["전체 공지", ""], restore: ["문제 복구", ""] };
  const actionChip = (a) => { const [t, tone] = ACTION_NAME[a] ?? [a, ""]; return `<span class="achip ${tone}">${esc(t)}</span>`; };
  async function renderAdmin(tab = "overview", id = null) {
    if (tab !== "users" || id) clearInterval(liveTimer);
    if (!ADMIN_TABS.some(([k]) => k === tab)) tab = "overview";
    const [, title, icon] = ADMIN_TABS.find(([k]) => k === tab);
    $$(".side-nav a").forEach((el) => el.classList.toggle("on", el.dataset.tab === tab));
    view.innerHTML = `
      <div class="page-head"><div><h1>${title}</h1><p>${TAB_DESC[tab]}</p></div></div>
      <div class="admin-body" id="admin-body"><p class="mini">불러오는 중…</p></div>`;
    icons();
    const body = $("#admin-body");
    view.onclick = (e) => adminClick(e, tab, id);
    view.onchange = (e) => adminChange(e, tab);
    try {
      if (tab === "overview") await adminOverview(body);
      else if (tab === "users") await (id ? adminUser(body, id) : adminUsers(body));
      else if (tab === "revenue") await adminRevenue(body);
      else if (tab === "ai") await adminAI(body);
      else if (tab === "quality") await adminQuality(body);
      else if (tab === "items") await adminItems(body);
      else if (tab === "runs") await (id ? adminRun(body, id) : adminRuns(body));
      else if (tab === "evals") await (id ? adminEval(body, id) : adminEvals(body));
      else if (tab === "logins") await adminLogins(body);
      else if (tab === "actions") await adminActions(body);
      else await adminVOC(body);
    } catch (err) {
      if (body.isConnected) body.innerHTML = `<p class="mini">${esc(err.message)}</p>`;
    }
    icons();
  }

  // ---------- 매출 ----------
  const won = (n) => `${Number(n ?? 0).toLocaleString("ko-KR")}원`;
  const PAY_STATUS = { paid: ["결제됨", "ok"], failed: ["실패", "bad"] };
  async function adminRevenue(body) {
    const r = await Store.adminGet("/revenue", { days: adminState.revDays, include_test: adminState.revTest });
    if (!body.isConnected) return;
    const t = r.totals, sb = r.subscriptions;
    const diff = r.months.last ? Math.round(((r.months.this - r.months.last) / r.months.last) * 100) : null;
    body.innerHTML = `
      <div class="panel-row" style="margin-bottom:12px">
        <div class="seg small">${[7, 30, 90, 365].map((d) => `<button data-revdays="${d}" class="${adminState.revDays === d ? "on" : ""}">${d === 365 ? "1년" : `${d}일`}</button>`).join("")}</div>
        <label class="mini" style="display:inline-flex;gap:6px;align-items:center;cursor:pointer"><input type="checkbox" data-revtest ${adminState.revTest ? "checked" : ""}/> 테스트 결제 포함</label>
      </div>
      <div class="kpis">
        ${kpi("이번 달 매출", won(r.months.this), `지난달 ${won(r.months.last)}${diff != null ? ` · ${diff >= 0 ? "+" : ""}${diff}%` : ""}`)}
        ${kpi("MRR (월 반복 매출)", won(sb.mrr), `구독 중 ${num(sb.active)}명 · 해지 예약 ${num(sb.canceling)}명${sb.past_due ? ` · 결제 실패 ${num(sb.past_due)}명` : ""}`, sb.past_due ? "warn" : "")}
        ${kpi(`${r.days}일 매출`, won(t.gross), `결제 ${num(t.payments)}건 · 신규 구독 ${num(t.new_subscriptions)} · 실패 ${num(t.failed)}건`, t.failed ? "warn" : "")}
        ${kpi("남는 돈 (추정)", won(t.margin_krw), `부가세·수수료 뺀 ${won(t.net_estimate)} − AI ${won(t.ai_cost_krw)}${t.margin_rate != null ? ` · 마진 ${Math.round(t.margin_rate * 100)}%` : ""}`, t.margin_krw < 0 ? "warn" : "")}
      </div>
      <div class="admin-grid">
        <section class="panel"><h3>일별 매출</h3>${dayBars(r.by_day, "amount", won)}</section>
        <section class="panel"><h3>요금제별 구독자</h3>
          ${table(["요금제", "#가격", "#구독 중", "#해지 예약", "#MRR"], sb.by_plan.map((p) => `
            <tr><td><b>${esc(p.name)}</b></td><td class="n">${won(p.price)}</td><td class="n">${num(p.active)}</td><td class="n">${num(p.canceling)}</td><td class="n">${won(p.price * p.active)}</td></tr>`), "요금제가 없어요")}
          <p class="mini">구독자 1명당 AI 원가 (${r.days}일): <b>${sb.ai_cost_per_subscriber_krw == null ? "–" : won(sb.ai_cost_per_subscriber_krw)}</b>
            · AI 비용 ${usd(t.ai_cost_usd)} (1달러 ${num(r.usd_krw)}원으로 환산) · 수수료율 ${(r.pg_fee_rate * 100).toFixed(1)}%</p>
        </section>
      </div>
      <section class="panel"><h3>최근 결제</h3>
        ${table(["회원", "요금제", "#금액", "구분", "상태", "언제", ""], r.recent.map((p) => { const [st, tone] = PAY_STATUS[p.status] ?? [p.status, ""];
          return `<tr><td>${esc(p.email ?? "탈퇴한 회원")}${p.is_test ? ' <span class="achip">테스트</span>' : ""}</td><td>${esc(p.plan)}</td><td class="n">${won(p.amount)}</td>
            <td>${p.kind === "first" ? "첫 결제" : "정기 결제"}</td><td><span class="achip ${tone}" title="${esc(p.failure ?? "")}">${st}</span></td>
            <td class="nowrap">${ago(p.at)}</td><td>${p.receipt_url ? `<a href="${esc(p.receipt_url)}" target="_blank" rel="noopener">영수증</a>` : ""}</td></tr>`; }),
          adminState.revTest ? "아직 결제가 없어요" : "아직 실제 결제가 없어요. '테스트 결제 포함'을 켜면 테스트 결제를 볼 수 있어요")}
      </section>`;
  }

  // ---------- 개요 ----------
  async function adminOverview(body) {
    const [o, recentUsers, recentVoc, fn] = await Promise.all([
      Store.adminGet("/overview", { days: adminState.days }),
      Store.adminGet("/users", { limit: 6, sort: "recent" }),
      Store.adminFeedback({ state: "open" }),
      Store.adminGet("/funnel", { days: 30 }),
    ]);
    if (!body.isConnected) return;
    const u = o.users, a = o.active, ai = o.ai, sm = o.sign_in_methods;
    const methodsTotal = Math.max(1, sm.password + sm.google + sm.kakao);
    body.innerHTML = `
      <div class="kpis">
        ${kpi("전체 가입자", num(u.total), `오늘 +${num(u.new_today)} · 7일 +${num(u.new_7d)} · 30일 +${num(u.new_30d)}`)}
        ${kpi("활성 사용자 (오늘 / 7일 / 30일)", `${num(a.dau)} / ${num(a.wau)} / ${num(a.mau)}`, `로그인하거나 문제를 푼 사람 · <a href="#/users" class="live-link"><span class="presence on"><i></i>지금 ${num(o.online_now)}명 접속 중</span></a>`)}
        ${kpi("AI 비용 (30일)", usd(ai.cost_30d), `오늘 ${usd(ai.cost_today)}${ai.global_limit_usd ? ` / 하루 한도 ${usd(ai.global_limit_usd)} (${Math.round((ai.cost_today / ai.global_limit_usd) * 100)}%)` : ""} · 7일 ${usd(ai.cost_7d)} · 실패 ${num(ai.failed_30d)}회`, ai.global_limit_usd && ai.cost_today >= ai.global_limit_usd * 0.8 ? "warn" : "")}
        ${kpi("처리할 VOC", num(o.voc.open + o.voc.reviewing), `접수 ${num(o.voc.open)} · 확인 중 ${num(o.voc.reviewing)}`, o.voc.open ? "warn" : "")}
      </div>
      <div class="admin-grid">
        <section class="panel">
          <div class="panel-row"><h3>일별 가입자</h3>
            <div class="seg small">${[7, 30, 90].map((d) => `<button data-days="${d}" class="${adminState.days === d ? "on" : ""}">${d}일</button>`).join("")}</div></div>
          ${dayBars(o.signups_by_day, "count")}
        </section>
        <section class="panel">
          <h3>로그인 방법</h3>
          <div class="hbars">${Object.entries(sm).map(([k, n]) => `
            <div class="hbar"><span>${METHOD_NAME[k]}</span><span class="track"><i class="m-${k}" style="width:${(n / methodsTotal) * 100}%"></i></span><b>${num(n)}</b></div>`).join("")}</div>
          <p class="mini">한 사람이 여러 방법을 연결할 수 있어 합이 가입자 수보다 클 수 있어요</p>
          <div class="ov-links">
            <a href="#/logins" class="${o.failed_logins_24h >= 10 ? "warn" : ""}"><i data-lucide="shield-alert"></i>최근 24시간 로그인 실패 ${num(o.failed_logins_24h)}회</a>
            <a href="#/users" data-users-state="suspended"><i data-lucide="user-x"></i>정지된 계정 ${num(u.suspended)}명</a>
            <span class="ov-stat"><i data-lucide="footprints"></i>오늘 방문자 ${num(o.visitors_today)}명</span>
          </div>
        </section>
      </div>
      <div class="admin-grid">
        <section class="panel"><h3>가입 전환 (최근 30일)</h3>${funnelHTML(fn.steps)}</section>
        <section class="panel"><h3>주간 재방문</h3>
          <p class="mini" style="margin-top:-6px">가입한 주의 다음 주에도 문제를 풀거나 로그인한 비율</p>
          ${table(["가입 주", "#가입", "#다음 주에도 씀"], fn.cohorts.slice(-8).reverse().map((c) => `
            <tr><td class="nowrap">${c.week.slice(5).replace("-", "/")} 주</td><td class="n">${num(c.size)}</td>
              <td class="n"><b>${c.rate == null ? "–" : `${Math.round(c.rate * 100)}%`}</b> <small>${num(c.week1)}명</small></td></tr>`), "아직 가입 기록이 없어요")}</section>
      </div>
      <div class="admin-grid">
        <section class="panel"><div class="panel-row"><h3>최근 가입자</h3><a class="mini" href="#/users">전체 보기</a></div>
          ${table(["회원", "로그인 방법", "가입"], recentUsers.items.map((x) => `
            <tr class="row-link" data-href="#/users/${x.id}"><td>${userLink(x.id, x.name)}<small>${esc(x.email)}</small></td><td>${methodChips(x.methods)}</td><td class="nowrap">${ago(x.created_at)}</td></tr>`), "아직 가입자가 없어요")}</section>
        <section class="panel"><div class="panel-row"><h3>처리할 문의</h3><a class="mini" href="#/voc">VOC 열기</a></div>
          ${recentVoc.length ? `<ul class="mini-list voc-peek">${recentVoc.slice(0, 6).map((f) => `<li><span class="fb-status ${f.status}">${FB_STATUS[f.status]}</span> <b>${esc(FEEDBACK_KINDS[f.kind])}</b> · ${esc(f.message.slice(0, 80))}<small>${esc(f.user_name)} · ${ago(f.created_at)}</small></li>`).join("")}</ul>` : '<p class="mini">처리할 문의가 없어요</p>'}</section>
      </div>`;
  }

  // 퍼널: 단계별 막대 + 앞 단계 대비 비율
  function funnelHTML(steps) {
    const top = Math.max(1, steps[0].count, ...steps.map((s) => s.count));
    return `<div class="funnel">${steps.map((s, i) => {
      const prev = i ? steps[i - 1].count : null;
      return `<div class="fstep"><span>${s.label}</span>
        <span class="track"><i style="width:${(s.count / top) * 100}%"></i></span>
        <b>${num(s.count)}</b><small>${prev && s.count <= prev ? `${Math.round((s.count / prev) * 100)}%` : ""}</small></div>`;
    }).join("")}</div>${steps[1].count > steps[0].count ? '<p class="mini">방문 수는 방문 기록을 시작한 날부터 세서, 그 전에 가입한 사람이 있으면 가입보다 적게 보일 수 있어요</p>' : ""}`;
  }

  // ---------- 문제 품질 ----------
  async function adminQuality(body) {
    const q = await Store.adminGet("/quality", { days: adminState.aiDays });
    if (!body.isConnected) return;
    const g = q.generated, k = q.answer_keys;
    const keyTotal = Object.values(k).reduce((a, b) => a + b, 0);
    const KEY_NAME = { sheet: "정답표만", confirmed: "정답 확인", verified: "검산 완료", conflict: "정답표와 다름", uncertain: "확인 필요", failed: "풀이 실패" };
    body.innerHTML = `
      <div class="panel-row top"><p class="mini">AI 가 만든 문제는 정답을 모르는 다른 AI 가 다시 풀어 통과한 것만 학생에게 나가요. 떨어진 문제의 이유와 개념을 보고 출제 지시를 다듬을 수 있어요.</p>
        <div class="seg small">${[7, 30, 90].map((d) => `<button data-aidays="${d}" class="${adminState.aiDays === d ? "on" : ""}">${d}일</button>`).join("")}</div></div>
      <div class="kpis">
        ${kpi("검산 통과율", g.rate == null ? "–" : `${Math.round(g.rate * 100)}%`, `만든 문제 ${num(g.total)}개 중 ${num(g.passed)}개 통과`, g.rate != null && g.rate < 0.6 ? "warn" : "")}
        ${kpi("탈락", num(g.total - g.passed), q.reasons[0] ? `가장 많은 이유: ${esc(q.reasons[0].reason)}` : "")}
        ${kpi("정답지 문항", num(keyTotal), `확인 필요 ${num((k.conflict ?? 0) + (k.uncertain ?? 0))}`)}
        ${kpi("문제 신고", num(q.reports), "문제·해설 오류 신고")}
      </div>
      <section class="panel"><h3>일별 통과율</h3>
        ${dayBars(q.by_day.map((d) => ({ ...d, rate: d.total ? d.passed / d.total * 100 : 0 })), "rate", (v) => `${Math.round(v)}%`)}</section>
      <div class="admin-grid">
        <section class="panel"><h3>탈락 이유</h3>
          ${table(["이유", "#문제 수"], q.reasons.map((r) => `<tr><td>${esc(r.reason)}</td><td class="n">${num(r.count)}</td></tr>`), "떨어진 문제가 없어요")}</section>
        <section class="panel"><h3>통과율이 낮은 개념</h3>
          ${table(["개념", "#만든 문제", "#통과율"], q.weak_concepts.map((c) => `<tr><td>${esc(c.name)}<small>${esc(c.concept_id)}</small></td>
            <td class="n">${num(c.total)}</td><td class="n ${c.rate < 0.5 ? "bad" : ""}"><b>${Math.round(c.rate * 100)}%</b></td></tr>`), "3문제 이상 만든 개념이 아직 없어요")}</section>
      </div>
      <section class="panel"><h3>정답지 문항 상태</h3>
        <div class="hbars">${Object.entries(KEY_NAME).map(([key, name]) => `
          <div class="hbar"><span>${name}</span><span class="track"><i class="${["conflict", "uncertain", "failed"].includes(key) ? "m-kakao" : "m-google"}" style="width:${keyTotal ? ((k[key] ?? 0) / keyTotal) * 100 : 0}%"></i></span><b>${num(k[key] ?? 0)}</b></div>`).join("")}</div></section>`;
    icons();
  }

  // ---------- 문제 성적표: 학생 실력을 감안한 문항 분석 ----------
  const GRADE_TONE = { A: "ok", B: "", C: "warn", D: "bad" };
  // 표 안에서 짧게 읽히도록 LaTeX 명령과 $ 를 걷어 낸다
  const texPlain = (t = "") => t.replace(/\\(displaystyle|left|right|,|;|!)/g, " ").replace(/\\(mathrm|text)\{([^}]*)\}/g, "$2")
    .replace(/\\d?frac\{([^}]*)\}\{([^}]*)\}/g, "($1)/($2)").replace(/\\int/g, "∫").replace(/\\log/g, "log").replace(/\\mid/g, "|")
    .replace(/\\cap/g, "∩").replace(/\\times/g, "×").replace(/[$\\]/g, "").replace(/\s+/g, " ").trim();
  async function adminItems(body) {
    const f = adminState.items;
    const r = await Store.adminGet("/item-stats", { ...(f.flag && { flag: f.flag }), ...(f.grade && { grade: f.grade }) });
    if (!body.isConnected) return;
    const total = Object.values(r.grades).reduce((a, b) => a + b, 0);
    const pct = (v) => (v == null ? "–" : `${Math.round(v * 100)}%`);
    const lv = (n) => "●".repeat(n) + "○".repeat(5 - n);
    const choiceBar = (x) => {
      if (!x.choices.length || !x.n) return "";
      const key = Number(x.answer);
      return `<div class="ich">${x.choices.map((c, i) => `
        <span class="${i + 1 === key ? "key" : c.n === 0 ? "dead" : ""}" title="${esc(c.text)} · ${c.n}명${c.ability == null ? "" : ` · 고른 학생 평균 실력 ${c.ability > 0 ? "+" : ""}${c.ability}`}">
          <i style="height:${Math.max(4, Math.round((c.n / x.n) * 44))}px"></i><b>${i + 1}</b></span>`).join("")}</div>`;
    };
    body.innerHTML = `
      <div class="panel-row top"><p class="mini">학생마다 실력이 달라서 단순 정답률 대신 <b>학생 실력과 문제 난이도를 함께 추정</b>(라쉬 모형)해요. 한 학생이 처음 푼 기록만 쓰고, ${r.min_n}명 이상 푼 문제만 매겨요.
        결과는 같은 개념의 새 문제를 만들 때 AI 가 참고해요 (난이도 보정 · 잘 먹힌 함정 · 죽은 보기).${r.updated_at ? ` · 마지막 계산 ${when(r.updated_at)}` : ""}</p>
        <button class="btn-ghost" data-irefresh><i data-lucide="refresh-cw"></i>지금 다시 계산</button></div>
      <div class="kpis">
        ${["A", "B", "C", "D"].map((g) => `<button type="button" class="kpi ${f.grade === g ? "on" : ""} ${GRADE_TONE[g]}" data-igrade="${g}" style="text-align:left;cursor:pointer"><span class="k">${g} 등급</span><b>${num(r.grades[g] ?? 0)}</b><small>${total ? `${Math.round(((r.grades[g] ?? 0) / total) * 100)}%` : "–"} · 눌러서 보기</small></button>`).join("")}
      </div>
      <section class="panel"><h3>문제 표시</h3>
        <div class="ichips">${Object.entries(r.flag_names).map(([k, name]) => `<button type="button" class="itag ${f.flag === k ? "on" : ""}" data-iflag="${k}">${esc(name)} <b>${num(r.flags[k] ?? 0)}</b></button>`).join("")}</div></section>
      <section class="panel"><h3>문제별 성적 <small class="mini">${f.grade || f.flag ? "필터 적용 중 — 같은 걸 다시 누르면 풀려요" : "나쁜 등급부터"}</small></h3>
        ${table(["등급", "문제", "#푼 학생", "#정답률", "난이도 의도 → 실제", "#변별도", "보기 (높이 = 고른 비율, 파랑 = 정답)", "표시"], r.items.map((x) => `
          <tr><td><span class="achip ${GRADE_TONE[x.grade]}">${x.grade}</span></td>
            <td class="istem">${esc(texPlain(x.stem))}<small>${esc(x.concept)} · ${esc(x.problem_id)}${x.source === "generated" ? " · AI 생성" : ""}</small></td>
            <td class="n">${num(x.n)}</td><td class="n">${pct(x.p)}</td>
            <td class="nowrap"><span title="의도">${lv(x.intended)}</span><br><span title="실제" class="${Math.abs(x.observed - x.intended) >= 2 ? "bad" : ""}">${lv(x.observed)}</span></td>
            <td class="n ${x.disc != null && x.disc < 0.15 ? "bad" : ""}">${x.disc == null ? "–" : x.disc.toFixed(2)}</td>
            <td>${choiceBar(x)}</td>
            <td>${x.flags.map((k) => `<span class="achip ${["neg_disc", "key_suspect"].includes(k) ? "bad" : "warn"}">${esc(r.flag_names[k] ?? k)}</span>`).join(" ") || '<span class="mini">—</span>'}</td></tr>`),
          total ? "조건에 맞는 문제가 없어요" : `아직 ${r.min_n}명 이상 푼 문제가 없어요. 풀이가 쌓이면 매일 아침 자동으로 매겨요`)}</section>`;
    icons();
  }

  // ---------- 하네스: AI 실행 기록 ----------
  const RUN_KIND = { generate: "문제 생성", agent: "대화 에이전트" };
  const RUN_STATUS = { passed: ["통과", "ok"], rejected: ["탈락", "warn"], answered: ["답변", "ok"], failed: ["실패", "bad"] };
  const STEP_NAME = { generate: "생성 AI", format_check: "형식 검사", verify: "검증 AI (독립 재풀이)", math_check: "검산 에이전트 판정",
    duplicate_check: "RAG 중복 확인", agent: "대화 에이전트 답", self_correct: "자기 수정 — 떨어진 이유를 생성 AI 에 전달" };
  const statusChip = (st) => { const [t, tone] = RUN_STATUS[st] ?? [st, ""]; return `<span class="achip ${tone}">${esc(t)}</span>`; };
  const ms = (v) => (v == null ? "–" : v >= 1000 ? `${(v / 1000).toFixed(1)}초` : `${v}ms`);
  const usd4 = (v) => (v == null ? "–" : `$${Number(v).toFixed(4)}`);

  async function adminRuns(body) {
    const f = adminState.runs;
    const [h, runs] = await Promise.all([Store.adminGet("/harness", { days: 30 }),
      Store.adminGet("/runs", { ...(f.kind && { kind: f.kind }), ...(f.status && { status: f.status }), limit: 80 })]);
    if (!body.isConnected) return;
    body.innerHTML = `
      <div class="panel-row top"><p class="mini">AI 실행 한 번마다 <b>하네스 버전</b>(모든 지시문 버전 + 모델 설정의 해시)과 단계별 기록이 남아요.
        지시문 파일(<code>harness/prompts/</code>)을 한 글자라도 바꾸면 버전이 바뀌어서, 버전끼리 결과를 비교할 수 있어요.</p></div>
      <div class="kpis">
        ${kpi("지금 하네스 버전", `<code>${esc(h.harness_version)}</code>`, `지시문 ${Object.keys(h.prompts).length}개`)}
        ${kpi("생성 · 검증 모델", esc(h.models.generate.split("/")[0]), `검증 ${esc(h.models.verify)}`)}
        ${kpi("대화 모델", esc(h.models.route.split("/")[0]), `임베딩 ${esc(h.models.embedding)}`)}
      </div>
      <section class="panel"><h3>버전별 결과 (최근 ${h.days}일)</h3>
        ${table(["하네스 버전", "종류", "#실행", "결과", "#평균 비용", "#평균 시간", "처음 쓰인 때"], h.versions.map((v) => `
          <tr><td><code>${esc(v.harness_version)}</code>${v.harness_version === h.harness_version ? ' <span class="achip ok">지금</span>' : ""}</td>
            <td>${esc(RUN_KIND[v.kind] ?? v.kind)}</td><td class="n">${num(v.runs)}</td>
            <td>${Object.entries(v.statuses).map(([st, n]) => `${statusChip(st)} ${num(n)}`).join(" ")}</td>
            <td class="n">${usd4(v.avg_cost_usd)}</td><td class="n">${ms(Math.round(v.avg_latency_ms))}</td><td class="nowrap">${when(v.first_at)}</td></tr>`),
          "아직 기록된 실행이 없어요")}</section>
      <section class="panel"><h3>실행 기록</h3>
        <div class="ichips">${Object.entries(RUN_KIND).map(([k, t]) => `<button type="button" class="itag ${f.kind === k ? "on" : ""}" data-rkind="${k}">${t}</button>`).join("")}
          ${Object.entries(RUN_STATUS).map(([k, [t]]) => `<button type="button" class="itag ${f.status === k ? "on" : ""}" data-rstatus="${k}">${t}</button>`).join("")}</div>
        ${table(["시각", "종류", "결과", "입력 → 결과", "#단계", "#도구", "#비용", "#시간"], runs.map((r) => `
          <tr class="click" data-run="${r.id}"><td class="nowrap">${when(r.created_at)}<small>${esc(r.email ?? "")}</small></td>
            <td>${esc(RUN_KIND[r.kind] ?? r.kind)}<small><code>${esc(r.harness_version)}</code></small></td><td>${statusChip(r.status)}</td>
            <td class="istem">${esc(r.input)}<small>${esc(r.output)}</small></td>
            <td class="n">${num(r.steps)}</td><td class="n">${num(r.tools)}</td><td class="n">${usd4(r.cost_usd)}</td><td class="n">${ms(r.latency_ms)}</td></tr>`),
          "조건에 맞는 실행이 없어요")}</section>
      <section class="panel"><h3>지시문 버전</h3>
        ${table(["지시문", "버전"], Object.entries(h.prompts).map(([n, v]) => `<tr><td><code>${esc(n)}</code></td><td><code>${esc(v)}</code></td></tr>`), "")}</section>`;
    icons();
  }

  async function adminRun(body, id) {
    const r = await Store.adminGet(`/runs/${id}`);
    if (!body.isConnected) return;
    const stepRow = (s, i) => {
      const tool = s.name.startsWith("tool:");
      const title = tool ? `도구 · ${s.name.slice(5)}` : (STEP_NAME[s.name] ?? s.name);
      const d = s.data ?? {};
      const detail = tool ? `<code>${esc(JSON.stringify(d.args ?? {}))}</code> → <b>${esc(String(d.result ?? ""))}</b>`
        : Object.entries(d).map(([k, v]) => `<span class="rk">${esc(k)}</span> ${esc(typeof v === "string" ? v : JSON.stringify(v))}`).join("<br>");
      return `
        <li class="rstep ${s.ok ? "ok" : "bad"} ${tool ? "tool" : ""}">
          <span class="rdot">${i + 1}</span>
          <div class="rbody">
            <div class="rhead"><b>${esc(title)}</b>${s.ok ? "" : ' <span class="achip bad">실패</span>'}
              <span class="rmeta">${s.model ? esc(s.model) + " · " : ""}${s.tokens ? `토큰 ${num(s.tokens.in)}/${num(s.tokens.out)} · ` : ""}${s.cost != null ? usd4(s.cost) + " · " : ""}${ms(s.ms)}</span></div>
            ${detail ? `<div class="rdetail">${detail}</div>` : ""}
            ${s.error ? `<div class="rdetail err-text">${esc(s.error)}</div>` : ""}
          </div>
        </li>`;
    };
    body.innerHTML = `
      <p><a href="#/runs">← 실행 기록</a></p>
      <div class="kpis">
        ${kpi("결과", statusChip(r.status), esc(RUN_KIND[r.kind] ?? r.kind))}
        ${kpi("하네스 버전", `<code>${esc(r.harness_version)}</code>`, when(r.created_at))}
        ${kpi("비용", usd4(r.cost_usd), `단계 ${r.steps.length}개`)}
        ${kpi("걸린 시간", ms(r.latency_ms), r.email ? esc(r.email) : "")}
      </div>
      <section class="panel"><h3>입력</h3><p class="rtext">${esc(r.input)}</p>
        <h3>결과</h3><p class="rtext">${esc(r.output)}${r.problem_id ? ` · 문제 <code>${esc(r.problem_id)}</code>` : ""}</p></section>
      <section class="panel"><h3>단계별 타임라인</h3><ol class="rtimeline">${r.steps.map(stepRow).join("")}</ol></section>
      <section class="panel"><h3>이 실행에 쓴 지시문</h3>
        ${table(["지시문", "버전"], Object.entries(r.prompt_versions).map(([n, v]) => `<tr><td><code>${esc(n)}</code></td><td><code>${esc(v)}</code></td></tr>`), "")}</section>`;
    icons();
  }

  // ---------- 하네스 평가 (점수판) ----------
  const pctv = (v) => (v == null ? "–" : `${Math.round(v * 100)}%`);
  const DEFECT_NAME = { wrong_key: "정답 번호 오류", multiple_answers: "복수 정답", missing_condition: "조건 누락", no_correct_choice: "맞는 보기 없음" };
  const delta = (cur, prev, good = "up") => {
    if (cur == null || prev == null) return "";
    const d = Math.round((cur - prev) * 100);
    if (!d) return '<small class="dz">±0</small>';
    const better = good === "up" ? d > 0 : d < 0;
    return `<small class="${better ? "du" : "dd"}">${d > 0 ? "+" : ""}${d}%p</small>`;
  };

  // 생성 효율 (자기 수정 루프 전후 비교) — 자기 수정을 켠 평가와 끈 평가 중 가장 최근 것끼리
  function genCard(done) {
    const withGen = done.filter((e) => e.metrics?.generate);
    if (!withGen.length) return "";
    const on = withGen.find((e) => e.models?.self_correct !== "False"), off = withGen.find((e) => e.models?.self_correct === "False");
    const g = (e) => e?.metrics?.generate ?? {};
    const row = (label, k, fmt, good = "up") => `<tr><td>${label}</td><td class="n">${off ? fmt(g(off)[k]) : "–"}</td><td class="n"><b>${on ? fmt(g(on)[k]) : "–"}</b></td>
      <td class="n">${on && off && g(on)[k] != null && g(off)[k] != null ? delta(g(on)[k], g(off)[k], good) : ""}</td></tr>`;
    return `<section class="panel"><h3>생성 효율 — 자기 수정 루프 끔 / 켬 <small class="mini">실제로 문제를 만들어 보고 되돌림</small></h3>
      ${table(["지표", "#끔", "#켬", "#차이"], [
        row("통과율 (요청 대비)", "yield", pctv), row("첫 시도 통과율", "first_try_pass", pctv),
        `<tr><td>문제당 시도 횟수</td><td class="n">${off ? g(off).avg_attempts ?? "–" : "–"}</td><td class="n"><b>${on ? g(on).avg_attempts ?? "–" : "–"}</b></td><td></td></tr>`,
        `<tr><td>통과 문제당 비용</td><td class="n">${off ? usd4(g(off).cost_per_accepted) : "–"}</td><td class="n"><b>${on ? usd4(g(on).cost_per_accepted) : "–"}</b></td><td></td></tr>`,
        `<tr><td>고쳐서 다시 낸 문제 → 통과</td><td class="n">–</td><td class="n"><b>${on ? `${num(g(on).self_corrected)}개 → ${pctv(g(on).self_correct_success)}` : "–"}</b></td><td></td></tr>`,
      ], "")}</section>`;
  }

  async function adminEvals(body) {
    const list = await Store.adminGet("/evals");
    if (!body.isConnected) return;
    const done = list.filter((e) => e.status === "done" && e.mode === "live");
    const [cur, prev] = done;
    const v = cur?.metrics?.verify ?? {}, pv = prev?.metrics?.verify ?? {};
    const r = cur?.metrics?.retrieval ?? {}, pr = prev?.metrics?.retrieval ?? {};
    body.innerHTML = `
      <div class="panel-row top"><p class="mini">골든셋(좋은 문제 + 일부러 망가뜨린 문제)을 <b>실제 문제 생성과 같은 검사 층</b>(검증 AI → 계산 도구 검산 에이전트)에 통과시켜요.
        하네스 버전마다 점수를 남겨서, 지시문 · 모델 · 도구를 바꿨을 때 좋아졌는지 숫자로 비교해요. 화살표는 바로 앞 평가와의 차이예요.</p>
        <button class="btn-ghost" data-eval-run><i data-lucide="play"></i>지금 평가 (실제 AI)</button></div>
      ${cur ? `<div class="kpis">
        ${kpi("망가진 문제 탐지율", `${pctv(v.detection_rate)} ${delta(v.detection_rate, pv.detection_rate)}`, `${num(v.bad)}문제 중 · 높을수록 좋아요`)}
        ${kpi("좋은 문제 오탐률", `${pctv(v.false_reject_rate)} ${delta(v.false_reject_rate, pv.false_reject_rate, "down")}`, `${num(v.good)}문제 중 · 낮을수록 좋아요`)}
        ${kpi("검산 에이전트 추가 탐지", `${pctv(v.math_check_added)} ${delta(v.math_check_added, pv.math_check_added)}`, `검증 AI 혼자 ${pctv(v.verifier_detection)} · Tool Calling 기여`)}
        ${kpi("RAG 검색 recall@3", `${pctv(r.recall_at_3)} ${delta(r.recall_at_3, pr.recall_at_3)}`, `MRR ${r.mrr ?? "–"}`)}
      </div>
      <section class="panel"><h3>결함 종류별 탐지율 <small class="mini">하네스 <code>${esc(cur.harness_version)}</code> · ${when(cur.created_at)}</small></h3>
        <div class="hbars">${Object.entries(v.by_defect ?? {}).map(([k, d]) => `
          <div class="hbar"><span>${esc(DEFECT_NAME[k] ?? k)} <small>(${d.cases})</small></span><span class="track"><i class="m-google" style="width:${(d.detected ?? 0) * 100}%"></i></span><b>${pctv(d.detected)}</b></div>`).join("")}</div>
        <p class="mini">검산 에이전트 판단 정확도 ${pctv(v.math_check_accuracy)} (${num(v.math_check_runs)}번 실행) · 평가 비용 ${usd4(cur.cost_usd)} · 문항당 평균 ${ms(v.avg_ms)}</p></section>
      ${genCard(done)}`
        : '<section class="panel"><p class="mini">아직 실제 AI 평가가 없어요. 위 버튼으로 첫 평가(기준점)를 만들어 주세요.</p></section>'}
      <section class="panel"><h3>평가 기록</h3>
        ${table(["시각", "하네스 버전", "방식", "상태", "#탐지율", "#오탐률", "#검산 추가", "#recall@3", "#비용"], list.map((e) => {
          const m = e.metrics?.verify ?? {}, q = e.metrics?.retrieval ?? {};
          return `<tr class="click" data-eval="${e.id}"><td class="nowrap">${when(e.created_at)}</td><td><code>${esc(e.harness_version)}</code></td>
            <td>${e.mode === "live" ? "실제 AI" : "재생"}</td>
            <td>${e.status === "done" ? '<span class="achip ok">완료</span>' : e.status === "running" ? '<span class="achip warn">진행 중</span>' : `<span class="achip bad" title="${esc(e.error ?? "")}">실패</span>`}</td>
            <td class="n">${pctv(m.detection_rate)}</td><td class="n">${pctv(m.false_reject_rate)}</td><td class="n">${pctv(m.math_check_added)}</td>
            <td class="n">${pctv(q.recall_at_3)}</td><td class="n">${usd4(e.cost_usd)}</td></tr>`;
        }), "평가 기록이 없어요")}</section>`;
    icons();
  }

  async function adminEval(body, id) {
    const e = await Store.adminGet(`/evals/${id}`);
    if (!body.isConnected) return;
    const vc = e.cases?.verify ?? [], rc = e.cases?.retrieval ?? [];
    const verdictCell = (c) => {
      const ok = (c.label === "good") === (c.decision === "pass");
      return `<span class="achip ${ok ? "ok" : "bad"}">${c.decision === "pass" ? "통과" : "탈락"}${ok ? "" : " ✗"}</span>`;
    };
    body.innerHTML = `
      <p><a href="#/evals">← 하네스 평가</a></p>
      <div class="kpis">
        ${kpi("하네스 버전", `<code>${esc(e.harness_version)}</code>`, when(e.created_at))}
        ${kpi("탐지율 / 오탐률", `${pctv(e.metrics?.verify?.detection_rate)} / ${pctv(e.metrics?.verify?.false_reject_rate)}`, e.mode === "live" ? "실제 AI" : "재생")}
        ${kpi("recall@3", pctv(e.metrics?.retrieval?.recall_at_3), `MRR ${e.metrics?.retrieval?.mrr ?? "–"}`)}
        ${kpi("비용 · 시간", usd4(e.cost_usd), ms(e.latency_ms))}
      </div>
      ${e.error ? `<section class="panel"><p class="err-text">${esc(e.error)}</p></section>` : ""}
      <section class="panel"><h3>검증 골든셋 — 문항별 <small class="mini">✗ = 기대와 다른 판정</small></h3>
        ${table(["문항", "정답", "결함", "판정", "거른 곳", "검증 AI", "검산 에이전트"], vc.map((c) => `
          <tr><td><code>${esc(c.id)}</code></td><td>${c.label === "good" ? "좋은 문제" : "망가진 문제"}</td><td>${esc(DEFECT_NAME[c.defect] ?? "")}</td>
            <td>${verdictCell(c)}</td><td>${c.caught_by === "verifier" ? "검증 AI" : c.caught_by === "math_check" ? "검산 에이전트" : "—"}</td>
            <td class="istem">${c.verifier ? `답 ${esc(c.verifier.verdict.answer)} · ${c.verifier.verdict.well_posed ? "결함 없음" : "결함: " + esc((c.verifier.verdict.issues || []).join(", "))}` : ""}</td>
            <td class="istem">${c.math ? (c.math.error ? `오류` : `${c.math.checkable ? (c.math.agrees ? "일치" : "불일치") : "계산 대상 아님"} · ${esc(c.math.computed || "")}<small>${esc((c.math.tools || []).join(" → "))}</small>`) : "—"}</td></tr>`), "")}</section>
      <section class="panel"><h3>RAG 검색 골든셋</h3>
        ${table(["질문", "기대 개념", "순위", "위 3개 (유사도)"], rc.map((c) => `
          <tr><td class="istem">${esc(c.query)}</td><td><code>${esc(c.expected)}</code></td><td>${c.rank ? `<span class="achip ok">${c.rank}위</span>` : '<span class="achip bad">없음</span>'}</td>
            <td class="istem">${c.top.map((h) => `${h.similarity} · ${esc((h.concepts || []).join(","))}`).join("<br>")}</td></tr>`), "")}</section>`;
    icons();
  }

  // ---------- AI 사용량 ----------
  async function adminAI(body) {
    const r = await Store.adminGet("/ai-usage", { days: adminState.aiDays });
    if (!body.isConnected) return;
    const t = r.totals;
    const groupRows = (list, name = (k) => k) => list.map((g) => `
      <tr><td>${esc(name(g.key))}</td><td class="n">${num(g.calls)}</td><td class="n ${g.failed ? "bad" : ""}">${num(g.failed)}</td>
        <td class="n">${compact(g.tokens)}</td><td class="n">${(g.avg_latency_ms / 1000).toFixed(1)}초</td><td class="n"><b>${usd(g.cost_usd)}</b></td></tr>`);
    const gHead = ["", "#호출", "#실패", "#토큰", "#평균 응답", "#비용"];
    body.innerHTML = `
      <div class="panel-row top"><p class="mini">모든 AI 호출(문제 생성·검증, 개념 정리, 기출 분석, 서술형 채점 등)의 토큰과 비용 기록이에요. 비용은 호출 시점 단가로 계산한 예상치예요.</p>
        <div class="seg small">${[1, 7, 30, 90].map((d) => `<button data-aidays="${d}" class="${adminState.aiDays === d ? "on" : ""}">${d === 1 ? "오늘" : `${d}일`}</button>`).join("")}</div></div>
      <div class="kpis">
        ${kpi("비용", usd(t.cost_usd), `하루 평균 ${usd(t.cost_usd / r.days)}`)}
        ${kpi("호출", num(t.calls), `실패 ${num(t.failed)}회${t.calls ? ` (${Math.round((t.failed / t.calls) * 100)}%)` : ""}`, t.failed && t.failed / Math.max(1, t.calls) > 0.1 ? "warn" : "")}
        ${kpi("토큰 (입력 / 출력)", `${compact(t.input_tokens)} / ${compact(t.output_tokens)}`, `캐시 ${compact(t.cached_tokens)} · 추론 ${compact(t.reasoning_tokens)}`)}
        ${kpi("평균 응답 시간", `${(t.avg_latency_ms / 1000).toFixed(1)}초`, "성공한 호출 기준")}
      </div>
      ${r.days > 1 ? `<section class="panel"><h3>일별 비용</h3>${dayBars(r.by_day, "cost_usd", usd)}</section>` : ""}
      <div class="admin-grid">
        <section class="panel"><h3>용도별</h3>${table(gHead, groupRows(r.by_purpose, (k) => PURPOSE_NAME[k] ?? k), "기록이 없어요")}</section>
        <section class="panel"><h3>모델별</h3>${table(gHead, groupRows(r.by_model), "기록이 없어요")}</section>
      </div>
      <div class="admin-grid">
        <section class="panel"><h3>비용이 많은 사용자</h3>${table(["사용자", "#호출", "#비용"], r.top_users.map((x) => `
          <tr><td>${userLink(x.user_id, x.name)}<small>${esc(x.email)}</small></td><td class="n">${num(x.calls)}</td><td class="n"><b>${usd(x.cost_usd)}</b></td></tr>`), "기록이 없어요")}</section>
        <section class="panel"><h3>최근 실패</h3>${table(["시각", "용도", "오류"], r.recent_errors.map((x) => `
          <tr><td class="nowrap">${when(x.at)}</td><td>${esc(PURPOSE_NAME[x.purpose] ?? x.purpose)}<small>${esc(x.model)}${x.email ? ` · ${esc(x.email)}` : ""}</small></td><td class="err-text">${esc(x.error)}</td></tr>`), "실패한 호출이 없어요")}</section>
      </div>`;
  }

  // ---------- 로그인 기록 ----------
  let loginItems = [];
  async function adminLogins(body, more = false) {
    const f = adminState.logins;
    const params = { limit: 100, result: f.result, ...(f.q && { q: f.q }), ...(f.method && { method: f.method }) };
    if (more && loginItems.length) params.before = loginItems.at(-1).at;
    const r = await Store.adminGet("/logins", params);
    if (!body.isConnected) return;
    loginItems = more ? [...loginItems, ...r.items] : r.items;
    body.innerHTML = `
      <div class="filters">
        <label class="search-box"><i data-lucide="search"></i><input id="lg-q" placeholder="이메일, 이름, IP" value="${esc(f.q)}" /></label>
        <div class="seg small">${[["all", "전체"], ["ok", "성공"], ["fail", "실패"]].map(([k, t]) => `<button data-lresult="${k}" class="${f.result === k ? "on" : ""}">${t}</button>`).join("")}</div>
        <select id="lg-method" class="sel"><option value="">모든 방법</option>${Object.entries(METHOD_NAME).map(([k, t]) => `<option value="${k}" ${f.method === k ? "selected" : ""}>${t}</option>`).join("")}</select>
        <span class="mini grow">최근 24시간 성공 ${num(r.last_24h.ok)} · <b class="${r.last_24h.failed ? "bad" : ""}">실패 ${num(r.last_24h.failed)}</b> · 기록은 ${r.retention_days}일 보관</span>
      </div>
      <section class="panel flush">${table(["시각", "사용자", "방법", "결과", "IP", "기기"], loginItems.map((e) => `
        <tr class="${e.ok ? "" : "fail"}"><td class="nowrap">${when(e.at)}</td>
          <td>${e.user_id ? userLink(e.user_id, e.name ?? e.email) : `<span class="muted">${esc(e.email ?? "–")}</span>`}${e.user_id ? `<small>${esc(e.email ?? "")}</small>` : '<small>가입되지 않은 이메일</small>'}</td>
          <td>${methodChips([e.method])}${e.kind === "signup" ? '<span class="mchip new">가입</span>' : ""}</td>
          <td>${e.ok ? '<span class="ok">성공</span>' : `<span class="bad">실패</span><small>${FAIL_REASON[e.reason] ?? e.reason ?? ""}</small>`}</td>
          <td class="mono">${esc(e.ip ?? "–")}</td><td title="${esc(e.user_agent ?? "")}">${device(e.user_agent ?? "")}</td></tr>`), "조건에 맞는 기록이 없어요")}</section>
      ${r.items.length === 100 ? '<div class="more-row"><button class="btn-ghost" data-lmore>더 보기</button></div>' : ""}`;
    icons();
  }

  // ---------- 회원 ----------
  async function adminUsers(body) {
    const f = adminState.users;
    const PAGE = 50;
    const r = await Store.adminGet("/users", { limit: PAGE, offset: f.offset, state: f.state, sort: f.sort, ...(f.q && { q: f.q }) });
    if (!body.isConnected) return;
    body.innerHTML = `
      <section class="panel live" id="live-panel"><p class="mini">접속 현황을 불러오는 중…</p></section>
      <div class="filters">
        <label class="search-box"><i data-lucide="search"></i><input id="us-q" placeholder="이름, 이메일 또는 IP" value="${esc(f.q)}" /></label>
        <div class="seg small">${[["all", "전체"], ["online", "접속 중"], ["active", "이용 중"], ["suspended", "정지"]].map(([k, t]) => `<button data-ustate="${k}" class="${f.state === k ? "on" : ""}">${t}</button>`).join("")}</div>
        <select id="us-sort" class="sel">${[["recent", "최근 가입순"], ["seen", "최근 활동순"], ["login", "최근 로그인순"], ["attempts", "푼 문제 많은 순"], ["cost", "AI 비용 많은 순"]].map(([k, t]) => `<option value="${k}" ${f.sort === k ? "selected" : ""}>${t}</option>`).join("")}</select>
        <span class="mini grow">${num(r.total)}명</span>
        <button class="btn-ghost" data-ucsv title="지금 검색·필터·정렬 그대로 전체 회원을 내려받아요"><i data-lucide="download"></i>CSV 내려받기</button>
      </div>
      <section class="panel flush">${table(["회원", "접속", "최근 IP · 기기", "로그인 방법", "가입", "최근 로그인", "#푼 문제", "#AI 비용", "상태"], r.items.map((u) => `
        <tr class="row-link" data-href="#/users/${u.id}"><td>${userLink(u.id, u.name)}<small>${esc(u.email)}</small></td>
          <td class="nowrap">${presenceBadge(u)}</td>
          <td class="nowrap"><span class="mono">${esc(u.last_seen_ip ?? "–")}</span><small>${device(u.last_seen_ua ?? "")}</small></td>
          <td>${methodChips(u.methods)}</td><td class="nowrap">${when(u.created_at).slice(0, 10)}</td><td class="nowrap">${ago(u.last_login_at)}</td>
          <td class="n">${num(u.attempts)}</td><td class="n">${usd(u.cost_usd)}</td>
          <td>${u.suspended_at ? '<span class="upill bad">정지</span>' : u.is_admin ? '<span class="upill">운영자</span>' : '<span class="upill ok">이용 중</span>'}</td></tr>`), "조건에 맞는 회원이 없어요")}</section>
      <div class="more-row">
        <button class="btn-ghost" data-upage="-1" ${f.offset ? "" : "disabled"}>이전</button>
        <span class="mini">${r.total ? `${f.offset + 1}–${Math.min(f.offset + PAGE, r.total)} / ${num(r.total)}` : ""}</span>
        <button class="btn-ghost" data-upage="1" ${f.offset + PAGE < r.total ? "" : "disabled"}>다음</button>
      </div>`;
    icons();
    startLive();
  }

  // 지금 접속 중 — 회원 목록을 보는 동안 15초마다 새로 받는다
  let liveTimer = null;
  function startLive() {
    clearInterval(liveTimer);
    const draw = async () => {
      const el = $("#live-panel");
      if (!el) return clearInterval(liveTimer);
      let p;
      try { p = await Store.adminGet("/presence"); } catch (err) { el.innerHTML = `<p class="mini">${esc(err.message)}</p>`; return; }
      if (!el.isConnected) return;
      const rows = p.items;
      el.innerHTML = `
        <div class="live-head">
          <h3><span class="pulse"></span>지금 접속 중</h3>
          <div class="live-stats"><span><b>${num(p.online)}</b>명 접속 중</span><span><b>${num(p.recent)}</b>명 15분 안 활동</span><span><b>${num(p.today)}</b>명 오늘 접속</span></div>
          <span class="mini">15초마다 새로 고침 · ${new Date(p.at).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>
        </div>
        ${rows.length ? `<div class="live-list">${rows.map((u) => `
          <a class="live-row" href="#/users/${u.id}">
            ${presenceBadge(u, true)}
            <span class="live-who"><b>${esc(u.name)}</b><small>${esc(u.email)}</small></span>
            <span class="live-page"><i data-lucide="monitor"></i>${esc(PAGE_NAME[u.last_seen_page] ?? "–")}</span>
            <span class="mono live-ip">${esc(u.last_seen_ip ?? "–")}</span>
            <span class="live-dev">${device(u.last_seen_ua ?? "")}</span>
          </a>`).join("")}</div>` : '<p class="mini">지금은 접속한 회원이 없어요. 학습 화면을 열어 둔 회원은 1분마다 여기에 나타나요</p>'}`;
      icons();
    };
    draw();
    liveTimer = setInterval(() => { if (document.visibilityState === "visible") draw(); }, 15_000);
  }

  let adminUserCache = null;
  async function adminUser(body, id) {
    const d = await Store.adminGet(`/users/${id}`);
    if (!body.isConnected) return;
    adminUserCache = d;
    const u = d.user, l = d.learning;
    const facts = [
      ["가입", when(u.created_at)], ["최근 로그인", u.last_login_at ? `${when(u.last_login_at)} (${ago(u.last_login_at)})` : "없음"],
      ["마지막 활동", u.last_seen_at ? `${when(u.last_seen_at)} (${ago(u.last_seen_at)})` : "기록 없음"],
      ["보고 있던 화면", PAGE_NAME[u.last_seen_page] ?? "–"], ["최근 접속 IP", u.last_seen_ip ?? "–"], ["기기", device(u.last_seen_ua ?? "")],
      ["이메일 인증", u.email_verified ? "인증됨" : "미인증"], ["마케팅 수신", u.agreed_marketing ? "동의" : "미동의"],
      ["학교 · 전공", [u.school, u.major].filter(Boolean).join(" · ") || "–"], ["하루 목표", `${u.daily_goal}문제`],
    ];
    body.innerHTML = `
      <a class="back-link" href="#/users"><i data-lucide="arrow-left"></i>회원 목록</a>
      <section class="panel user-head">
        <div class="who"><h2>${esc(u.name)} ${presenceBadge(u, true)}</h2><p>${esc(u.email)}</p><div>${methodChips(u.methods)}${u.is_admin ? '<span class="upill">운영자</span>' : ""}</div></div>
        <div class="uactions">${u.is_admin ? '<p class="mini">운영자 계정은 정지·삭제할 수 없어요</p>' : `
          <button class="btn-ghost" data-ulogout title="이 회원이 쓰던 모든 곳의 로그인을 끊어요"><i data-lucide="log-out"></i>강제 로그아웃</button>
          ${u.suspended_at ? '<button class="btn-ghost" data-unsuspend><i data-lucide="user-check"></i>정지 해제</button>' : '<button class="btn-ghost" data-suspend><i data-lucide="user-x"></i>이용 정지</button>'}
          <button class="btn-ghost danger-text" data-udelete><i data-lucide="trash-2"></i>계정 삭제</button>`}</div>
        ${u.suspended_at ? `<div class="suspend-note"><i data-lucide="ban"></i><span><b>${when(u.suspended_at)}부터 이용 정지</b> · ${esc(u.suspended_reason ?? "")}</span></div>` : ""}
      </section>
      <div class="kpis">
        ${kpi("푼 문제", num(l.attempts), `정답률 ${pct(l.accuracy)} · 오늘 ${num(l.today)} · ${l.streak}일 연속`)}
        ${kpi("남은 오답", num(l.open_notes), `마지막 풀이 ${ago(l.last_attempt_at)}`)}
        ${kpi("프로젝트 · 대화", `${num(l.projects)} · ${num(l.sessions)}`, `암기 카드 ${num(l.cards)} · 올린 자료 ${num(l.materials)}`)}
        ${kpi("AI 사용", usd(d.ai.cost_usd), `${num(d.ai.calls)}회 호출`)}
      </div>
      <div class="admin-grid">
        <section class="panel"><h3>정보</h3><dl class="facts">${facts.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("")}</dl></section>
        <section class="panel"><div class="panel-row"><h3>보낸 문의</h3>${d.feedback.length ? `<a class="mini" href="#/voc" data-voc-user="${u.id}">VOC에서 보기</a>` : ""}</div>
          ${d.feedback.length ? `<ul class="mini-list">${d.feedback.map((f) => `<li><span class="fb-status ${f.status}">${FB_STATUS[f.status]}</span> ${esc(FEEDBACK_KINDS[f.kind])} · ${esc(f.message)}<small>${when(f.created_at)}</small></li>`).join("")}</ul>` : '<p class="mini">보낸 문의가 없어요</p>'}</section>
      </div>
      ${d.actions.length ? `<section class="panel"><h3>이 회원에 대한 조치</h3>${table(["시각", "조치", "운영자", "내용"], d.actions.map((a) => `
        <tr><td class="nowrap">${when(a.at)}</td><td>${actionChip(a.action)}</td><td>${esc(a.admin_email)}</td><td>${esc(a.detail ?? "–")}</td></tr>`), "")}</section>` : ""}
      <section class="panel"><h3>접속한 IP</h3>${table(["IP", "#로그인", "#실패", "마지막"], d.ips.map((x) => `
        <tr><td class="mono">${esc(x.ip)}${x.ip === u.last_seen_ip ? ' <span class="upill ok">최근</span>' : ""}</td><td class="n">${num(x.logins)}</td>
          <td class="n ${x.failed ? "bad" : ""}">${num(x.failed)}</td><td class="nowrap">${when(x.last_at)} · ${ago(x.last_at)}</td></tr>`), "최근 90일 로그인 기록이 없어요")}
        <p class="mini">로그인 기록 기준 (90일 보관). 여러 IP에서 실패가 많으면 계정 도용 시도일 수 있어요</p></section>
      <section class="panel"><h3>최근 로그인 기록</h3>${table(["시각", "방법", "결과", "IP", "기기"], d.logins.map((e) => `
        <tr class="${e.ok ? "" : "fail"}"><td class="nowrap">${when(e.at)}</td><td>${methodChips([e.method])}${e.kind === "signup" ? '<span class="mchip new">가입</span>' : ""}</td>
          <td>${e.ok ? '<span class="ok">성공</span>' : `<span class="bad">실패</span><small>${FAIL_REASON[e.reason] ?? ""}</small>`}</td><td class="mono">${esc(e.ip ?? "–")}</td><td>${device(e.user_agent ?? "")}</td></tr>`), "최근 90일 기록이 없어요")}</section>`;
    icons();
  }

  // ---------- 관리 기록 ----------
  async function adminActions(body) {
    const f = adminState.actions;
    const r = await Store.adminGet("/actions", { limit: 200, ...(f.action && { action: f.action }), ...(f.q && { q: f.q }) });
    if (!body.isConnected) return;
    const c = r.last_30d;
    body.innerHTML = `
      <div class="kpis">
        ${kpi("이용 정지 (30일)", num(c.suspend), `정지 해제 ${num(c.unsuspend)}`, c.suspend ? "warn" : "")}
        ${kpi("강제 로그아웃 (30일)", num(c.logout))}
        ${kpi("계정 삭제 (30일)", num(c.delete))}
        ${kpi("VOC 처리 (30일)", num((c.voc_status ?? 0) + (c.voc_reply ?? 0)), `답변 ${num(c.voc_reply)} · 공지 ${num(c.announce)}`)}
      </div>
      <div class="filters">
        <label class="search-box"><i data-lucide="search"></i><input id="ac-q" placeholder="운영자·대상 이메일 또는 내용" value="${esc(f.q)}" /></label>
        <select id="ac-action" class="sel"><option value="">모든 조치</option>${Object.entries(ACTION_NAME).map(([k, [t]]) => `<option value="${k}" ${f.action === k ? "selected" : ""}>${t}</option>`).join("")}</select>
        <span class="mini grow">${num(r.items.length)}건${r.items.length >= 200 ? " (최근 200건)" : ""}</span>
      </div>
      <section class="panel flush">${table(["시각", "조치", "대상", "내용", "운영자", "IP"], r.items.map((a) => `
        <tr><td class="nowrap">${when(a.at)}<small>${ago(a.at)}</small></td><td>${actionChip(a.action)}</td>
          <td>${a.target_user_id ? `${userLink(a.target_user_id, a.target_email ?? "")}` : esc(a.target_email ?? "–")}</td>
          <td>${esc(a.detail ?? "–")}</td><td>${esc(a.admin_email)}</td><td class="mono">${esc(a.ip ?? "–")}</td></tr>`), "아직 기록된 조치가 없어요")}</section>
      <p class="mini">조치 기록은 지우지 않아요. 대상 계정이 삭제돼도 이메일과 함께 남아요</p>`;
    icons();
  }

  // ---------- VOC (의견·문제 신고) ----------
  async function adminVOC(body) {
    const f = adminState.voc;
    const [items, sum] = await Promise.all([
      Store.adminFeedback({ state: f.state, ...(f.kind && { kind: f.kind }), ...(f.q && { q: f.q }), ...(f.user_id && { user_id: f.user_id }) }),
      Store.adminGet("/feedback/summary"),
    ]);
    if (!body.isConnected) return;
    const s = sum.by_status;
    body.innerHTML = `
      <div class="kpis">
        ${kpi("접수", num(s.open), "아직 확인하지 않은 것", s.open ? "warn" : "")}
        ${kpi("확인 중", num(s.reviewing))}
        ${kpi("해결", num(s.resolved))}
        <div class="kpi"><span class="k">처리할 것 · 종류별</span><div class="kind-list">${Object.entries(sum.open_by_kind).filter(([, n]) => n).map(([k, n]) => `<span>${FEEDBACK_KINDS[k]} <b>${n}</b></span>`).join("") || "<span>없음</span>"}</div></div>
      </div>
      <div class="filters">
        <label class="search-box"><i data-lucide="search"></i><input id="voc-q" placeholder="내용, 이름, 이메일" value="${esc(f.q)}" /></label>
        <div class="seg small">${[["open", "처리할 것"], ["resolved", "해결됨"], ["all", "전체"]].map(([k, t]) => `<button data-afilter="${k}" class="${f.state === k ? "on" : ""}">${t}</button>`).join("")}</div>
        <select id="voc-kind" class="sel"><option value="">모든 종류</option>${Object.entries(FEEDBACK_KINDS).map(([k, t]) => `<option value="${k}" ${f.kind === k ? "selected" : ""}>${t}</option>`).join("")}</select>
        ${f.user_id ? '<button class="tag on" data-voc-clear-user>한 회원의 문의만 · 해제 ✕</button>' : ""}
      </div>
      <details class="panel announce">
        <summary><i data-lucide="megaphone"></i>모든 사용자에게 공지 보내기</summary>
        <div class="field"><label for="an-title">제목</label><input id="an-title" maxlength="120" placeholder="예: 11월 5일 밤 10시 점검 안내" /></div>
        <div class="field"><label for="an-body">내용 <small>· 선택</small></label><textarea id="an-body" rows="3" maxlength="2000"></textarea></div>
        <div class="field"><label for="an-link">누르면 갈 화면 <small>· 선택 (예: #/library)</small></label><input id="an-link" maxlength="200" /></div>
        <div class="fb-actions"><button class="btn-primary" data-announce>공지 보내기</button></div>
      </details>
      <div id="admin-list">${items.length ? items.map((fb) => `
        <section class="panel fb-item" data-fb="${fb.id}">
          <div class="fb-meta"><span class="tag on">${FEEDBACK_KINDS[fb.kind]}</span><span class="fb-status ${fb.status}">${FB_STATUS[fb.status]}</span>
            <span>${userLink(fb.user_id, fb.user_name)} · ${esc(fb.user_email)}</span><span>${new Date(fb.created_at).toLocaleString("ko-KR")}</span>
            ${fb.page ? `<span>${esc(fb.page)}</span>` : ""}</div>
          <p class="fb-msg">${esc(fb.message)}</p>
          ${fb.problem_id ? `<div class="fb-problem"><small>${esc(fb.problem_id)}${fb.problem_hidden ? ' · <b class="bad">신고로 숨겨짐</b>' : ""}</small>
            <p data-math>${esc(fb.problem_stem ?? "")}</p>
            ${fb.problem_hidden ? `<button class="btn-ghost" data-frestore="${esc(fb.problem_id)}"><i data-lucide="undo-2"></i>문제가 맞아요, 다시 보이게</button>` : ""}</div>` : ""}
          <textarea rows="2" maxlength="2000" placeholder="답변 (저장하면 '해결'로 바뀌고, 보낸 사람에게 알림으로 전달돼요)">${esc(fb.reply ?? "")}</textarea>
          <div class="fb-actions">
            ${Object.entries(FB_STATUS).filter(([k]) => k !== fb.status).map(([k, t]) => `<button class="btn-ghost" data-fstatus="${k}">${t}(으)로</button>`).join("")}
            <button class="btn-primary" data-freply>답변 저장</button></div>
        </section>`).join("") : '<div class="empty"><i data-lucide="inbox"></i><b>조건에 맞는 문의가 없어요</b></div>'}</div>`;
    icons();
  }

  // ---------- 운영 콘솔: 클릭 · 입력 ----------
  const rerender = (tab, id) => renderAdmin(tab, id);
  let searchTimer;
  function adminChange(e, tab) {
    const t = e.target;
    if (t.id === "lg-method") { adminState.logins.method = t.value; rerender(tab); }
    else if (t.id === "ac-action") { adminState.actions.action = t.value; rerender(tab); }
    else if (t.id === "us-sort") { adminState.users.sort = t.value; adminState.users.offset = 0; rerender(tab); }
    else if (t.id === "voc-kind") { adminState.voc.kind = t.value; rerender(tab); }
  }
  view.addEventListener("input", (e) => {
    const map = { "lg-q": ["logins", "logins"], "us-q": ["users", "users"], "voc-q": ["voc", "voc"], "ac-q": ["actions", "actions"] };
    const hit = map[e.target.id];
    if (!hit) return;
    adminState[hit[0]].q = e.target.value.trim();
    if (hit[0] === "users") adminState.users.offset = 0;
    clearTimeout(searchTimer);
    // 입력이 멈추면 다시 불러오고, 커서는 검색창에 그대로
    searchTimer = setTimeout(async () => {
      const pos = e.target.selectionStart;
      await renderAdmin(hit[1]);
      const input = $(`#${e.target.id}`);
      if (input) { input.focus(); input.setSelectionRange(pos, pos); }
    }, 350);
  });

  async function adminClick(e, tab, id) {
    const el = (sel) => e.target.closest(sel);
    let x;
    if ((x = el("[data-days]"))) { adminState.days = Number(x.dataset.days); return rerender(tab); }
    if ((x = el("[data-revdays]"))) { adminState.revDays = Number(x.dataset.revdays); return rerender(tab); }
    if (el("[data-revtest]")) { adminState.revTest = !adminState.revTest; return rerender(tab); }
    if ((x = el("[data-aidays]"))) { adminState.aiDays = Number(x.dataset.aidays); return rerender(tab); }
    if ((x = el("[data-eval]"))) { location.hash = `#/evals/${x.dataset.eval}`; return; }
    if ((x = el("[data-eval-run]"))) {
      if (!confirm("실제 AI 로 골든셋 평가와 문제 생성 평가를 돌려요. 10분 안팎 걸리고 약 $1~2 의 비용이 들어요. 진행할까요?")) return;
      x.disabled = true;
      try { await Store.adminPost("/evals/run"); toast("평가를 시작했어요. 몇 분 뒤 새로고침해 보세요"); } catch (err) { toast(err.message); }
      return rerender(tab);
    }
    if ((x = el("[data-run]"))) { location.hash = `#/runs/${x.dataset.run}`; return; }
    if ((x = el("[data-rkind]"))) { adminState.runs.kind = adminState.runs.kind === x.dataset.rkind ? "" : x.dataset.rkind; return rerender(tab); }
    if ((x = el("[data-rstatus]"))) { adminState.runs.status = adminState.runs.status === x.dataset.rstatus ? "" : x.dataset.rstatus; return rerender(tab); }
    if ((x = el("[data-igrade]"))) { adminState.items.grade = adminState.items.grade === x.dataset.igrade ? "" : x.dataset.igrade; return rerender(tab); }
    if ((x = el("[data-iflag]"))) { adminState.items.flag = adminState.items.flag === x.dataset.iflag ? "" : x.dataset.iflag; return rerender(tab); }
    if ((x = el("[data-irefresh]"))) {
      x.disabled = true;
      try { const r = await Store.adminPost("/item-stats/refresh"); toast(`${num(r.problems)}문제의 성적을 새로 매겼어요`); } catch (err) { toast(err.message); }
      return rerender(tab);
    }
    if ((x = el("[data-lresult]"))) { adminState.logins.result = x.dataset.lresult; return rerender(tab); }
    if (el("[data-lmore]")) return adminLogins($("#admin-body"), true);
    if ((x = el("[data-ustate]"))) { adminState.users.state = x.dataset.ustate; adminState.users.offset = 0; return rerender(tab); }
    if ((x = el("[data-users-state]"))) { adminState.users.state = x.dataset.usersState; adminState.users.offset = 0; return; }
    if ((x = el("[data-ucsv]"))) {
      const f = adminState.users;
      x.disabled = true;
      try {
        const name = await Store.adminDownload("/users.csv", { state: f.state, sort: f.sort, ...(f.q && { q: f.q }) });
        toast(`${name} 파일을 내려받았어요`);
      } catch (err) { toast(err.message); }
      x.disabled = false;
      return;
    }
    if ((x = el("[data-upage]"))) { adminState.users.offset = Math.max(0, adminState.users.offset + Number(x.dataset.upage) * 50); return rerender(tab); }
    if ((x = el("[data-voc-user]"))) { Object.assign(adminState.voc, { user_id: x.dataset.vocUser, state: "all", kind: "", q: "" }); return; }
    if (el("[data-voc-clear-user]")) { adminState.voc.user_id = ""; return rerender(tab); }
    if ((x = el("tr.row-link")) && !el("a")) { location.hash = x.dataset.href; return; }
    if ((x = el("[data-afilter]"))) { adminState.voc.state = x.dataset.afilter; return rerender(tab); }

    // 계정 관리
    const u = adminUserCache?.user;
    if (el("[data-ulogout]")) {
      const u = adminUserCache.user;
      return formModal({
        title: `${u.name} 님을 강제 로그아웃할까요?`, submit: "로그아웃시키기", danger: true,
        body: `<p class="modal-text">이 회원이 쓰던 <b>모든 PC·폰의 로그인이 끊겨요</b>. 화면을 열어 둔 곳은 1분 안에 "운영자가 로그아웃시켰어요" 안내가 뜨고, 다시 로그인하면 계속 쓸 수 있어요.
          도용이 의심되면 이용 정지와 함께 쓰세요.</p>
          <div class="field"><label for="lo-reason">사유 (관리 기록에 남아요, 선택)</label><input id="lo-reason" maxlength="500" placeholder="예: 도용 의심 · 본인 요청" /></div>`,
        onSubmit: (form) => {
          Store.adminPost(`/users/${u.id}/logout`, { reason: $("#lo-reason", form).value.trim() || null })
            .then(() => { toast("강제 로그아웃했어요"); rerender(tab, id); }).catch((err) => toast(err.message));
        },
      });
    }
    if (el("[data-suspend]") && u) {
      return formModal({
        title: `${u.name}님의 이용을 정지할까요?`, submit: "이용 정지", danger: true,
        body: `<p class="modal-text">정지하면 바로 로그아웃되고 다시 로그인할 수 없어요. 학습 기록은 그대로 남고, 언제든 해제할 수 있어요.</p>
          <div class="field"><label for="sus-reason">정지 이유 <small>· 운영 기록용, 사용자에게는 보이지 않아요</small></label><textarea id="sus-reason" rows="2" maxlength="500" placeholder="예: 다른 사람의 기출 무단 업로드 반복"></textarea></div>`,
        onSubmit: (form) => {
          const reason = $("#sus-reason", form).value.trim();
          if (reason.length < 2) return invalid($("#sus-reason", form), "이유를 2자 이상 적어 주세요");
          Store.adminPost(`/users/${u.id}/suspend`, { reason }).then(() => { toast("이용을 정지했어요"); rerender(tab, id); }).catch((err) => toast(err.message));
        },
      });
    }
    if (el("[data-unsuspend]") && u) {
      try { await Store.adminPost(`/users/${u.id}/unsuspend`); toast("정지를 해제했어요"); return rerender(tab, id); } catch (err) { return toast(err.message); }
    }
    if (el("[data-udelete]") && u) {
      return formModal({
        title: "계정을 삭제할까요?", submit: "영구 삭제", danger: true,
        body: `<p class="modal-text"><b>${esc(u.name)}</b>님의 계정과 학습 기록, 올린 자료, 프로필 사진이 모두 지워지고 되돌릴 수 없어요. 확인을 위해 이메일 <b>${esc(u.email)}</b>을 입력해 주세요.</p>
          <div class="field"><label for="del-email">이메일</label><input id="del-email" autocomplete="off" placeholder="${esc(u.email)}" /></div>`,
        onSubmit: (form) => {
          const input = $("#del-email", form);
          if (input.value.trim().toLowerCase() !== u.email) return invalid(input, "이메일이 맞지 않아요");
          Store.adminDelete(`/users/${u.id}`, { confirm_email: input.value.trim() }).then(() => { toast("계정을 삭제했어요"); location.hash = "#/users"; }).catch((err) => toast(err.message));
        },
      });
    }

    // VOC: 공지 · 상태 · 답변 · 문제 복구
    if (el("[data-announce]")) {
      const title = $("#an-title").value.trim();
      if (title.length < 2) return invalid($("#an-title"), "제목을 적어 주세요");
      try {
        const r = await Store.adminAnnounce({ title, body: $("#an-body").value.trim() || null, link: $("#an-link").value.trim() || null });
        toast(`${r.sent}명에게 공지를 보냈어요`);
        ["#an-title", "#an-body", "#an-link"].forEach((s) => ($(s).value = ""));
      } catch (err) { toast(err.message); }
      return;
    }
    const card = el("[data-fb]");
    if (!card) return;
    const fid = card.dataset.fb;
    try {
      if ((x = el("[data-fstatus]"))) { await Store.adminUpdateFeedback(fid, { status: x.dataset.fstatus }); toast(`'${FB_STATUS[x.dataset.fstatus]}'(으)로 바꿨어요`); return rerender(tab); }
      if (el("[data-freply]")) {
        const reply = $("textarea", card).value.trim();
        if (!reply) return toast("답변을 적어 주세요");
        await Store.adminUpdateFeedback(fid, { reply, status: "resolved" });
        toast("답변을 저장하고 해결로 바꿨어요");
        return rerender(tab);
      }
      if ((x = el("[data-frestore]"))) { await Store.adminRestoreProblem(x.dataset.frestore); toast("문제를 다시 보이게 했어요"); return rerender(tab); }
    } catch (err) { toast(err.message); }
  }


  // ================= 입장: 로그인 · 권한 확인 =================
  const gate = $("#gate"), shell = $("#shell");
  // 같은 계정으로 다른 PC에서 로그인 → 팝업 후 로그아웃
  let replacedShown = false;
  function sessionReplaced() {
    if (replacedShown) return;
    replacedShown = true;
    clearInterval(liveTimer);
    try { localStorage.removeItem(TOKEN_KEY); } catch { /* 무시 */ }
    closeOverlays();
    const bd = document.createElement("div");
    bd.className = "backdrop";
    bd.innerHTML = `
      <div class="modal" role="alertdialog" aria-modal="true" style="max-width:380px;text-align:center">
        <h2 style="font-size:17px;font-weight:700;margin-bottom:8px">다른 PC에서 접속 중입니다.</h2>
        <p style="font-size:14px;color:var(--ink-2);line-height:1.6">자동으로 로그아웃 됩니다.</p>
        <div class="modal-foot" style="justify-content:center"><button type="button" class="btn-primary" data-so-ok>확인</button></div>
      </div>`;
    document.body.append(bd);
    const out = () => { bd.remove(); showGate("login", "다른 PC에서 접속해서 로그아웃됐어요. 다시 로그인하면 다른 PC가 로그아웃돼요"); };
    $("[data-so-ok]", bd).onclick = out;
    setTimeout(out, 5000);
  }

  function showGate(mode, msg = "") {
    shell.hidden = true;
    gate.hidden = false;
    gate.dataset.mode = mode;
    $("#gate-msg").textContent = msg;
    $("#gate-msg").hidden = !msg;
    if (mode === "login") try { localStorage.removeItem(TOKEN_KEY); } catch { /* 무시 */ }
    icons();
  }

  async function enter() {
    if (!getToken()) return showGate("login");
    let me;
    try {
      me = await api("/me");
      await api("/admin/feedback/summary"); // 운영자가 아니면 404 → '권한 없음'
    } catch { return; }
    $("#me-name").textContent = me.name;
    $("#me-email").textContent = me.email;
    gate.hidden = true;
    shell.hidden = false;
    route();
  }

  function route() {
    if (shell.hidden) return;
    const [tab, id] = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
    closeOverlays();
    view.onclick = null;
    view.onchange = null;
    renderAdmin(tab ?? "overview", id ?? null);
    $("#shell").classList.remove("nav-open");
    window.scrollTo(0, 0);
  }
  window.addEventListener("hashchange", route);

  // 이메일 로그인 (관리자 페이지 안에서 바로)
  $("#gate-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = $("#g-email").value.trim(), password = $("#g-pw").value;
    if (!email || !password) return showGate("login", "이메일과 비밀번호를 입력해 주세요");
    const btn = $("#gate-form button[type=submit]");
    btn.disabled = true;
    try {
      const res = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "로그인하지 못했어요");
      localStorage.setItem(TOKEN_KEY, data.access_token);
      localStorage.setItem("eureka.user", JSON.stringify(data.user));
      await enter();
    } catch (err) {
      showGate("login", err.message);
    } finally { btn.disabled = false; }
  });
  // 간편 로그인: 로그인 화면을 거쳐 다시 여기로 돌아온다 (login.html 이 eureka.next 를 보고 /admin 으로)
  $$("[data-provider]").forEach((b) => b.addEventListener("click", () => {
    try { localStorage.setItem("eureka.next", "/admin"); } catch { /* 무시 */ }
    location.href = `/api/auth/${b.dataset.provider}/start`;
  }));
  $$("[data-logout]").forEach((b) => b.addEventListener("click", () => {
    try { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem("eureka.user"); } catch { /* 무시 */ }
    showGate("login", "로그아웃했어요");
  }));
  $("#nav-toggle").addEventListener("click", () => $("#shell").classList.toggle("nav-open"));

  enter();
})();

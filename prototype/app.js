// Eureka 프로토타입 앱 — 해시 라우팅, 사이드바, 메뉴별 화면(새 학습·대화·프로젝트·오답노트·라이브러리),
// 모달·메뉴·⌘K 검색. 데이터는 store.js 의 Store, 개념 트리는 concepts.js 의 CONCEPTS 를 쓴다.
(() => {
  // ================= 유틸 =================
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s = "") => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  // 아이콘과 수식을 함께 그린다. 수식은 data-math 가 붙은 요소의 $…$ 만 렌더링 (대화 글의 '$5' 같은 건 건드리지 않음)
  const MATH_OPTS = { delimiters: [{ left: "$$", right: "$$", display: true }, { left: "$", right: "$", display: false }], throwOnError: false };
  const icons = () => {
    lucide.createIcons();
    if (window.renderMathInElement) $$("[data-math]").forEach((el) => renderMathInElement(el, MATH_OPTS));
    mountWorkCanvases();
    mountGraphs();
  };
  // 서술형 풀이 칸 상태 — 문제 id → { open, tab, text, image, drawn, eraser, review, busy } (다시 그려도 유지)
  const workState = {};
  // 검색 결과처럼 짧은 글로 보여 줄 때: LaTeX 명령을 걷어 낸 평문
  const plainMath = (s = "") => s.replace(/\$+([^$]*)\$+/g, (_, m) => m
    .replace(/\\(displaystyle|mathrm|dfrac|frac|left|right|text)\b/g, " ").replace(/\\[,;!]/g, " ")
    .replace(/\\int/g, "∫").replace(/\\log/g, "log").replace(/\\times/g, "×").replace(/\\cap/g, "∩").replace(/\\mid/g, "|")
    .replace(/[{}\\]/g, "").replace(/\s+/g, " ").trim());
  const DAY = 864e5;
  // 정답처럼 $…$ 없이 LaTeX 만 담긴 짧은 글: 수식 기호가 있으면 $…$ 로 감싸 KaTeX 가 그리게 한다 (한글이 섞이면 그대로)
  const texAns = (a) => {
    const t = String(a).trim();
    return !t.includes("$") && !/[가-힣]/.test(t) && /[\\^_{}=]/.test(t) ? `$${t}$` : t;
  };

  // 분야(domain) 색·이름 — 공식 5개 + 사용자 코스 분야 (없는 키는 회색, 이름은 코스의 분야 이름)
  const TEMPLATE_DOMAINS = ["math", "physics", "chemistry", "biology", "earth_science"];
  const EXTRA_COLOR = { english: "#0ea5e9", korean: "#e11d48", social: "#d97706", history: "#a16207", economics: "#059669",
    accounting: "#4f46e5", law: "#475569", computer: "#0d9488", medicine: "#dc2626", language: "#7c3aed", general: "#64748b" };
  const COLOR = new Proxy({ math: "var(--math)", physics: "var(--physics)", chemistry: "var(--chemistry)", biology: "var(--biology)", earth_science: "var(--earth)" },
    { get: (t, k) => t[k] ?? EXTRA_COLOR[k] ?? EXTRA_COLOR.general });
  const DOMAIN_NAME = new Proxy({ math: "수학", physics: "물리", chemistry: "화학", biology: "생명과학", earth_science: "지구과학" },
    { get: (t, k) => t[k] ?? COURSES.find((c) => c.domain === k)?.category ?? "기타" });

  // 코스와 개념 트리 — 서버 모드는 /api/sync 로 받은 것 (공식 코스 + 내 코스), 로컬 모드는 concepts.js
  let CONCEPTS = [], COURSES = [], SUBJECTS = [], DOMAINS = [...TEMPLATE_DOMAINS];
  let conceptMap = {}, kidsMap = {}, courseMap = {};
  const domainOrder = (d) => (TEMPLATE_DOMAINS.includes(d) ? TEMPLATE_DOMAINS.indexOf(d) : 99);
  function loadConcepts() {
    CONCEPTS = Store.state?.concepts ?? window.CONCEPTS ?? [];
    COURSES = Store.state?.courses ?? window.COURSES ?? [];
    conceptMap = Object.fromEntries(CONCEPTS.map((c) => [c.id, c]));
    courseMap = Object.fromEntries(COURSES.map((c) => [c.id, c]));
    kidsMap = {};
    for (const c of CONCEPTS) if (c.parent_id) (kidsMap[c.parent_id] ??= []).push(c);
    for (const list of Object.values(kidsMap)) list.sort((a, b) => (a.position ?? 0) - (b.position ?? 0));
    const official = (c) => (courseMap[c.id]?.source === "user" ? 1 : 0);
    // 공식 코스는 교육과정 순서 (concepts.js 의 YAML 순서), 사용자 코스는 그 뒤
    const yamlOrder = Object.fromEntries((window.COURSES ?? []).map((c, i) => [c.id, i]));
    SUBJECTS = CONCEPTS.filter((c) => c.level === "subject")
      .sort((a, b) => domainOrder(a.domain) - domainOrder(b.domain) || official(a) - official(b) || (yamlOrder[a.id] ?? 999) - (yamlOrder[b.id] ?? 999));
    DOMAINS = [...new Set(SUBJECTS.map((s) => s.domain))].sort((a, b) => domainOrder(a) - domainOrder(b));
  }
  const concept = (id) => conceptMap[id];
  const childrenOf = (id) => kidsMap[id] ?? [];
  const pathOf = (id) => { const out = []; for (let c = concept(id); c; c = concept(c.parent_id)) out.unshift(c); return out; };
  const subjectOf = (id) => pathOf(id)[0];
  const projectDomain = (p) => concept(p?.subjectId)?.domain;
  // 내가 공부하는 분야 — 프로젝트 코스와 풀어 본 문제. 없으면 공식 코스 분야
  function myDomains() {
    const ds = new Set([...Store.state.projects.map((p) => projectDomain(p)), ...Store.state.attempts.map((a) => Store.problem(a.problemId)?.domain)].filter(Boolean));
    return ds.size ? [...ds].sort((a, b) => domainOrder(a) - domainOrder(b)) : TEMPLATE_DOMAINS;
  }

  const startOfToday = () => new Date(new Date().toDateString()).getTime();
  const daysLeft = (examDate) => (examDate ? Math.round((new Date(`${examDate}T00:00:00`) - startOfToday()) / DAY) : null);
  const ddayLabel = (n) => (n == null ? "" : n > 0 ? `D-${n}` : n === 0 ? "D-DAY" : "종료");
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

  function toast(msg) {
    $(".toast")?.remove();
    const t = document.createElement("div");
    t.className = "toast";
    t.textContent = msg;
    document.body.append(t);
    setTimeout(() => t.remove(), 2200);
  }

  const view = $("#view");
  const home = $("#home");
  const contentEl = $(".content");

  // 스크롤바는 스크롤하는 동안만 보이고, 멈추고 0.8초 뒤 사라진다 (CSS .content.is-scrolling)
  {
    let hideTimer;
    contentEl.addEventListener("scroll", () => {
      contentEl.classList.add("is-scrolling");
      clearTimeout(hideTimer);
      hideTimer = setTimeout(() => contentEl.classList.remove("is-scrolling"), 800);
    }, { passive: true });
  }


  // ================= 프로필 사진: 사진 · Eureka 캐릭터 · 이름 첫 글자 =================
  // 캐릭터는 브랜드 색 배경 + 동그란 얼굴(눈·입 조합) + 소품 배지(앱 아이콘과 같은 lucide 아이콘)로 그린다
  const PRESETS = {
    spark: { name: "반짝", a: "#ff7a59", b: "#ffd36e", icon: "sparkles", eyes: "happy", mouth: "grin" },
    cap: { name: "합격", a: "#4f6bff", b: "#9db0ff", icon: "graduation-cap", eyes: "dot", mouth: "grin" },
    glasses: { name: "꼼꼼", a: "#8b5cf6", b: "#cbb4ff", icon: "glasses", eyes: "glasses", mouth: "smile" },
    flask: { name: "실험", a: "#14b8a6", b: "#86ead9", icon: "flask-conical", eyes: "wink", mouth: "smile" },
    atom: { name: "원자", a: "#0ea5e9", b: "#9fdcff", icon: "atom", eyes: "dot", mouth: "o" },
    bulb: { name: "유레카", a: "#f59e0b", b: "#ffe28a", icon: "lightbulb", eyes: "happy", mouth: "o" },
    book: { name: "독서", a: "#22c55e", b: "#a7ecbe", icon: "book-open", eyes: "dot", mouth: "smile" },
    pencil: { name: "필기", a: "#ec4899", b: "#ffb6da", icon: "pencil", eyes: "wink", mouth: "grin" },
    star: { name: "별", a: "#eab308", b: "#fff0a0", icon: "star", eyes: "happy", mouth: "smile" },
    rocket: { name: "도약", a: "#6366f1", b: "#c9cbff", icon: "rocket", eyes: "dot", mouth: "o" },
    headphones: { name: "집중", a: "#06b6d4", b: "#a5eefa", icon: "headphones", eyes: "happy", mouth: "smile" },
    crown: { name: "1등", a: "#f43f5e", b: "#ffb8c4", icon: "crown", eyes: "dot", mouth: "grin" },
  };
  const INK = "#1f2937";
  const EYES = {
    dot: `<circle cx="25" cy="34" r="2.7" fill="${INK}"/><circle cx="39" cy="34" r="2.7" fill="${INK}"/>`,
    happy: `<path d="M21.5 35 q3.5 -4 7 0 M35.5 35 q3.5 -4 7 0" stroke="${INK}" stroke-width="2.2" fill="none" stroke-linecap="round"/>`,
    wink: `<circle cx="25" cy="34" r="2.7" fill="${INK}"/><path d="M35.5 35 q3.5 -4 7 0" stroke="${INK}" stroke-width="2.2" fill="none" stroke-linecap="round"/>`,
    glasses: `<circle cx="25" cy="34" r="5.2" fill="#fff" stroke="${INK}" stroke-width="1.8"/><circle cx="39" cy="34" r="5.2" fill="#fff" stroke="${INK}" stroke-width="1.8"/>
      <path d="M30.2 34 h3.6" stroke="${INK}" stroke-width="1.8"/><circle cx="25" cy="34.5" r="1.8" fill="${INK}"/><circle cx="39" cy="34.5" r="1.8" fill="${INK}"/>`,
  };
  const MOUTH = {
    smile: `<path d="M27.5 41.5 q4.5 4.5 9 0" stroke="${INK}" stroke-width="2.2" fill="none" stroke-linecap="round"/>`,
    grin: `<path d="M27 40.5 q5 7 10 0 z" fill="${INK}"/><path d="M29.5 43.6 q2.5 1.6 5 0" stroke="#ff8fa8" stroke-width="1.6" fill="none" stroke-linecap="round"/>`,
    o: `<ellipse cx="32" cy="43" rx="2.4" ry="2.8" fill="${INK}"/>`,
  };
  const pascal = (k) => k.replace(/(^|-)(\w)/g, (_, __, c) => c.toUpperCase());
  function iconPaths(name) {
    const node = lucide.icons?.[pascal(name)];
    const children = Array.isArray(node?.[2]) ? node[2] : Array.isArray(node) ? node : [];
    return children.map(([tag, attrs]) => `<${tag} ${Object.entries(attrs).map(([k, v]) => `${k}="${v}"`).join(" ")}/>`).join("");
  }
  function presetSVG(key) {
    const p = PRESETS[key] ?? PRESETS.spark;
    return `<svg viewBox="0 0 64 64" class="avatar-svg" aria-hidden="true">
      <defs><linearGradient id="avg-${key}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${p.b}"/><stop offset="1" stop-color="${p.a}"/></linearGradient></defs>
      <circle cx="32" cy="32" r="32" fill="url(#avg-${key})"/>
      <ellipse cx="32" cy="38" rx="20.5" ry="18.5" fill="#fff"/>
      <ellipse cx="21" cy="41" rx="3.2" ry="2" fill="#ffadc2" opacity=".75"/><ellipse cx="43" cy="41" rx="3.2" ry="2" fill="#ffadc2" opacity=".75"/>
      ${EYES[p.eyes]}${MOUTH[p.mouth]}
      <circle cx="49" cy="15" r="11" fill="#fff" opacity=".96"/>
      <g transform="translate(42 8) scale(.58)" fill="none" stroke="${p.a}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">${iconPaths(p.icon)}</g>
    </svg>`;
  }
  // 사용자 프로필 사진 마크업 (크기는 CSS 의 .avatar 가 정한다)
  function avatarInner(user) {
    if (user.avatarType === "photo" && user.avatarUrl) return `<img src="${esc(user.avatarUrl)}" alt="" />`;
    if (user.avatarType === "preset") return presetSVG(user.avatarPreset);
    return esc((user.name || "?").slice(0, 1));
  }

  // ================= 라우팅 =================
  // #/  #/?project=id  #/chat/id  #/project/id  #/notes  #/library[/cards|/saved|/concept/id]
  function route() {
    const [path, qs = ""] = location.hash.replace(/^#\/?/, "").split("?");
    return { parts: path.split("/").filter(Boolean), params: new URLSearchParams(qs) };
  }
  const go = (path) => { location.hash = path; };

  function navKey() {
    const [page, id] = route().parts;
    if (!page) return "home";
    if (page === "chat" || page === "project") return `${page}:${id}`;
    return page;
  }

  // 홈으로 돌아올 때마다 제목·입력창·카드가 다시 아래에서 위로 떠오르게
  let revealer = null;
  function replayReveal() {
    if (!revealer) return; // 첫 화면은 아래 초기화에서 처리
    const els = $$("#home .reveal");
    els.forEach((el) => { el.style.transition = "none"; el.classList.remove("in"); revealer.unobserve(el); });
    void home.offsetHeight; // 처음 위치로 바로 되돌린 뒤
    els.forEach((el) => (el.style.transition = ""));
    requestAnimationFrame(() => els.forEach((el) => revealer.observe(el))); // 다시 재생
  }

  function render() {
    if (!Store.state) return; // 서버 데이터를 받기 전
    closeOverlays();
    const { parts, params } = route();
    const [page, a, b] = parts;
    home.hidden = !!page;
    view.hidden = !page;
    view.onclick = null;
    view.onchange = null;
    view.onkeydown = null;
    $(".wrap").classList.toggle("wide", page === "project");
    if (!page) { renderHome(params); replayReveal(); }
    else if (page === "chat") renderChat(a);
    else if (page === "project") renderProject(a, params);
    else if (page === "notes") renderNotes();
    else if (page === "library") renderLibrary(a ?? "concepts", b);
    else if (page === "settings") renderSettings(params);
    else if (page === "answer-key") renderAnswerKey(a);
    else if (page === "exam") renderExamPaper(a, params);
    else if (page === "exam-record") renderExamRecord(a);
    else if (page === "admin") { location.href = "/admin"; return; }
    else return go("/");
    renderSidebar();
    if (page !== "chat") contentEl.scrollTop = 0;
    icons();
    $("#app").classList.remove("mobile-open");
  }
  window.addEventListener("hashchange", render);
  Store.subscribe(() => {
    const [page, id] = route().parts;
    // 새 대화가 서버 id 를 받으면 주소만 바꾼다
    if (page === "chat" && !Store.session(id) && Store.resolveId(id) !== id) return location.replace(`#/chat/${Store.resolveId(id)}`);
    // 보고 있던 대화·프로젝트가 삭제되면 홈으로
    if ((page === "chat" && !Store.session(id)) || (page === "project" && !Store.project(id))) return go("/");
    renderSidebar();
  });
  Store.onError((msg) => toast(`저장하지 못했어요: ${msg}`));

  // ================= 사이드바 =================
  function renderSidebar() {
    const st = Store.state;
    const key = navKey();
    $$(".sidebar [data-key]").forEach((el) => el.classList.toggle("active", el.dataset.key === key));

    const open = Store.openNotes().length;
    const badge = $("#notes-badge");
    badge.textContent = open;
    badge.hidden = !open;

    const projects = [...st.projects].sort((a, b) => {
      const ended = (p) => (daysLeft(p.examDate) ?? 1) < 0;
      return (b.pinned - a.pinned) || (ended(a) - ended(b)) || (a.createdAt - b.createdAt);
    });
    $("#projects").innerHTML = projects.length ? projects.map((p) => {
      const n = daysLeft(p.examDate);
      return `
        <div class="nav-row">
          <a class="nav-item" href="#/project/${p.id}" data-key="project:${p.id}" ${key === `project:${p.id}` ? 'aria-current="page"' : ""}>
            <i data-lucide="folder" style="color:${COLOR[projectDomain(p)]}"></i><span class="label">${esc(p.name)}</span>
            ${p.pinned ? '<i data-lucide="pin" class="pin"></i>' : ""}
            ${n != null ? `<span class="dday ${n >= 0 && n <= 14 ? "soon" : ""}">${ddayLabel(n)}</span>` : ""}
          </a>
          <button class="more" data-menu="project" data-id="${p.id}" aria-label="프로젝트 메뉴"><i data-lucide="ellipsis"></i></button>
        </div>`;
    }).join("") : '<p class="nav-empty">＋ 를 눌러 첫 프로젝트를 만들어 보세요</p>';

    // 최근 대화: 오늘 / 어제 / 지난 7일 / 이전
    const groups = { 오늘: [], 어제: [], "지난 7일": [], 이전: [] };
    const today = startOfToday();
    [...st.sessions].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, 30).forEach((s) => {
      const g = s.updatedAt >= today ? "오늘" : s.updatedAt >= today - DAY ? "어제" : s.updatedAt >= today - 7 * DAY ? "지난 7일" : "이전";
      groups[g].push(s);
    });
    const chats = Object.entries(groups).filter(([, list]) => list.length).map(([title, list]) => `
      <div class="group-title">${title}</div>
      ${list.map((s) => {
        const p = s.projectId && Store.project(s.projectId);
        return `
          <div class="nav-row">
            <a class="nav-item chat" href="#/chat/${s.id}" data-key="chat:${s.id}">
              ${p ? `<span class="proj-dot" style="--c:${COLOR[projectDomain(p)]}" title="${esc(p.name)}"></span>` : ""}
              <span class="label">${esc(s.title)}</span>
            </a>
            <button class="more" data-menu="chat" data-id="${s.id}" aria-label="대화 메뉴"><i data-lucide="ellipsis"></i></button>
          </div>`;
      }).join("")}`).join("");
    $("#chats").innerHTML = chats || '<p class="nav-empty">아직 대화가 없어요</p>';
    $$("#projects [data-key], #chats [data-key]").forEach((el) => el.classList.toggle("active", el.dataset.key === key));

    $("#profile-name").textContent = st.user.name;
    const av = $("#profile-avatar");
    av.innerHTML = avatarInner(st.user);
    av.classList.toggle("has-image", st.user.avatarType !== "initial" && !!st.user.avatarType);
    const todayN = Store.todayCount(), streak = Store.streak();
    $("#profile-sub").textContent = !todayN && !streak ? "오늘 첫 문제를 풀어 보세요"
      : `오늘 ${todayN} / ${st.user.dailyGoal}문제${streak ? ` · ${streak}일 연속` : ""}`;
    icons();
  }

  $(".sidebar").addEventListener("click", (e) => {
    const more = e.target.closest(".more");
    if (more) {
      e.preventDefault();
      more.classList.add("open");
      const close = () => more.classList.remove("open");
      if (more.dataset.menu === "project") projectMenu(more, more.dataset.id, close);
      else chatMenu(more, more.dataset.id, close);
    }
  });
  $("#new-project").addEventListener("click", () => projectWizard());
  $("#nav-search").addEventListener("click", openPalette);
  $("#profile").addEventListener("click", (e) => profileMenu(e.currentTarget));

  function projectMenu(anchor, id, onClose) {
    const p = Store.project(id);
    openMenu(anchor, [
      { icon: "pencil", label: "프로젝트 수정", run: () => projectModal(p) },
      { icon: p.pinned ? "pin-off" : "pin", label: p.pinned ? "고정 해제" : "맨 위에 고정", run: () => Store.updateProject(id, { pinned: !p.pinned }) },
      "-",
      { icon: "trash-2", label: "삭제", danger: true, run: () => confirmModal({
        title: "프로젝트를 삭제할까요?",
        text: `<b>${esc(p.name)}</b>과 그 안의 대화가 모두 삭제돼요. 풀이 기록과 오답노트는 남아요.`,
        run: () => { Store.deleteProject(id); toast("프로젝트를 삭제했어요"); },
      }) },
    ], onClose);
  }

  function chatMenu(anchor, id, onClose) {
    const s = Store.session(id);
    openMenu(anchor, [
      { icon: "pencil", label: "이름 바꾸기", run: () => renameModal(s) },
      { icon: "folder-input", label: "프로젝트로 옮기기", run: () => moveModal(s) },
      "-",
      { icon: "trash-2", label: "삭제", danger: true, run: () => confirmModal({
        title: "대화를 삭제할까요?",
        text: `<b>${esc(s.title)}</b> 대화가 삭제돼요. 이 대화에서 푼 기록과 오답노트는 남아요.`,
        run: () => { Store.deleteSession(id); toast("대화를 삭제했어요"); },
      }) },
    ], onClose);
  }

  function profileMenu(anchor) {
    openMenu(anchor, [
      { label: Store.state.user.name, header: true },
      { icon: "user-round-cog", label: "계정 설정", run: () => go("/settings") },
      Store.state.user.isAdmin && { icon: "shield-check", label: "관리자 페이지 열기", run: () => window.open("/admin", "_blank", "noopener") },
      Store.mode === "local" && { icon: "rotate-ccw", label: "데모 데이터 초기화", run: () => confirmModal({
        title: "데모 데이터를 초기화할까요?", text: "직접 만든 프로젝트, 대화, 풀이 기록이 모두 지워지고 처음 샘플 데이터로 돌아가요.", action: "초기화",
        run: () => { Store.reset(); go("/"); render(); toast("처음 상태로 되돌렸어요"); },
      }) },
      "-",
      Store.mode === "api" && { label: Store.state.user.email ?? "", header: true },
      { icon: "log-out", label: "로그아웃", run: () => {
        try { localStorage.removeItem("eureka.token"); localStorage.removeItem("eureka.user"); } catch { /* 저장소 없음 */ }
        location.href = "login.html";
      } },
    ]);
  }

  // ================= 홈 (새 학습) =================
  let homeProjectId = null;
  const prompt = $("#prompt"), send = $("#send");

  function renderHome(params) {
    if (params.has("project")) homeProjectId = Store.project(params.get("project")) ? params.get("project") : null;
    if (homeProjectId && !Store.project(homeProjectId)) homeProjectId = null;
    renderChip();

    const st = Store.state;
    const name = st.user?.name;
    $("#greeting").textContent = name ? `${name}님, 오늘은 무엇을 공부할까요?` : "오늘은 무엇을 공부할까요?";

    renderOnboard();
    renderGoal();
    renderTodo();
    renderExam();
    renderActivity();

    const recent = [...st.sessions].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, 4);
    $("#cards-recent").innerHTML = recent.map((s) => {
      const p = s.projectId && Store.project(s.projectId);
      const ids = s.messages.flatMap((m) => m.problemIds ?? []);
      const tried = ids.map((pid) => Store.lastAttempt(s.id, pid)).filter(Boolean);
      const ok = tried.filter((a) => a.correct).length;
      return card({
        href: `#/chat/${s.id}`, c: p ? COLOR[projectDomain(p)] : "var(--ink-3)", kind: p ? p.name : "대화", title: s.title,
        meta: `${ids.length ? `${ok} / ${ids.length} 정답 · ` : ""}${relTime(s.updatedAt)}`, pct: ids.length ? (ok / ids.length) * 100 : 0,
      });
    }).join("") || '<p class="empty">아직 학습 기록이 없어요. 위 입력창에 풀고 싶은 문제를 적어 보세요</p>';

    $("#subjects").innerHTML = myDomains().map((d) => {
      const acc = Store.accuracy({ domain: d });
      const w = Store.conceptStats({ domain: d })[0];
      return `
        <a class="card subject" href="#/notes?domain=${d}" style="--c:${COLOR[d]}; text-decoration:none; color:inherit">
          <span class="kind"><span class="sw"></span>${DOMAIN_NAME[d]}</span>
          <div class="pct">${acc == null ? "–" : Math.round(acc * 100)}<small>% 정답률</small></div>
          <div class="bar"><i style="width:${acc == null ? 0 : acc * 100}%"></i></div>
          <div class="weak">${w ? `약점 <b>${esc(concept(w.conceptId)?.name ?? "")}</b>` : "아직 풀이 기록이 없어요"}</div>
        </a>`;
    }).join("");
  }

  const dayKey = (t) => new Date(new Date(t).toDateString()).getTime();

  // ---------- 첫 사용 안내: 목표 정하기 → 첫 문제 → 기출 올리기 (다 하거나 닫으면 사라짐) ----------
  const ONBOARD_KEY = "eureka.onboard.closed";
  function renderOnboard() {
    const el = $("#onboard");
    const st = Store.state;
    let closed = false;
    try { closed = localStorage.getItem(ONBOARD_KEY) === "1"; } catch { /* 저장소 없음 */ }
    const steps = [
      { done: st.projects.length > 0, icon: "target", title: "목표 정하기", text: "준비하는 시험과 날짜를 적으면 범위와 D-day를 챙겨 드려요", action: "목표 만들기", act: "wizard" },
      { done: st.attempts.length > 0, icon: "pencil-line", title: "첫 문제 풀어 보기", text: "입력창에 풀고 싶은 문제를 말해 보세요. 마이크로 말해도 돼요", action: "예시로 시작", act: "try" },
      { done: false, icon: "file-up", title: "기출 올리기", text: "가진 기출을 올리면 같은 스타일로 문제를 만들고 정답지도 만들어요", action: "기출 올리러 가기", act: "upload" },
    ];
    if (closed || (steps[0].done && steps[1].done)) { el.hidden = true; return; }
    el.hidden = false;
    el.innerHTML = `
      <div class="onboard-head"><div><h2>Eureka에 오신 걸 환영해요</h2><p>세 단계면 준비가 끝나요</p></div>
        <div class="ob-goal"><span>하루 목표</span><div class="seg small">${[5, 10, 20, 30].map((g) => `<button data-goal="${g}" class="${st.user.dailyGoal === g ? "on" : ""}">${g}문제</button>`).join("")}</div></div>
        <button class="icon-btn" data-onboard-close aria-label="안내 닫기" title="다음에 볼게요"><i data-lucide="x"></i></button></div>
      <ol class="onboard-steps">${steps.map((s, i) => `
        <li class="${s.done ? "done" : ""}">
          <span class="ob-ic">${s.done ? '<i data-lucide="check"></i>' : `<i data-lucide="${s.icon}"></i>`}</span>
          <div><b>${i + 1}. ${s.title}</b><p>${s.text}</p>
            ${s.done ? '<small>완료</small>' : `<button class="btn-ghost" data-onboard="${s.act}">${s.action}</button>`}</div>
        </li>`).join("")}</ol>`;
    el.onclick = (e) => {
      if (e.target.closest("[data-onboard-close]")) {
        try { localStorage.setItem(ONBOARD_KEY, "1"); } catch { /* 저장소 없음 */ }
        el.hidden = true;
        return;
      }
      const goalBtn = e.target.closest("[data-goal]");
      if (goalBtn) {
        Promise.resolve(Store.updateUser({ dailyGoal: Number(goalBtn.dataset.goal) })).catch((err) => toast(err.message));
        toast(`하루 목표를 ${goalBtn.dataset.goal}문제로 정했어요`);
        return renderHome(new URLSearchParams());
      }
      const act = e.target.closest("[data-onboard]")?.dataset.onboard;
      if (act === "wizard") projectWizard();
      else if (act === "try") { prompt.value = "로그 성질 3점짜리 2문제 내줘"; send.disabled = false; prompt.focus(); }
      else if (act === "upload") st.projects.length ? go(`/project/${st.projects[0].id}`) : projectWizard();
    };
  }

  // ---------- 오늘 목표: 링 + 연속 학습 ----------
  // 오늘 아직 안 풀었으면 어제까지 이어진 연속 기록을 보여 주고 이어 가자고 한다
  function streakUntilYesterday() {
    const days = new Set(Store.state.attempts.map((a) => dayKey(a.at)));
    let n = 0;
    for (let d = startOfToday() - DAY; days.has(d); d -= DAY) n++;
    return n;
  }
  function renderGoal() {
    const done = Store.todayCount(), goal = Math.max(1, Store.state.user.dailyGoal || 20);
    const r = 44, len = 2 * Math.PI * r, ratio = Math.min(1, done / goal);
    const left = goal - done;
    const streak = done ? Store.streak() : streakUntilYesterday();
    const streakText = done
      ? `${streak}일 연속 학습 중`
      : streak ? `어제까지 ${streak}일 연속 · 오늘도 이어 가요` : "오늘 첫 문제로 연속 학습을 시작해요";
    $("#goal-card").innerHTML = `
      <h2>오늘 목표</h2>
      <div class="ring" role="img" aria-label="오늘 ${goal}문제 중 ${done}문제 풀었어요">
        <svg viewBox="0 0 100 100"><circle class="track" cx="50" cy="50" r="${r}" /><circle class="fill" cx="50" cy="50" r="${r}" stroke-dasharray="${len}" stroke-dashoffset="${len}" data-offset="${len * (1 - ratio)}" /></svg>
        <div class="num"><b>${done}</b><small>/ ${goal}문제</small></div>
      </div>
      <div class="msg ${left <= 0 ? "done" : ""}">${left <= 0 ? "오늘 목표를 달성했어요!" : `목표까지 ${left}문제`}</div>
      <span class="streak ${done ? "" : "off"}"><i data-lucide="flame"></i>${streakText}</span>`;
    // 다음 프레임에 채워서 링이 차오르는 애니메이션
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const c = $("#goal-card .fill");
      if (c) c.style.strokeDashoffset = c.dataset.offset;
    }));
  }

  // ---------- 오늘 할 일: 복습 시기 → 약점 → 암기 카드 → 목표 ----------
  const REVIEW_DAYS = [1, 3, 7]; // 서버 알림(services/reminders.py)과 같은 간격
  function renderTodo() {
    const st = Store.state;
    const today = startOfToday();
    const open = Store.openNotes();
    const due = open.filter((n) => REVIEW_DAYS.includes(Math.round((today - dayKey(n.createdAt)) / DAY)));
    const weak = Store.conceptStats().find((s) => s.attempts >= 3 && s.accuracy < 0.8 && concept(s.conceptId));
    const unknownCards = st.cards.filter((c) => c.known !== true).length;
    const left = (st.user.dailyGoal || 20) - Store.todayCount();

    const items = [];
    if (due.length) items.push({ href: "#/notes", icon: "rotate-ccw", c: "var(--warn)", title: `복습할 오답 ${due.length}문제`, meta: "틀린 지 1·3·7일째 — 지금 다시 풀면 오래 기억돼요" });
    else if (open.length) items.push({ href: "#/notes", icon: "circle-x", c: "var(--warn)", title: `아직 안 푼 오답 ${open.length}문제`, meta: "맞히면 오답노트에서 졸업해요" });
    if (weak) {
      const c = concept(weak.conceptId);
      items.push({ href: `#/library/concept/${c.id}`, icon: "target", c: COLOR[c.domain], title: `약점 개념 · ${c.name}`, meta: `정답률 ${pct(weak.accuracy)} (${weak.attempts}문제) · 개념 정리부터 다시 봐요` });
    }
    if (unknownCards) items.push({ href: "#/library/cards", icon: "layers", c: "var(--accent)", title: `암기 카드 ${unknownCards}장`, meta: `약 ${Math.max(1, Math.round(unknownCards / 2))}분이면 한 번 넘겨 볼 수 있어요` });
    if (left > 0) {
      const topic = weak ? concept(weak.conceptId).name : (DOMAIN_NAME[myDomains()[0]] ?? "수학");
      items.push({ fill: `${topic} 문제 ${Math.min(left, 5)}개 내줘`, icon: "pencil-line", c: "var(--ink)", title: `문제 ${left}개 더 풀기`, meta: "누르면 입력창에 요청을 채워 드려요" });
    }

    const shown = items.slice(0, 4);
    $("#todo-count").textContent = shown.length ? `${shown.length}개` : "";
    $("#todo").innerHTML = shown.length ? shown.map((t) => {
      const inner = `
        <span class="ic" style="--c:${t.c}"><i data-lucide="${t.icon}"></i></span>
        <span class="tx"><b>${esc(t.title)}</b><small>${esc(t.meta)}</small></span>
        <i data-lucide="chevron-right" class="go"></i>`;
      return t.href ? `<a class="todo-item" href="${t.href}">${inner}</a>` : `<button type="button" class="todo-item" data-fill="${esc(t.fill)}">${inner}</button>`;
    }).join("") : '<div class="todo-done"><i data-lucide="party-popper"></i><span>오늘 할 일을 모두 끝냈어요.<br />내일도 이 화면에서 챙겨 드릴게요</span></div>';
  }

  // ---------- 다가오는 시험 ----------
  const WEEKDAY = "일월화수목금토";
  function renderExam() {
    const upcoming = Store.state.projects
      .map((p) => ({ p, n: daysLeft(p.examDate) }))
      .filter((x) => x.n != null && x.n >= 0)
      .sort((a, b) => a.n - b.n);
    if (!upcoming.length) {
      $("#exam-card").outerHTML = `
        <article class="panel exam empty-exam" id="exam-card">
          <h2>다가오는 시험</h2>
          <p>시험 날짜가 있는 프로젝트를 만들면 D-day와 남은 오답을 여기서 챙겨 드려요.</p>
          <button type="button" class="btn-ghost" data-wizard><i data-lucide="plus"></i>프로젝트 만들기</button>
        </article>`;
      return;
    }
    const { p, n } = upcoming[0];
    const d = new Date(`${p.examDate}T00:00:00`);
    const acc = Store.accuracy({ projectId: p.id });
    const notes = Store.openNotes().filter((x) => x.projectId === p.id).length;
    const next = upcoming[1];
    $("#exam-card").outerHTML = `
      <a class="panel exam" id="exam-card" href="#/project/${p.id}" style="--c:${n <= 14 ? "var(--warn)" : COLOR[projectDomain(p)]}">
        <h2>다가오는 시험</h2>
        <div class="dd">${ddayLabel(n)}</div>
        <div class="name">${esc(p.name)}</div>
        <div class="date">${d.getMonth() + 1}월 ${d.getDate()}일 (${WEEKDAY[d.getDay()]})${p.goal ? ` · 목표 ${esc(p.goal)}` : ""}</div>
        <div class="facts"><span>정답률 <b>${pct(acc)}</b></span><span>남은 오답 <b>${notes}</b></span></div>
        ${next ? `<div class="next">그다음 · ${esc(next.p.name)} ${ddayLabel(next.n)}</div>` : ""}
      </a>`;
  }

  // ---------- 학습 기록: 최근 20주 히트맵 + 이번 주 요약 ----------
  // 칸 하나 12px + 간격 3px. 들어가는 만큼 주를 보여 준다 (12~53주)
  const heatWeeks = () => Math.max(12, Math.min(53, Math.floor(($("#heat-scroll").clientWidth + 3) / 15)));
  let shownWeeks = 0;
  new ResizeObserver(() => {
    if (!home.hidden && Store.state && heatWeeks() !== shownWeeks) renderActivity();
  }).observe($("#heat-scroll"));

  function renderActivity() {
    const sec = $(".activity");
    sec.hidden = !Store.state.attempts.length; // 아직 기록이 없으면 빈 칸만 보이므로 숨긴다
    if (sec.hidden) return;
    const WEEKS = (shownWeeks = heatWeeks());
    const goal = Math.max(1, Store.state.user.dailyGoal || 20);
    const byDay = new Map();
    for (const a of Store.state.attempts) {
      const k = dayKey(a.at);
      const v = byDay.get(k) ?? { n: 0, ok: 0 };
      v.n++; v.ok += a.correct ? 1 : 0;
      byDay.set(k, v);
    }
    const now = new Date(startOfToday());
    const today = now.getTime();
    const mondayOffset = (now.getDay() + 6) % 7; // 월요일 시작
    // 날짜 계산은 Date 생성자로 (서머타임이 있는 시간대에서도 하루 = 자정 기준)
    const dateAt = (offset) => new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset).getTime();
    const startOffset = -mondayOffset - (WEEKS - 1) * 7;
    const level = (n) => (!n ? 0 : n >= goal ? 4 : n >= goal * 0.5 ? 3 : n >= goal * 0.25 ? 2 : 1);

    let html = "", lastMonth = -1;
    for (let w = 0; w < WEEKS; w++) {
      // 월이 바뀌는 주에만 위에 월 표시 (그 주 일요일 기준)
      const m = new Date(dateAt(startOffset + w * 7 + 6)).getMonth();
      // 첫 칸은 그 달이 2주 이상 이어질 때만 (바로 다음 달 표시와 겹치지 않게)
      const crowded = w === 0 && new Date(dateAt(startOffset + 13)).getMonth() !== m;
      html += `<span class="m">${m !== lastMonth && !crowded ? `${m + 1}월` : ""}</span>`;
      lastMonth = m;
      for (let i = 0; i < 7; i++) {
        const t = dateAt(startOffset + w * 7 + i);
        const v = byDay.get(t);
        const d = new Date(t);
        const cls = t > today ? "future" : `l${level(v?.n)}${t === today ? " is-today" : ""}`;
        html += `<span class="d ${cls}" title="${d.getMonth() + 1}월 ${d.getDate()}일 · ${v ? `${v.n}문제, 정답 ${v.ok}` : "학습 없음"}"></span>`;
      }
    }
    const heat = $("#heat");
    heat.innerHTML = html;
    heat.setAttribute("role", "img");
    heat.setAttribute("aria-label", `최근 ${WEEKS}주 동안 날마다 푼 문제 수`);

    // 이번 주(월~오늘) vs 지난주 같은 요일까지
    const sum = (from, to) => {
      let n = 0, ok = 0, days = 0;
      for (let i = from; i <= to; i++) { const v = byDay.get(dateAt(i)); if (v) { n += v.n; ok += v.ok; days++; } }
      return { n, ok, days, acc: n ? ok / n : null };
    };
    const cur = sum(-mondayOffset, 0), prev = sum(-mondayOffset - 7, -7);
    const delta = (a, b, unit) => {
      if (a == null || b == null) return '<span class="delta">지난주 기록 없음</span>';
      const d = a - b;
      return `<span class="delta ${d > 0 ? "up" : d < 0 ? "down" : ""}">지난주보다 ${d > 0 ? "+" : d < 0 ? "−" : "±"}${Math.abs(d)}${unit}</span>`;
    };
    const accPct = (s) => (s.acc == null ? null : Math.round(s.acc * 100));
    $("#week-stats").innerHTML = `
      <div class="wstat"><div class="k">이번 주 푼 문제</div><div class="v">${cur.n}<small>문제</small></div>${delta(cur.n, prev.n || null, "문제")}</div>
      <div class="wstat"><div class="k">이번 주 정답률</div><div class="v">${accPct(cur) ?? "–"}<small>%</small></div>${delta(accPct(cur), accPct(prev), "%p")}</div>
      <div class="wstat"><div class="k">공부한 날</div><div class="v">${cur.days}<small>/ ${mondayOffset + 1}일</small></div><span class="delta">누적 ${Store.state.attempts.length}문제</span></div>`;
  }

  $("#home").addEventListener("click", (e) => {
    const fill = e.target.closest("[data-fill]");
    if (fill) {
      prompt.value = fill.dataset.fill;
      send.disabled = false;
      prompt.focus();
      contentEl.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    if (e.target.closest("[data-wizard]")) projectWizard();
  });

  function card({ href, c, kind, title, meta, pct: p = 0 }) {
    return `
      <a class="card" href="${href}" style="--c:${c}; text-decoration:none; color:inherit">
        <span class="kind"><span class="sw"></span>${esc(kind)}</span>
        <h3>${esc(title)}</h3>
        <div class="meta">${esc(meta)}</div>
        ${p ? `<div class="bar"><i style="width:${p}%"></i></div>` : ""}
      </a>`;
  }

  function renderChip() {
    const p = homeProjectId && Store.project(homeProjectId);
    const chip = $("#project-chip");
    chip.style.setProperty("--c", p ? COLOR[projectDomain(p)] : "var(--ink-3)");
    chip.innerHTML = `<i data-lucide="${p ? "folder" : "folder-open"}"></i><span class="chip-text">${p ? esc(p.name) : "프로젝트 없음"}</span><i data-lucide="chevron-down"></i>`;
    icons();
  }

  $("#project-chip").addEventListener("click", (e) => {
    openMenu(e.currentTarget, [
      { label: "어디에서 공부할까요?", header: true },
      ...Store.state.projects.map((p) => ({ icon: "folder", label: p.name, checked: p.id === homeProjectId, run: () => { homeProjectId = p.id; renderChip(); } })),
      "-",
      { icon: "folder-open", label: "프로젝트 없이", checked: !homeProjectId, run: () => { homeProjectId = null; renderChip(); } },
    ]);
  });

  const syncHomeSend = () => (send.disabled = !(prompt.value.trim() || homeAttach.count) || homeAttach.busy);
  const homeAttach = bindAttach($("#composer"), { onChange: () => syncHomeSend() });
  prompt.addEventListener("input", syncHomeSend);
  bindVoice($("#composer"));
  $("#composer").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = prompt.value.trim();
    if (homeAttach.busy) return toast("파일을 올리는 중이에요. 잠시만 기다려 주세요");
    if (!text && !homeAttach.count) return;
    const files = homeAttach.take();
    prompt.value = "";
    send.disabled = true;
    ask({ projectId: homeProjectId, text, files });
  });

  // 아이콘 타일: 메뉴로 이동하거나 예시 요청을 입력창에 채운다
  const TILE_ROUTES = { 오답노트: "/notes", "개념 정리": "/library", "암기 카드": "/library/cards" };
  $("#actions").addEventListener("click", (e) => {
    const tile = e.target.closest(".action");
    if (!tile) return;
    const label = tile.textContent.trim();
    if (TILE_ROUTES[label]) return go(TILE_ROUTES[label]);
    if (label === "시험지 만들기") {
      const ps = Store.state.projects;
      if (!ps.length) { toast("먼저 준비하는 시험(프로젝트)을 만들어 주세요"); return projectWizard(); }
      if (ps.length === 1) return go(`/project/${ps[0].id}?exam=1`);
      return openMenu(tile, [{ label: "어느 시험으로 만들까요?", header: true },
        ...ps.map((p) => ({ icon: "folder", label: p.name, run: () => go(`/project/${p.id}?exam=1`) }))]);
    }
    if (!tile.dataset.prompt) return openPalette();
    prompt.value = tile.dataset.prompt;
    send.disabled = false;
    prompt.focus();
  });

  // ================= 입력창 + 첨부: 사진·카메라·파일·Google Drive =================
  // 고르는 즉시 서버에 올려 id 를 받고(POST /sessions/files), 보낼 때 그 id 를 메시지에 붙인다.
  // Drive 파일은 브라우저가 사용자의 Google 권한(drive.file — 고른 파일만)으로 내려받아 같은 길로 올린다.
  const ATTACH_MAX = 5, ATTACH_MAX_BYTES = 20 * 1024 * 1024;
  const ATTACH_TYPES = ["application/pdf", "image/png", "image/jpeg", "image/webp"];
  const FILE_ACCEPT = ".pdf,application/pdf,image/png,image/jpeg,image/webp";
  const isTouch = matchMedia("(pointer: coarse)").matches;
  const fileKind = (mime) => (mime === "application/pdf" ? "PDF" : "사진");

  // 큰 사진·HEIC 처럼 서버가 받지 않는 사진은 브라우저에서 JPG 로 줄여 보낸다 (긴 변 2400px)
  async function normalizeImage(file) {
    const ok = ATTACH_TYPES.includes(file.type);
    if (ok && (file.type === "application/pdf" || file.size <= 3 * 1048576)) return file;
    if (!file.type.startsWith("image/")) return file;
    try {
      const bmp = await createImageBitmap(file);
      const k = Math.min(1, 2400 / Math.max(bmp.width, bmp.height));
      const canvas = Object.assign(document.createElement("canvas"), { width: Math.round(bmp.width * k), height: Math.round(bmp.height * k) });
      const g = canvas.getContext("2d");
      g.fillStyle = "#fff"; g.fillRect(0, 0, canvas.width, canvas.height); // 투명 PNG 가 검게 나오지 않게
      g.drawImage(bmp, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise((res) => canvas.toBlob(res, "image/jpeg", 0.88));
      if (!blob) return file;
      return new File([blob], file.name.replace(/\.[^.]+$/, "") + ".jpg", { type: "image/jpeg" });
    } catch {
      return file; // 못 바꾸면 그대로 — 형식이 안 맞으면 아래 검사에서 알려 준다
    }
  }

  // ---------- Google Drive (Google Picker) ----------
  const DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file";
  const DRIVE_MIMES = [...ATTACH_TYPES, "application/vnd.google-apps.document", "application/vnd.google-apps.presentation"].join(",");
  const scriptLoads = {};
  const loadScript = (src) => (scriptLoads[src] ??= new Promise((res, rej) => {
    const s = Object.assign(document.createElement("script"), { src, async: true });
    s.onload = res;
    s.onerror = () => { delete scriptLoads[src]; s.remove(); rej(new Error("Google Drive 를 불러오지 못했어요. 인터넷 연결을 확인해 주세요")); };
    document.head.append(s);
  }));
  let driveReady = null, driveAuth = null; // driveAuth: { token, exp }
  function prepareDrive() {
    driveReady ??= Promise.all([loadScript("https://accounts.google.com/gsi/client"), loadScript("https://apis.google.com/js/api.js")])
      .then(() => new Promise((res, rej) => gapi.load("picker", { callback: res, onerror: () => rej(new Error("Google Drive 를 불러오지 못했어요")) })))
      .catch((e) => { driveReady = null; throw e; });
    return driveReady;
  }
  // 팝업은 클릭 안에서 바로 열어야 막히지 않는다 — 스크립트는 + 메뉴를 열 때 미리 받아 둔다
  function driveToken(cfg) {
    if (driveAuth && driveAuth.exp > Date.now() + 60_000) return Promise.resolve(driveAuth.token);
    return new Promise((res, rej) => {
      const client = google.accounts.oauth2.initTokenClient({
        client_id: cfg.client_id, scope: DRIVE_SCOPE,
        callback: (r) => {
          if (r.error || !r.access_token) return rej(new Error("Google Drive 접근을 허용하지 않았어요"));
          driveAuth = { token: r.access_token, exp: Date.now() + (Number(r.expires_in) || 3600) * 1000 };
          res(r.access_token);
        },
        error_callback: (e) => rej(new Error(e?.type === "popup_failed_to_open"
          ? "팝업이 막혔어요. 브라우저에서 이 사이트의 팝업을 허용하고 다시 눌러 주세요"
          : e?.type === "popup_closed" ? "" : "Google 로그인 중 문제가 생겼어요")),
      });
      client.requestAccessToken({ prompt: "" });
    });
  }
  async function driveDownload(doc, token) {
    const native = doc.mimeType?.startsWith("application/vnd.google-apps.");
    const url = native
      ? `https://www.googleapis.com/drive/v3/files/${encodeURIComponent(doc.id)}/export?mimeType=application/pdf`
      : `https://www.googleapis.com/drive/v3/files/${encodeURIComponent(doc.id)}?alt=media&supportsAllDrives=true`;
    const r = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    if (!r.ok) throw new Error(r.status === 403 && native ? "문서가 너무 커서 PDF 로 바꾸지 못했어요" : "Drive 에서 파일을 받지 못했어요");
    const blob = await r.blob();
    return new File([blob], native ? `${doc.name}.pdf` : doc.name, { type: native ? "application/pdf" : (doc.mimeType || blob.type) });
  }
  function openDrivePicker(cfg, left, onPick) {
    if (!window.google?.accounts?.oauth2 || !window.google?.picker) {
      prepareDrive().then(() => toast("Google Drive 를 준비했어요. 한 번 더 눌러 주세요"), (e) => toast(e.message));
      return;
    }
    driveToken(cfg).then((token) => {
      const P = google.picker;
      const view = new P.DocsView(P.ViewId.DOCS).setMimeTypes(DRIVE_MIMES).setIncludeFolders(true).setSelectFolderEnabled(false);
      const builder = new P.PickerBuilder().addView(view).addView(new P.DocsUploadView())
        .setOAuthToken(token).setDeveloperKey(cfg.api_key).setAppId(cfg.app_id)
        .setLocale("ko").setTitle("첨부할 파일 고르기 (PDF·사진·문서)")
        .setCallback((data) => {
          if (data.action !== P.Action.PICKED) return;
          onPick(data.docs.slice(0, left).map((d) => ({ name: d.name, size: d.sizeBytes, file: driveDownload(d, token) })));
        });
      if (left > 1) builder.enableFeature(P.Feature.MULTISELECT_ENABLED).setMaxItems(left);
      builder.build().setVisible(true);
    }, (e) => e.message && toast(e.message));
  }

  // 입력창 하나에 첨부를 붙인다. onChange: 첨부가 바뀔 때(보내기 버튼 상태 갱신)
  function bindAttach(form, { onChange = () => {} } = {}) {
    const btn = $("[data-attach]", form), input = $("input:not([type=file])", form);
    const tray = document.createElement("div");
    tray.className = "attach-tray";
    tray.hidden = true;
    form.prepend(tray);
    let items = [], seq = 0, driveCfg;
    Store.driveConfig().then((c) => (driveCfg = c));

    const render = () => {
      tray.hidden = !items.length;
      form.classList.toggle("has-files", items.length > 0);
      btn.disabled = items.length >= ATTACH_MAX;
      tray.innerHTML = items.map((it) => `
        <div class="att ${it.status}" data-key="${it.key}" title="${esc(it.error || it.name)}">
          <span class="att-thumb">${it.preview ? `<img src="${it.preview}" alt="" />` : `<i data-lucide="${it.mime === "application/pdf" ? "file-text" : "file"}"></i>`}
            ${it.status === "uploading" ? '<span class="att-spin" aria-hidden="true"></span>' : ""}</span>
          <span class="att-meta"><b>${esc(it.name)}</b><small>${it.status === "error" ? esc(it.error)
            : it.status === "uploading" ? (it.from === "drive" ? "Drive 에서 가져오는 중…" : "올리는 중…")
            : `${fileKind(it.mime)} · ${fmtSize(it.size)}`}</small></span>
          <button type="button" class="att-x" data-remove="${it.key}" aria-label="${esc(it.name)} 첨부 빼기"><i data-lucide="x"></i></button>
        </div>`).join("");
      icons();
      onChange();
    };

    // source: { name, size?, file: File | Promise<File> } — Drive 는 받는 동안 자리부터 보여 준다
    function add(sources, from = "device") {
      const room = ATTACH_MAX - items.length;
      if (room <= 0) return toast(`한 번에 ${ATTACH_MAX}개까지 첨부할 수 있어요`);
      if (sources.length > room) toast(`한 번에 ${ATTACH_MAX}개까지라서 ${room}개만 첨부했어요`);
      for (const src of sources.slice(0, room)) {
        const it = { key: ++seq, name: src.name, size: src.size ?? 0, mime: "", status: "uploading", from };
        items.push(it);
        (async () => {
          let file = await src.file;
          file = await normalizeImage(file);
          Object.assign(it, { name: file.name, size: file.size, mime: file.type });
          if (!ATTACH_TYPES.includes(file.type)) throw new Error("PDF 또는 사진(PNG·JPG·WEBP)만 첨부할 수 있어요");
          if (file.size > ATTACH_MAX_BYTES) throw new Error("파일은 20MB 까지 첨부할 수 있어요");
          if (file.type.startsWith("image/")) { it.preview = URL.createObjectURL(file); render(); }
          const saved = await Store.uploadChatFile(file);
          if (!items.includes(it)) return Store.removeChatFile(saved.id); // 올리는 사이에 뺐다
          Object.assign(it, saved, { status: "done" });
          if (it.preview) Store.rememberChatFileUrl(saved.id, it.preview);
        })().catch((e) => Object.assign(it, { status: "error", error: e.message || "첨부하지 못했어요" })).finally(render);
      }
      render();
    }
    const addFiles = (list) => add([...list].map((f) => ({ name: f.name, size: f.size, file: f })));

    function pick({ accept, capture = false }) {
      const fi = Object.assign(document.createElement("input"), { type: "file", accept, multiple: !capture });
      if (capture) fi.setAttribute("capture", "environment");
      fi.addEventListener("change", () => { if (fi.files.length) addFiles(fi.files); });
      fi.click();
    }

    btn.addEventListener("click", (e) => {
      if (Store.mode !== "api") return toast("체험 모드에서는 파일을 첨부할 수 없어요. 로그인하면 쓸 수 있어요");
      if (driveCfg) prepareDrive().catch(() => {}); // 고르는 동안 미리 받아 둔다
      const left = ATTACH_MAX - items.length;
      openMenu(e.currentTarget, [
        { label: "사진·PDF 를 올리면 AI 가 읽고 풀어 줘요", header: true },
        isTouch && { icon: "camera", label: "카메라로 찍기", run: () => pick({ accept: "image/*", capture: true }) },
        { icon: "image", label: isTouch ? "사진 보관함" : "사진·이미지", run: () => pick({ accept: "image/*" }) },
        { icon: "paperclip", label: "파일 (PDF·사진)", run: () => pick({ accept: FILE_ACCEPT }) },
        driveCfg && "-",
        driveCfg && { icon: "hard-drive", label: "Google Drive 에서 고르기", run: () => openDrivePicker(driveCfg, left, (srcs) => add(srcs, "drive")) },
      ]);
    });

    tray.addEventListener("click", (e) => {
      const x = e.target.closest("[data-remove]");
      if (!x) return;
      const it = items.find((i) => String(i.key) === x.dataset.remove);
      items = items.filter((i) => i !== it);
      if (it?.id) Store.removeChatFile(it.id);
      if (it?.preview) URL.revokeObjectURL(it.preview);
      render();
      input.focus();
    });

    // 붙여넣기(캡처 이미지) · 끌어다 놓기
    input.addEventListener("paste", (e) => {
      const files = [...(e.clipboardData?.files ?? [])];
      if (!files.length || Store.mode !== "api") return;
      e.preventDefault();
      addFiles(files);
    });
    const hasFiles = (e) => [...(e.dataTransfer?.types ?? [])].includes("Files");
    form.addEventListener("dragover", (e) => { if (!hasFiles(e)) return; e.preventDefault(); form.classList.add("dragging"); });
    form.addEventListener("dragleave", (e) => { if (!form.contains(e.relatedTarget)) form.classList.remove("dragging"); });
    form.addEventListener("drop", (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      form.classList.remove("dragging");
      if (Store.mode !== "api") return toast("체험 모드에서는 파일을 첨부할 수 없어요. 로그인하면 쓸 수 있어요");
      addFiles(e.dataTransfer.files);
    });

    return {
      get busy() { return items.some((i) => i.status === "uploading"); },
      get count() { return items.filter((i) => i.status === "done").length; },
      // 보낼 첨부를 꺼내고 입력창을 비운다 (실패한 것은 버림). 미리보기 URL 은 대화 화면에서 계속 쓴다
      take() {
        const files = items.filter((i) => i.status === "done").map(({ id, name, mime, size }) => ({ id, name, mime, size }));
        items = [];
        render();
        return files;
      },
    };
  }

  // 보낸 메시지의 첨부 (사진은 썸네일, PDF 는 이름표). 누르면 새 탭에서 연다
  const messageFilesHTML = (files = []) => (files.length ? `<div class="msg-files">${files.map((f) => f.mime?.startsWith("image/")
    ? `<button type="button" class="msg-img" data-file-open="${f.id}" aria-label="${esc(f.name)} 크게 보기"><img data-file-img="${f.id}" alt="${esc(f.name)}" /></button>`
    : `<button type="button" class="msg-file" data-file-open="${f.id}"><i data-lucide="file-text"></i><span><b>${esc(f.name)}</b><small>${fileKind(f.mime)} · ${fmtSize(f.size)}</small></span></button>`).join("")}</div>` : "");
  function hydrateMessageFiles(root) {
    $$("img[data-file-img]", root).forEach((img) => Store.chatFileUrl(img.dataset.fileImg)
      .then((u) => (img.src = u)).catch(() => img.closest(".msg-img")?.classList.add("broken")));
  }
  function openMessageFile(id) {
    const w = window.open("", "_blank"); // 클릭 안에서 먼저 열어야 팝업이 막히지 않는다
    Store.chatFileUrl(id).then((u) => { if (w) w.location.href = u; else location.href = u; },
      (e) => { w?.close(); toast(e.message); });
  }

  // ================= 음성 입력: 브라우저 음성 인식 + 마이크 음량 미니 게이지 =================
  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  let voice = null; // 지금 듣고 있는 입력창 { btn, stop }
  const MIC_ICON = '<i data-lucide="mic"></i>', STOP_ICON = '<i data-lucide="square"></i>';
  const voiceMeterHTML = '<span class="voice-meter" hidden aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span>';

  function bindVoice(form) {
    const btn = $("[data-mic]", form);
    if (!btn) return;
    btn.addEventListener("click", () => (voice?.btn === btn ? voice.stop() : startVoice(form, btn)));
  }

  async function startVoice(form, btn) {
    if (!SpeechRec) return toast("이 브라우저는 음성 입력을 지원하지 않아요. Chrome·Edge·Safari에서 써 주세요");
    voice?.stop();
    const input = $("input", form), meter = $(".voice-meter", form), bars = $$("i", meter);
    const placeholder = input.placeholder;
    const base = input.value.trim() ? `${input.value.trimEnd()} ` : "";
    const rec = new SpeechRec();
    rec.lang = "ko-KR";
    rec.interimResults = true;   // 말하는 동안 글자를 바로 보여 준다
    rec.continuous = false;      // 말을 멈추면 끝난다
    let finalText = "", stream = null, ctx = null, raf = 0, ended = false;
    const hint = document.createElement("span");
    hint.className = "voice-hint";
    hint.textContent = "듣고 있어요 · 다시 누르면 멈춰요";
    form.append(hint);

    const cleanup = () => {
      if (ended) return;
      ended = true;
      cancelAnimationFrame(raf);
      stream?.getTracks().forEach((t) => t.stop());
      ctx?.close().catch(() => {});
      hint.remove();
      meter.hidden = true;
      btn.classList.remove("listening");
      btn.innerHTML = MIC_ICON;
      btn.setAttribute("aria-label", "음성 입력");
      input.placeholder = placeholder;
      lucide.createIcons();
      if (voice?.btn === btn) voice = null;
    };
    voice = { btn, stop: () => { try { rec.stop(); } catch { /* 이미 끝남 */ } cleanup(); } };

    btn.classList.add("listening");
    btn.innerHTML = STOP_ICON;
    btn.setAttribute("aria-label", "음성 입력 멈추기");
    input.placeholder = "말씀하세요…";
    meter.hidden = false;
    lucide.createIcons();

    rec.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) finalText += r[0].transcript; else interim += r[0].transcript;
      }
      input.value = base + finalText + interim;
      input.dispatchEvent(new Event("input", { bubbles: true })); // 보내기 버튼 켜기
    };
    rec.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") toast("마이크 권한을 허용해 주세요 (주소창의 자물쇠 → 마이크)");
      else if (e.error === "no-speech") toast("목소리가 들리지 않았어요. 다시 눌러 말해 주세요");
      else if (e.error === "audio-capture") toast("마이크를 찾지 못했어요");
      else if (e.error !== "aborted") toast("음성을 알아듣지 못했어요. 다시 해 주세요");
    };
    rec.onend = () => { cleanup(); input.focus(); };
    try { rec.start(); } catch { cleanup(); return toast("음성 입력을 시작하지 못했어요"); }

    // 미니 음성 게이지: 말소리 대역(약 200Hz~3.5kHz)을 다섯 칸으로 나눠 높이로
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      if (ended) return stream.getTracks().forEach((t) => t.stop());
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      const an = ctx.createAnalyser();
      an.fftSize = 512;
      an.smoothingTimeConstant = 0.6;
      ctx.createMediaStreamSource(stream).connect(an);
      const freq = new Uint8Array(an.frequencyBinCount);
      const hz = ctx.sampleRate / an.fftSize;
      const lo = Math.max(1, Math.round(200 / hz)), hi = Math.round(3500 / hz), span = (hi - lo) / bars.length;
      const tick = () => {
        an.getByteFrequencyData(freq);
        bars.forEach((b, i) => {
          let sum = 0;
          for (let k = Math.floor(lo + i * span); k < lo + (i + 1) * span; k++) sum += freq[k];
          const v = Math.min(1, sum / span / 170);
          b.style.height = `${4 + v * 16}px`;
        });
        raf = requestAnimationFrame(tick);
      };
      tick();
    } catch { /* 게이지 없이도 음성 입력은 된다 */ }
  }
  window.addEventListener("hashchange", () => voice?.stop());

  // ================= 대화 =================
  // 질문을 보내고 답을 기다린다. 새 대화면 바로 그 대화로 이동하고, 서버가 진짜 id 를 주면 주소를 바꾼다
  // 계산·설명 질문인지 (서버 explain.is_explain_request 와 같은 기준의 간단판 — 팝업 문구에만 쓴다)
  const explainLike = (t) => !/\d+\s*(문제|문항|개)|문제\s*(를|좀)?\s*(내|만들|줘)|모의고사|출제/.test(t)
    && /계산|구해|풀어|적분|미분|값은|얼마|증명|왜|설명|어떻게|원리|그래프|극한|∫|√/.test(t);
  function ask({ sessionId = null, projectId = null, text, files = [] }) {
    const { id, done } = Store.sendMessage({ sessionId, projectId, text, files });
    const ex = explainLike(text);
    withAIProgress({
      title: files.length ? "첨부한 자료를 읽는 중" : ex ? "풀이를 준비하는 중" : "문제를 준비하는 중",
      steps: files.length ? ["사진·파일 읽기", "문제 이해하기", "단계별로 풀기", "검산하기"]
        : ex ? ["질문 이해하기", "단계별로 풀기", "검산하기", "그래프·화면 준비"]
        : ["요청 이해하기", "문제 만들기", "다른 AI가 다시 풀어 검산", "화면 준비"],
      expectMs: Store.mode === "api" ? (files.length ? 25000 : ex ? 18000 : 30000) : 900,
      run: () => done.catch(() => id), // 실패해도 대화에 '답변을 만들지 못했어요'가 남으니 그 대화를 연다
    }).then((realId = id) => {
      if (location.hash === `#/chat/${realId}`) renderChat(realId);
      else go(`/chat/${realId}`);
    });
    return id;
  }

  // 문제 형식 — 객관식(보기 4·5개) · 단답형(정수) · 주관식(글자) · 수치형 · 서술형(AI 채점)
  const ptype = (p) => p.problemType ?? (p.choices ? "multiple_choice" : "short_answer");
  const isShort = (p) => ptype(p) !== "multiple_choice";
  const TYPE_LABEL = { short_answer: "단답형", text: "주관식", numeric: "수치형", essay: "서술형" };
  const conceptLabel = (p) => {
    const c = concept(p.conceptIds?.[0]);
    return c ? `${subjectOf(c.id)?.name ?? ""} · ${c.name}` : DOMAIN_NAME[p.domain] ?? "";
  };

  function problemHTML(pid, { attempt = null, index = null } = {}) {
    const p = Store.problem(pid);
    if (!p) return "";
    const saved = Store.state.savedProblemIds.includes(pid);
    let answerArea;
    const t = ptype(p);
    if (t === "essay") {
      answerArea = attempt ? essayResultHTML(p, attempt) : `
        <div class="essay-form" data-short><textarea name="answer" rows="6" maxlength="4000" aria-label="답안"
          placeholder="답안을 써 주세요. 제출하면 AI가 채점 기준으로 점수를 매겨요 (10~30초)"></textarea>
          <button class="btn-primary" type="button" data-short-submit><i data-lucide="send"></i>제출하고 채점받기</button></div>`;
    } else if (isShort(p)) {
      const unit = t === "numeric" && p.unit ? ` <small class="unit">${esc(p.unit)}</small>` : "";
      const input = {
        short_answer: '<input name="answer" inputmode="numeric" placeholder="답을 정수로 입력하세요" autocomplete="off" maxlength="10" aria-label="답" />',
        numeric: '<input name="answer" inputmode="decimal" placeholder="수로 입력 (예: 9.8, 3/4)" autocomplete="off" maxlength="40" aria-label="답" />',
        text: '<input name="answer" placeholder="답을 입력하세요" autocomplete="off" maxlength="200" aria-label="답" />',
      }[t] ?? '<input name="answer" placeholder="답을 입력하세요" autocomplete="off" maxlength="200" aria-label="답" />';
      answerArea = attempt
        ? `<div class="short-result ${attempt.correct ? "ok" : "bad"}"><span>내 답 <b>${esc(attempt.answer)}</b></span>${p.answer ? `<span>정답 <b data-math>${esc(p.answer)}</b>${unit}</span>` : ""}</div>`
        : `<div class="short-form" data-short>${input}${unit}<button class="btn-primary" type="button" data-short-submit>제출</button></div>`;
    } else {
      answerArea = `<div class="choices">${p.choices.map((ch, i) => {
        const n = String(i + 1);
        const cls = !attempt ? "" : n === p.answer ? "correct" : n === attempt.answer ? "wrong" : "dim";
        return `<button class="choice ${cls}" data-choice="${n}" ${attempt ? "disabled" : ""}><span class="n">${n}</span><span data-math>${esc(ch)}</span></button>`;
      }).join("")}</div>`;
    }
    let result = "";
    if (attempt) {
      const note = !attempt.correct && Store.state.wrongNotes.find((w) => w.problemId === pid && !w.resolvedAt);
      result = `
        <div class="result ${attempt.correct ? "ok" : "bad"}">
          <i data-lucide="${attempt.correct ? "circle-check" : "circle-x"}"></i>${attempt.correct ? "정답이에요!" : "아쉬워요. 오답노트에 저장했어요"}
        </div>
        ${p.solution ? `<div class="solution"><b>해설</b><span data-math>${esc(p.solution)}</span></div>` : ""}
        ${note ? whyHTML(note) : ""}`;
    }
    const work = workState[pid]?.open;
    return `
      <article class="problem ${work ? "has-work" : ""}" data-problem="${pid}" style="--c:${COLOR[p.domain]}">
        <div class="problem-main">
          <div class="problem-meta">
            <span class="kind"><span class="sw"></span>${esc(conceptLabel(p))}${isShort(p) ? ` · ${TYPE_LABEL[ptype(p)] ?? "단답형"}` : ""}</span>
            <span class="stars" title="난이도 ${p.difficulty}">${"★".repeat(p.difficulty)}${"☆".repeat(5 - p.difficulty)}</span>
            <button class="work-btn ${work ? "on" : ""}" data-work="${pid}" title="풀이를 쓰면 AI가 어디서 틀렸는지 알려줘요"><i data-lucide="pencil-line"></i>서술형 풀이</button>
            <button class="icon-btn save ${saved ? "on" : ""}" data-save="${pid}" title="${saved ? "저장 취소" : "저장"}"><i data-lucide="bookmark"></i></button>
            <button class="icon-btn" data-report="${pid}" title="문제·정답이 이상하면 알려 주세요"><i data-lucide="flag"></i></button>
          </div>
          <p class="stem" data-math>${index ? `<b>${index}.</b> ` : ""}${esc(p.stem)}</p>
          ${answerArea}
          ${result}
        </div>
        ${work ? workHTML(pid) : ""}
      </article>`;
  }

  // 서술형 답안의 AI 채점 결과 — 점수, 기준별 점수·이유, 총평, 내 답안·모범 답안
  function essayResultHTML(p, a) {
    const f = a.feedback;
    if (!f) return `<div class="short-result ${a.correct ? "ok" : "bad"}"><span>내 답안을 제출했어요</span></div>`;
    return `
      <div class="essay-result ${a.correct ? "ok" : "bad"}">
        <div class="essay-score"><b>${f.score}</b><span>/ ${f.max_score}점</span></div>
        <ul class="essay-criteria">${f.criteria.map((c) => `
          <li class="${c.earned >= c.points ? "full" : c.earned ? "part" : "none"}"><span class="pts">${c.earned}/${c.points}</span>
            <div><b data-math>${esc(c.criterion)}</b><small data-math>${esc(c.comment)}</small></div></li>`).join("")}</ul>
        <p class="essay-summary" data-math>${esc(f.summary)}</p>
        <details><summary><i data-lucide="chevron-right"></i>내 답안</summary><p class="prose" data-math>${esc(a.answer)}</p></details>
        ${p.answer ? `<details><summary><i data-lucide="chevron-right"></i>모범 답안</summary><p class="prose" data-math>${esc(p.answer)}</p></details>` : ""}
      </div>`;
  }

  // ---------- 서술형 풀이: 타이핑(수식 미리보기) 또는 손글씨 → AI 가 단계별로 확인 ----------
  const workPreview = (text) => esc(text || "").trim() || '<span class="mini">수식은 $x^2+1$ 처럼 $ 로 감싸면 여기에 보기 좋게 보여요</span>';
  function workHTML(pid) {
    const w = workState[pid];
    const attempted = Store.state.attempts.some((a) => a.problemId === pid);
    const p = Store.problem(pid);
    return `
      <div class="work ${w.full ? "full" : ""}" data-work-panel="${pid}">
        <div class="work-head"><b><i data-lucide="pencil-line"></i>서술형 풀이</b>
          <div class="seg">${[["type", "타이핑"], ["draw", "손글씨"]].map(([k, t]) => `<button type="button" data-work-tab="${k}" class="${w.tab === k ? "on" : ""}">${t}</button>`).join("")}</div>
          <button type="button" class="icon-btn" data-work-full aria-label="${w.full ? "작게 보기" : "크게 보기"}" title="${w.full ? "작게 보기 (Esc)" : "크게 보기"}"><i data-lucide="${w.full ? "minimize-2" : "maximize-2"}"></i></button>
          <button type="button" class="icon-btn" data-work-close aria-label="풀이 칸 닫기"><i data-lucide="x"></i></button></div>
        <div class="work-stem"><p data-math>${esc(p?.stem ?? "")}</p>
          ${p?.choices?.length ? `<ol>${p.choices.map((c) => `<li data-math>${esc(c)}</li>`).join("")}</ol>` : ""}</div>
        <div class="work-type" ${w.tab === "type" ? "" : "hidden"}>
          <textarea data-work-text rows="6" maxlength="4000" placeholder="한 줄에 한 단계씩 적어 주세요&#10;예) t = x^2 로 치환하면 dt = 2x dx&#10;    $\\int_0^1 e^t\\,dt = e - 1$">${esc(w.text)}</textarea>
          <div class="work-preview" data-math data-work-preview>${workPreview(w.text)}</div>
        </div>
        <div class="work-draw" ${w.tab === "draw" ? "" : "hidden"}>
          <canvas data-work-canvas aria-label="손글씨 풀이"></canvas>
          <div class="work-tools">
            <button type="button" class="tag ${w.eraser ? "" : "on"}" data-work-pen><i data-lucide="pen-line"></i>펜</button>
            <button type="button" class="tag ${w.eraser ? "on" : ""}" data-work-eraser><i data-lucide="eraser"></i>지우개</button>
            <button type="button" class="tag" data-work-clear><i data-lucide="trash-2"></i>모두 지우기</button>
          </div>
        </div>
        <div class="work-foot"><span class="mini">${attempted ? "정답과 비교해서 알려줘요" : "답을 내기 전이라 정답 대신 틀린 곳과 힌트만 알려줘요"}</span>
          <button type="button" class="btn-primary" data-work-submit ${w.busy ? "disabled" : ""}>${w.busy ? '<i data-lucide="loader-circle" class="spin"></i>확인하는 중…' : '<i data-lucide="scan-search"></i>풀이 확인'}</button></div>
        <div data-work-review>${w.review ? reviewHTML(w.review, w.tab, pid) : ""}</div>
      </div>`;
  }
  const VERDICT = {
    correct: ["circle-check", "풀이가 맞아요", "ok"], partial: ["circle-alert", "거의 맞았어요. 중간에 고칠 곳이 있어요", "warn"],
    wrong: ["circle-x", "접근 방법을 다시 생각해 봐요", "bad"], unreadable: ["scan-eye", "풀이를 읽지 못했어요. 조금 더 크고 또렷하게 써 주세요", "warn"],
  };
  function reviewHTML(r, tab, pid) {
    const [icon, title, cls] = VERDICT[r.verdict] ?? VERDICT.partial;
    return `
      <div class="work-review ${cls}">
        <div class="wr-head"><i data-lucide="${icon}"></i>${title}</div>
        ${tab === "draw" && r.transcription ? `<details class="wr-read"><summary>AI가 읽은 내 풀이</summary><div class="prose" data-math>${esc(r.transcription)}</div></details>` : ""}
        ${r.steps.length ? `<ol class="wr-steps">${r.steps.map((s, i) => `
          <li class="${s.ok ? "ok" : "bad"} ${r.first_error === i + 1 ? "first" : ""}"><i data-lucide="${s.ok ? "check" : "x"}"></i>
            <div><span data-math>${esc(s.step)}</span>${r.first_error === i + 1 ? "<em>여기서부터 틀렸어요</em>" : ""}<small data-math>${esc(s.comment)}</small></div></li>`).join("")}</ol>` : ""}
        <p data-math>${esc(r.summary)}</p>
        ${r.hint ? `<p class="wr-hint" data-math><b>힌트</b> ${esc(r.hint)}</p>` : ""}
        <button type="button" class="link-btn" data-report-review="${pid}">채점이 이상해요</button>
      </div>`;
  }
  // 손글씨 캔버스: 흰 바탕 PNG 로 저장 (지우개는 흰색으로 덧칠)
  function mountWorkCanvases() {
    $$("canvas[data-work-canvas]:not([data-ready])").forEach((cv) => {
      const w = workState[cv.closest("[data-work-panel]").dataset.workPanel];
      const ctx = cv.getContext("2d");
      const width = cv.clientWidth;
      if (!width) return; // 숨겨진 탭이면 보일 때 다시
      // 크게 보기에서 쓴 것을 작게 돌아와도 잘리지 않게: 폭에 맞춰 줄이고 그 높이만큼 캔버스를 늘린다
      const [iw, ih] = w.image ? w.imageSize : [0, 0];
      const scale = iw ? Math.min(1, width / iw) : 1;
      const height = Math.max(cv.clientHeight || 320, Math.ceil(ih * scale));
      if (height > cv.clientHeight) cv.style.height = `${height}px`;
      const dpr = Math.min(devicePixelRatio || 1, 2);
      cv.width = width * dpr;
      cv.height = height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = "#fff";
      ctx.fillRect(0, 0, width, height);
      if (w.image) { const img = new Image(); img.onload = () => ctx.drawImage(img, 0, 0, iw * scale, ih * scale); img.src = w.image; }
      cv.dataset.ready = "1";
      let drawing = false;
      const at = (e) => { const r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
      cv.addEventListener("pointerdown", (e) => {
        drawing = true;
        cv.setPointerCapture(e.pointerId);
        ctx.lineCap = ctx.lineJoin = "round";
        ctx.strokeStyle = w.eraser ? "#fff" : "#0f172a";
        ctx.lineWidth = w.eraser ? 22 : e.pointerType === "pen" && e.pressure ? 1.5 + e.pressure * 2 : 2.4;
        ctx.beginPath();
        ctx.moveTo(...at(e));
        ctx.lineTo(...at(e));
        ctx.stroke();
      });
      cv.addEventListener("pointermove", (e) => { if (drawing) { ctx.lineTo(...at(e)); ctx.stroke(); } });
      const end = () => { if (!drawing) return; drawing = false; w.image = cv.toDataURL("image/png"); w.imageSize = [width, height]; w.drawn = true; };
      cv.addEventListener("pointerup", end);
      cv.addEventListener("pointercancel", end);
    });
  }
  // 풀이 칸 크게 보기 — 화면 전체로 펼치고 문제를 위에 보여 준다. 손글씨는 새 크기로 캔버스를 다시 깐다 (쓴 것은 유지)
  function setWorkFull(panel, full) {
    const w = workState[panel.dataset.workPanel];
    w.full = full;
    panel.classList.toggle("full", full);
    document.body.classList.toggle("work-full-open", full);
    const btn = $("[data-work-full]", panel);
    btn.setAttribute("aria-label", full ? "작게 보기" : "크게 보기");
    btn.title = full ? "작게 보기 (Esc)" : "크게 보기";
    btn.innerHTML = `<i data-lucide="${full ? "minimize-2" : "maximize-2"}"></i>`;
    const cv = $("canvas[data-work-canvas]", panel);
    cv.replaceWith(Object.assign(document.createElement("canvas"), { ariaLabel: "손글씨 풀이" }));
    $(".work-draw canvas", panel).setAttribute("data-work-canvas", "");
    icons();
    (w.tab === "type" ? $("[data-work-text]", panel) : null)?.focus();
  }
  document.addEventListener("keydown", (e) => {
    const panel = e.key === "Escape" && $(".work.full");
    if (panel) { e.preventDefault(); setWorkFull(panel, false); }
  });

  // 풀이 칸의 버튼들 (문제 카드가 있는 모든 화면에서 공통)
  async function handleWork(e) {
    const toggle = e.target.closest("[data-work]");
    if (toggle) {
      const pid = toggle.dataset.work, card = toggle.closest("[data-problem]");
      const w = (workState[pid] ??= { open: false, tab: "type", text: "", image: null, drawn: false, eraser: false, review: null, busy: false });
      w.open = !w.open;
      card.classList.toggle("has-work", w.open);
      toggle.classList.toggle("on", w.open);
      $("[data-work-panel]", card)?.remove();
      if (w.open) { card.insertAdjacentHTML("beforeend", workHTML(pid)); icons(); $("[data-work-text]", card)?.focus(); }
      return;
    }
    const panel = e.target.closest("[data-work-panel]");
    const pid = panel.dataset.workPanel, w = workState[pid];
    const tab = e.target.closest("[data-work-tab]");
    if (tab) {
      w.tab = tab.dataset.workTab;
      $$("[data-work-tab]", panel).forEach((b) => b.classList.toggle("on", b === tab));
      $(".work-type", panel).hidden = w.tab !== "type";
      $(".work-draw", panel).hidden = w.tab !== "draw";
      mountWorkCanvases();
      return;
    }
    if (e.target.closest("[data-work-full]")) {
      setWorkFull(panel, !w.full);
      return;
    }
    if (e.target.closest("[data-work-close]")) {
      if (w.full) setWorkFull(panel, false);
      w.open = false;
      const card = panel.closest("[data-problem]");
      card.classList.remove("has-work");
      $("[data-work]", card)?.classList.remove("on");
      panel.remove();
      return;
    }
    const pen = e.target.closest("[data-work-pen]"), eraser = e.target.closest("[data-work-eraser]");
    if (pen || eraser) {
      w.eraser = !!eraser;
      $("[data-work-pen]", panel).classList.toggle("on", !w.eraser);
      $("[data-work-eraser]", panel).classList.toggle("on", w.eraser);
      return;
    }
    if (e.target.closest("[data-work-clear]")) {
      w.image = null;
      w.drawn = false;
      const cv = $("canvas[data-work-canvas]", panel);
      cv.replaceWith(Object.assign(document.createElement("canvas"), { ariaLabel: "손글씨 풀이" }));
      $(".work-draw canvas", panel).setAttribute("data-work-canvas", "");
      mountWorkCanvases();
      return;
    }
    if (!e.target.closest("[data-work-submit]")) return; // 캔버스·글 입력 등은 채점으로 넘기지 않는다
    const text = (w.text || "").trim();
    const image = w.tab === "draw" && w.drawn ? w.image : null;
    if (w.tab === "type" ? !text : !image) return toast(w.tab === "draw" ? "손글씨로 풀이를 써 주세요" : "풀이를 적어 주세요");
    w.busy = true;
    const setBtn = () => {
      const b = $(`[data-work-panel="${pid}"] [data-work-submit]`);
      if (!b) return;
      b.disabled = w.busy;
      b.innerHTML = w.busy ? '<i data-lucide="loader-circle" class="spin"></i>확인하는 중…' : '<i data-lucide="scan-search"></i>풀이 확인';
      lucide.createIcons();
    };
    setBtn();
    try {
      w.review = await withAIProgress({
        title: "풀이를 확인하는 중", steps: ["풀이 읽기", "단계별로 확인", "처음 틀린 단계 찾기"], expectMs: 20000,
        run: () => Store.reviewSolution(pid, w.tab === "type" ? { text } : { image }),
      });
      const box = $(`[data-work-panel="${pid}"] [data-work-review]`);
      if (box) { box.innerHTML = reviewHTML(w.review, w.tab, pid); icons(); }
    } catch (err) { toast(err.message); }
    w.busy = false;
    setBtn();
  }
  // 타이핑하면 수식 미리보기를 바로 바꾼다
  document.addEventListener("input", (e) => {
    if (!e.target.matches?.("[data-work-text]")) return;
    const panel = e.target.closest("[data-work-panel]");
    workState[panel.dataset.workPanel].text = e.target.value;
    const pv = $("[data-work-preview]", panel);
    pv.innerHTML = workPreview(e.target.value);
    if (window.renderMathInElement) renderMathInElement(pv, MATH_OPTS);
  });


  // 보기 클릭 또는 단답형 제출 → 채점. 서버 결과를 받은 뒤 redraw(문제 카드, 풀이) 로 다시 그린다
  // (단답형은 form 이 아니라 입력칸+버튼 — 모달 자체가 form 이라 form 을 겹칠 수 없음)
  async function handleAnswer(e, ctx, redraw) {
    let box, answer;
    const choice = e.target.closest?.("[data-choice]");
    const shortBtn = e.target.closest?.("[data-short-submit]");
    if (choice) {
      box = choice.closest("[data-problem]");
      answer = choice.dataset.choice;
    } else if (shortBtn) {
      box = shortBtn.closest("[data-problem]");
      answer = $("[name=answer]", box).value.trim();
      const t = ptype(Store.problem(box.dataset.problem));
      if (t === "short_answer" && !/^-?\d[\d,]*$/.test(answer)) { toast("답을 정수로 입력해 주세요"); return true; }
      if (t === "numeric" && !/^\s*-?\d[\d,]*(\.\d+)?([eE]-?\d+)?(\s*\/\s*-?\d+(\.\d+)?)?/.test(answer)) { toast("답을 수로 입력해 주세요 (예: 9.8, 3/4)"); return true; }
      if (t === "essay" && answer.length < 5) { toast("답안을 조금 더 써 주세요"); return true; }
      if (!answer) { toast("답을 입력해 주세요"); return true; }
      if (t === "essay") { shortBtn.innerHTML = '<i data-lucide="loader-circle" class="spin"></i>AI가 채점하는 중… (10~30초)'; lucide.createIcons(); }
    } else return false;
    if (box.classList.contains("busy")) return true;
    box.classList.add("busy");
    try {
      const essay = ptype(Store.problem(box.dataset.problem)) === "essay" && Store.mode === "api";
      const r = essay
        ? await withAIProgress({ title: "서술형 답안을 채점하는 중", steps: ["답안 읽기", "채점 기준과 비교", "점수·피드백 정리"], expectMs: 20000,
            run: () => Store.answer({ problemId: box.dataset.problem, answer, ...ctx }) })
        : await Store.answer({ problemId: box.dataset.problem, answer, ...ctx });
      redraw(box, { answer, correct: r.correct, score: r.score, feedback: r.feedback });
      if (r.resolved) toast("오답을 극복했어요");
    } catch (err) {
      toast(err.message);
      box.classList.remove("busy");
      const sb = $("[data-short-submit]", box);
      if (sb && ptype(Store.problem(box.dataset.problem)) === "essay") { sb.innerHTML = '<i data-lucide="send"></i>제출하고 채점받기'; lucide.createIcons(); }
    }
    return true;
  }

  const whyHTML = (note) => `
    <div class="why">왜 틀렸나요?
      ${Object.entries(ERROR_TYPES).filter(([k]) => k !== "unknown").map(([k, v]) =>
        `<button class="tag ${note.errorType === k ? "on" : ""}" data-error="${k}" data-note="${note.id}">${v}</button>`).join("")}
    </div>`;

  // 문제 카드 공통 동작: 저장, 틀린 이유 표시
  function handleProblemExtras(e) {
    const report = e.target.closest("[data-report], [data-report-review]");
    if (report) {
      feedbackModal(report.dataset.report ? { problemId: report.dataset.report, kind: "problem" } : { problemId: report.dataset.reportReview, kind: "review" });
      return true;
    }
    if (e.target.closest("[data-work], [data-work-panel]")) { handleWork(e); return true; }
    const save = e.target.closest("[data-save]");
    if (save) {
      Store.toggleSaved(save.dataset.save);
      const on = Store.state.savedProblemIds.includes(save.dataset.save);
      save.classList.toggle("on", on);
      toast(on ? "라이브러리에 저장했어요" : "저장을 취소했어요");
      return true;
    }
    const why = e.target.closest("[data-error]");
    if (why) {
      Store.setErrorType(why.dataset.note, why.dataset.error);
      $$(`[data-note="${why.dataset.note}"]`).forEach((b) => b.classList.toggle("on", b.dataset.error === why.dataset.error));
      return true;
    }
    return false;
  }

  // 문제 카드 하나만 다시 그리기 (라이브러리·다시 풀기 등)
  const redrawCard = (box, attempt) => { box.outerHTML = problemHTML(box.dataset.problem, { attempt }); icons(); };

  // 대화에 나온 문제 묶음 — '한 문제씩'(넘겨 보기) 또는 '모두 보기'. 고른 방식은 기억한다
  let problemView = (() => { try { return localStorage.getItem("eureka.problemView") || "one"; } catch { return "one"; } })();
  const problemPos = {}; // "대화id:메시지번호" → 보고 있는 문제 위치
  function problemSetHTML(s, mi, ids) {
    const cards = ids.map((pid, i) => problemHTML(pid, { attempt: Store.lastAttempt(s.id, pid), index: i + 1 }));
    if (ids.length < 2) return cards.join("");
    const key = `${s.id}:${mi}`, one = problemView === "one";
    const pos = Math.min(problemPos[key] ?? 0, ids.length - 1);
    const dots = ids.map((pid, i) => {
      const a = Store.lastAttempt(s.id, pid);
      return `<button type="button" class="pdot ${a ? (a.correct ? "ok" : "bad") : ""} ${i === pos ? "on" : ""}" data-pgo="${i}" aria-label="${i + 1}번 문제"></button>`;
    }).join("");
    const done = ids.filter((pid) => Store.lastAttempt(s.id, pid)).length;
    return `
      <div class="pset" data-pset="${key}" data-count="${ids.length}">
        <div class="pset-bar">
          <div class="seg">${[["one", "한 문제씩"], ["all", "모두 보기"]].map(([k, t]) => `<button type="button" data-pview="${k}" class="${problemView === k ? "on" : ""}">${t}</button>`).join("")}</div>
          ${one ? `<div class="pnav">
              <button type="button" class="icon-btn" data-pstep="-1" ${pos === 0 ? "disabled" : ""} aria-label="이전 문제"><i data-lucide="chevron-left"></i></button>
              <b>${pos + 1}</b><span>/ ${ids.length}</span>
              <button type="button" class="icon-btn" data-pstep="1" ${pos === ids.length - 1 ? "disabled" : ""} aria-label="다음 문제"><i data-lucide="chevron-right"></i></button>
            </div><div class="pdots">${dots}</div>` : `<span class="mini">${done} / ${ids.length}문제 풀었어요</span>`}
        </div>
        ${cards.map((c, i) => `<div class="pslot" ${one && i !== pos ? "hidden" : ""}>${c}</div>`).join("")}
      </div>`;
  }
  // 묶음의 보기 방식·위치 바꾸기 (다시 그리지 않고 보이는 카드만 바꾼다)
  function handleProblemSet(e, rerender) {
    const mode = e.target.closest("[data-pview]");
    if (mode) {
      problemView = mode.dataset.pview;
      try { localStorage.setItem("eureka.problemView", problemView); } catch { /* 저장 불가 */ }
      rerender();
      return true;
    }
    const step = e.target.closest("[data-pstep]"), goTo = e.target.closest("[data-pgo]");
    if (!step && !goTo) return false;
    const set = e.target.closest("[data-pset]"), key = set.dataset.pset, n = Number(set.dataset.count);
    const pos = goTo ? Number(goTo.dataset.pgo) : (problemPos[key] ?? 0) + Number(step.dataset.pstep);
    problemPos[key] = Math.max(0, Math.min(n - 1, pos));
    rerender();
    return true;
  }

  function renderChat(id, { keepScroll = false } = {}) {
    if (voice && !document.body.contains(voice.btn)) voice.stop();
    if (voice?.btn.closest("#chat-form")) voice.stop(); // 입력창을 새로 그리기 전에 듣기를 멈춘다
    const s = Store.session(id);
    if (!s) { toast("대화를 찾을 수 없어요"); return go("/"); }
    const scroll = contentEl.scrollTop;
    const p = s.projectId && Store.project(s.projectId);
    const msgs = s.messages.map((m, mi) => m.role === "user"
      ? `<div class="msg user">${messageFilesHTML(m.files)}<div class="bubble">${esc(m.text)}</div></div>`
      : `<div class="msg ai"><span class="ai-avatar"></span><div class="ai-body"><p>${esc(m.text)}</p>
          ${m.explanation ? explanationHTML(m.explanation, `${s.id}-${mi}`) : ""}
          ${problemSetHTML(s, mi, m.problemIds ?? [])}
        </div></div>`).join("");

    view.innerHTML = `
      <div class="chat-view">
        <div class="chat-head">
          <h1>${esc(s.title)}</h1>
          ${p ? `<a class="pill" href="#/project/${p.id}" style="--c:${COLOR[projectDomain(p)]}"><i data-lucide="folder"></i>${esc(p.name)}</a>` : ""}
          <button class="icon-btn" id="chat-more" aria-label="대화 메뉴"><i data-lucide="ellipsis"></i></button>
        </div>
        <div class="thread">
          ${msgs}
          ${Store.isPending(id) ? `<div class="msg ai"><span class="ai-avatar"></span><div class="ai-body"><div class="typing"><i></i><i></i><i></i></div></div></div>` : ""}
        </div>
        <form class="composer glass chat-composer" id="chat-form">
          <button type="button" class="icon-btn" data-attach title="사진·파일 첨부" aria-label="사진·파일 첨부"><i data-lucide="plus"></i></button>
          <input id="chat-input" placeholder="이어서 물어보세요" autocomplete="off" />
          ${voiceMeterHTML}
          <button type="button" class="icon-btn mic-btn" data-mic title="음성 입력" aria-label="음성 입력"><i data-lucide="mic"></i></button>
          <button type="submit" class="send" disabled aria-label="보내기"><i data-lucide="arrow-up"></i></button>
        </form>
      </div>`;
    if (keepScroll) $(".chat-view").classList.add("still"); // 답을 고를 때 다시 그려도 떠오르는 움직임은 처음 한 번만
    icons();

    const input = $("#chat-input"), btn = $("#chat-form .send");
    const sync = () => (btn.disabled = !(input.value.trim() || attach.count) || attach.busy);
    const attach = bindAttach($("#chat-form"), { onChange: () => sync() });
    input.addEventListener("input", sync);
    $("#chat-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (attach.busy) return toast("파일을 올리는 중이에요. 잠시만 기다려 주세요");
      if (!text && !attach.count) return;
      ask({ sessionId: id, text, files: attach.take() });
      renderChat(id);
      $("#chat-input").focus();
    });
    $("#chat-more").addEventListener("click", (e) => chatMenu(e.currentTarget, id));
    bindVoice($("#chat-form"));

    const ctx = { projectId: s.projectId, sessionId: s.id };
    const redraw = () => renderChat(id, { keepScroll: true });
    view.onclick = (e) => {
      const f = e.target.closest("[data-file-open]");
      if (f) return openMessageFile(f.dataset.fileOpen);
      if (!handleProblemSet(e, redraw) && !handleProblemExtras(e)) handleAnswer(e, ctx, redraw);
    };
    hydrateMessageFiles(view);

    contentEl.scrollTop = keepScroll ? scroll : contentEl.scrollHeight;
  }

  // ================= 계산·설명 풀이 (요약 · 원리 · 단계 · 답 · 검산 · 그래프) =================
  const SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]; // 범주 색 순서 고정 (dataviz 검증 통과)
  const graphData = {}; // 그래프 key → 데이터 (화면 폭이 바뀌면 다시 그린다)

  function explanationHTML(e, key) {
    const check = e.check?.status === "verified"
      ? `<span class="ex-check ok"><i data-lucide="badge-check"></i>검산 완료 · ${esc(e.check.note)}</span>`
      : e.check?.status === "mismatch"
        ? `<span class="ex-check warn"><i data-lucide="triangle-alert"></i>검산 결과가 달라요 · ${esc(e.check.note)}. 한 번 더 확인해 주세요</span>`
        : "";
    if (e.graph) graphData[key] = e.graph;
    return `
      <div class="explain">
        <p class="ex-summary" data-math>${esc(e.summary)}</p>
        ${e.principle ? `<p class="ex-principle" data-math><b>원리</b> ${esc(e.principle)}</p>` : ""}
        ${e.steps?.length ? `<h4 class="ex-h">단계별 풀이</h4>
          <ol class="ex-steps">${e.steps.map((s) => `
            <li><p data-math><b>${esc(s.title)}</b> ${esc(s.text)}</p>${s.math ? `<div class="ex-math" data-math>$$${esc(s.math)}$$</div>` : ""}</li>`).join("")}
          </ol>` : ""}
        ${e.result ? `<div class="ex-result"><span class="ex-label">최종 답</span><div class="ex-math" data-math>$$${esc(e.result)}$$</div>${check}</div>` : check}
        ${e.graph ? `
          <figure class="ex-graph">
            <figcaption>${esc(e.graph.title)}</figcaption>
            <div class="ex-legend">${e.graph.series.map((s) => `<span><i style="background:${SERIES[s.slot % 3]}"></i>${esc(s.label)}</span>`).join("")}</div>
            <div class="ex-plot" data-graph="${esc(key)}" role="img" aria-label="${esc(e.graph.title)}"></div>
            <details class="ex-table"><summary>값을 표로 보기</summary>${graphTable(e.graph)}</details>
          </figure>` : ""}
      </div>`;
  }

  function graphTable(g) {
    const step = Math.max(1, Math.round((g.xs.length - 1) / 10));
    const rows = g.xs.map((x, i) => i).filter((i) => i % step === 0 || i === g.xs.length - 1);
    const f = (v) => (v == null ? "정의되지 않음" : Number(v.toFixed(4)).toString());
    return `<table><thead><tr><th>x</th>${g.series.map((s) => `<th>${esc(s.label)}</th>`).join("")}</tr></thead>
      <tbody>${rows.map((i) => `<tr><td>${f(g.xs[i])}</td>${g.series.map((s) => `<td>${f(s.ys[i])}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  }

  // 보기 좋은 눈금 (1·2·5 × 10ⁿ)
  function niceTicks(lo, hi, count = 5) {
    const span = hi - lo || 1, raw = span / count, mag = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 5, 10].map((k) => k * mag).find((s) => span / s <= count) ?? 10 * mag;
    const out = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(Math.abs(v) < step * 1e-9 ? 0 : v);
    return out;
  }
  const fmtTick = (v) => (Math.abs(v) >= 1000 || (Math.abs(v) < 0.01 && v !== 0) ? v.toExponential(0) : Number(v.toFixed(2)).toString());

  function mountGraphs() {
    $$(".ex-plot[data-graph]").forEach((el) => {
      if (!el._ro) { el._ro = new ResizeObserver(() => drawGraph(el)); el._ro.observe(el); }
      drawGraph(el);
    });
  }

  function drawGraph(el) {
    const g = graphData[el.dataset.graph];
    const W = Math.round(el.clientWidth);
    if (!g || !W || el._w === W) return;
    el._w = W;
    const H = Math.round(W < 480 ? Math.max(240, W * 0.78) : Math.min(340, Math.max(220, W * 0.56)));
    const M = { l: 44, r: 14, t: 14, b: 28 }, pw = W - M.l - M.r, ph = H - M.t - M.b;

    // y 범위: 2~98% 값으로 정해 점근선 근처의 아주 큰 값이 그래프를 짓누르지 않게
    const all = g.series.flatMap((s) => s.ys).filter((v) => v != null).sort((a, b) => a - b);
    const q = (p) => all[Math.min(all.length - 1, Math.max(0, Math.round(p * (all.length - 1))))];
    let lo = q(0.02), hi = q(0.98);
    g.marks.forEach((mk) => { lo = Math.min(lo, mk.y); hi = Math.max(hi, mk.y); });
    if (lo > 0 && lo < (hi - lo) * 0.6) lo = 0; // 0 이 가까우면 기준선이 보이게
    if (hi < 0 && -hi < (hi - lo) * 0.6) hi = 0;
    if (hi - lo < 1e-9) { lo -= 1; hi += 1; }
    const pad = (hi - lo) * 0.12; lo -= pad; hi += pad;
    const x0 = g.xs[0], x1 = g.xs[g.xs.length - 1];
    const X = (x) => M.l + ((x - x0) / (x1 - x0)) * pw, Y = (y) => M.t + (1 - (y - lo) / (hi - lo)) * ph;

    const yt = niceTicks(lo, hi, 5), xt = niceTicks(x0, x1, Math.max(3, Math.round(pw / 80)));
    const grid = yt.map((v) => `<line x1="${M.l}" x2="${W - M.r}" y1="${Y(v)}" y2="${Y(v)}" class="${v === 0 ? "axis0" : "grid"}"/>
      <text x="${M.l - 8}" y="${Y(v) + 4}" text-anchor="end" class="tick">${fmtTick(v)}</text>`).join("")
      + xt.map((v) => `${v === 0 ? `<line x1="${X(0)}" x2="${X(0)}" y1="${M.t}" y2="${H - M.b}" class="axis0"/>` : ""}
      <text x="${X(v)}" y="${H - 8}" text-anchor="middle" class="tick">${fmtTick(v)}</text>`).join("");

    // 선: 정의되지 않는 점이나 점근선(값이 크게 튀는 곳)에서 끊는다
    const jump = (hi - lo) * 0.8;
    const paths = g.series.map((s) => {
      let d = "", prev = null;
      s.ys.forEach((y, i) => {
        if (y == null || (prev != null && Math.abs(y - prev) > jump)) { prev = y; if (y == null) return; d += `M${X(g.xs[i]).toFixed(1)},${Y(y).toFixed(1)}`; return; }
        d += `${prev == null ? "M" : "L"}${X(g.xs[i]).toFixed(1)},${Y(y).toFixed(1)}`;
        prev = y;
      });
      return `<path d="${d}" fill="none" stroke="${SERIES[s.slot % 3]}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" clip-path="url(#clip-${el.dataset.graph.replace(/\W/g, "")})"/>`;
    }).join("");

    // 선 끝 직접 라벨 (글자는 본문 색, 겹치면 아래로 비킨다)
    const ends = g.series.map((s) => {
      for (let i = s.ys.length - 1; i >= 0; i--) {
        const y = s.ys[i];
        if (y != null && y >= lo && y <= hi) return { s, x: X(g.xs[i]), y: Y(y) };
      }
      return null;
    }).filter(Boolean).sort((a, b) => a.y - b.y);
    ends.forEach((e, i) => { if (i && e.y - ends[i - 1].y < 14) e.y = ends[i - 1].y + 14; });
    const labels = W < 420 ? "" : ends.map((e) => `<text x="${Math.min(e.x, W - M.r) - 4}" y="${e.y - 7}" text-anchor="end" class="dlabel">${esc(e.s.label.split("=")[0].trim())}</text>`).join("");

    // 점 라벨: 가까운 라벨끼리는 위아래로 비키고, 아주 좁은 화면에서는 좌표만
    const pts = g.marks.map((mk) => ({ mk, cx: X(mk.x), cy: Y(mk.y), ly: Y(mk.y) - 8 })).sort((a, b) => a.ly - b.ly);
    pts.forEach((p, i) => { if (i && Math.abs(p.cx - pts[i - 1].cx) < 120 && p.ly - pts[i - 1].ly < 16) p.ly = pts[i - 1].ly + 16; });
    const marks = pts.map(({ mk, cx, cy, ly }) => `<circle cx="${cx}" cy="${cy}" r="4.5" fill="${SERIES[mk.slot % 3]}" stroke="#fff" stroke-width="2"/>
      <text x="${cx + 8}" y="${ly}" class="mlabel">${W < 420 ? "" : `${esc(mk.label)} `}(${fmtTick(mk.x)}, ${fmtTick(mk.y)})</text>`).join("");

    const clipId = `clip-${el.dataset.graph.replace(/\W/g, "")}`;
    el.innerHTML = `
      <svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
        <defs><clipPath id="${clipId}"><rect x="${M.l}" y="${M.t}" width="${pw}" height="${ph}"/></clipPath></defs>
        ${grid}${paths}${marks}${labels}
        <g class="hover" hidden><line class="cross" y1="${M.t}" y2="${H - M.b}"/>${g.series.map((s) => `<circle r="4" fill="${SERIES[s.slot % 3]}" stroke="#fff" stroke-width="2"/>`).join("")}</g>
        <rect x="${M.l}" y="${M.t}" width="${pw}" height="${ph}" fill="transparent" class="hit"/>
      </svg>
      <div class="ex-tip" hidden></div>`;

    // 마우스·손가락을 따라다니는 기준선 + 값
    const svg = $("svg", el), hov = $(".hover", el), tip = $(".ex-tip", el), dots = $$(".hover circle", el);
    const move = (ev) => {
      const r = svg.getBoundingClientRect();
      const px = Math.min(Math.max(ev.clientX - r.left, M.l), W - M.r);
      const i = Math.round(((px - M.l) / pw) * (g.xs.length - 1));
      const xv = g.xs[i];
      hov.hidden = false;
      $(".cross", el).setAttribute("x1", X(xv)); $(".cross", el).setAttribute("x2", X(xv));
      g.series.forEach((s, k) => {
        const y = s.ys[i], ok = y != null && y >= lo && y <= hi;
        dots[k].style.display = ok ? "" : "none";
        if (ok) { dots[k].setAttribute("cx", X(xv)); dots[k].setAttribute("cy", Y(y)); }
      });
      tip.hidden = false;
      tip.innerHTML = `<b>x = ${fmtTick(xv)}</b>${g.series.map((s) => `<span><i style="background:${SERIES[s.slot % 3]}"></i>${esc(s.label.split("=")[0].trim())} <b>${s.ys[i] == null ? "–" : Number(s.ys[i].toFixed(4))}</b></span>`).join("")}`;
      const left = X(xv) + 12 + tip.offsetWidth > W ? X(xv) - 12 - tip.offsetWidth : X(xv) + 12;
      tip.style.left = `${left}px`; tip.style.top = `${M.t + 4}px`;
    };
    const hit = $(".hit", el);
    hit.addEventListener("pointermove", move);
    hit.addEventListener("pointerdown", move);
    hit.addEventListener("pointerleave", () => { hov.hidden = true; tip.hidden = true; });
  }

  // ================= 프로젝트: 작업 공간 (올린 문제 · 문제와 정답 · 분석 리포트) =================
  const MATERIAL_STATUS = { uploaded: ["분석 대기", "clock"], extracting: ["AI가 읽는 중", "loader"], ready: ["완료", "circle-check"], failed: ["실패", "circle-alert"] };
  const SRC_LABEL = { printed: "시험지", file: "정답 파일", ai: "AI 풀이", manual: "직접 입력" };
  const ANS_STATUS = {
    manual: ["직접 입력", "ok"], sheet: ["정답표", "ok"], confirmed: ["정답 확인", "ok"], verified: ["검산 완료", "ok"],
    conflict: ["정답표와 다름", "warn"], uncertain: ["확인 필요", "warn"], failed: ["풀이 실패", "bad"],
  };
  const QTYPE_NAME = { multiple_choice: "객관식", short_answer: "단답형", text: "주관식", numeric: "수치형", essay: "서술형" };
  const DIFF_NAME = ["기본", "쉬움", "보통", "어려움", "최고난도"];
  const wsState = {}; // 프로젝트별 { sel: 자료 id | "all", view: "list" | "erd", open: Set }
  const ansLabel = (q, a = q.answer) => (!a ? "–" : q.choices ? (CIRC[Number(a) - 1] ?? a) : texAns(a));
  const hasAnswer = (q) => !!q.answer && !["uncertain", "failed"].includes(q.answer_status);

  function renderProject(id, params) {
    const p = Store.project(id);
    if (!p) { toast("프로젝트를 찾을 수 없어요"); return go("/"); }
    const d = projectDomain(p);
    const n = daysLeft(p.examDate);
    const acc = Store.accuracy({ projectId: id });
    const tries = Store.state.attempts.filter((a) => a.projectId === id).length;
    const right = Store.state.attempts.filter((a) => a.projectId === id && a.correct).length;
    const open = Store.openNotes().filter((w) => w.projectId === id).length;
    const weak = Store.conceptStats({ projectId: id }).slice(0, 3);
    const sessions = Store.state.sessions.filter((s) => s.projectId === id).sort((a, b) => b.updatedAt - a.updatedAt);
    const units = p.unitIds.length ? p.unitIds : childrenOf(p.subjectId).map((u) => u.id);
    const api = Store.mode === "api";
    wsState[id] ??= { sel: "all", view: "list", open: new Set() };
    const chip = (icon, text) => `<span class="ws-chip"><i data-lucide="${icon}"></i>${esc(text)}</span>`;

    view.innerHTML = `
      <section class="ws-head">
        <div class="ws-top">
          <span class="ws-icon" style="--c:${COLOR[d]}"><i data-lucide="folder-open"></i></span>
          <div class="ws-title">
            <h1>${esc(p.name)}</h1>
            <div class="ws-meta">
              ${chip("book-open", concept(p.subjectId)?.name ?? "코스")}${chip("list-checks", qtypeLabel(p))}
              ${p.goal ? chip("flag", `목표 ${p.goal}`) : ""}${p.examDate ? chip("calendar", `시험일 ${p.examDate}`) : ""}
              ${p.textbook ? chip("book-marked", p.textbook) : ""}
            </div>
          </div>
          <div class="ws-actions">
            ${api ? '<button class="btn-ghost" data-ws-upload><i data-lucide="upload"></i>기출 올리기</button>' : ""}
            <a class="btn-primary" href="#/?project=${id}"><i data-lucide="square-pen"></i>이 프로젝트에서 새 학습</a>
            <button class="icon-btn" id="project-more" aria-label="프로젝트 메뉴"><i data-lucide="ellipsis"></i></button>
          </div>
        </div>
        <div class="ws-kpis">
          ${n == null ? '<button class="ws-kpi-btn" data-proj-edit><span>시험까지</span><b class="soft">시험일 정하기</b><small>D-day를 챙겨 드려요 →</small></button>'
            : `<div><span>시험까지</span><b class="${n >= 0 && n <= 14 ? "warn" : ""}">${ddayLabel(n)}</b><small>${p.examDate}</small></div>`}
          ${tries ? `<div><span>푼 문제</span><b>${tries}</b><small>맞힌 문제 ${right}</small></div>
          <div><span>정답률</span><b>${pct(acc)}</b><small>이 프로젝트 기준</small></div>`
            : `<a href="#/?project=${id}" class="ws-kpi-wide"><span>학습 기록</span><b class="soft">첫 문제 풀기</b><small>풀면 정답률과 약점을 계산해 드려요 →</small></a>`}
          <a href="#/notes?project=${id}"><span>남은 오답</span><b class="${open ? "warn" : ""}">${open}</b><small>오답노트 열기 →</small></a>
          <div id="ws-kpi-files"><span>올린 문항</span><b>${api ? "…" : "–"}</b><small>정답 있음 –</small></div>
        </div>
      </section>

      ${api ? `
      <div class="ws-grid">
        <section class="panel ws-col ws-files">
          <div class="ws-col-head"><h3><i data-lucide="layers"></i>올린 문제</h3>
            <button class="icon-btn" data-ws-upload title="기출·교재 올리기" aria-label="기출 올리기"><i data-lucide="plus"></i></button></div>
          <div id="ws-files"><p class="mini">불러오는 중…</p></div>
        </section>
        <section class="panel ws-col ws-sheet"><div id="ws-sheet"><p class="mini">불러오는 중…</p></div></section>
        <aside class="panel ws-col ws-report">
          <div id="ws-report"><p class="mini">분석하는 중…</p></div>
          <div class="ws-gen">
            <h4><i data-lucide="sparkles"></i>기출을 닮은 새 문제</h4>
            <div class="seg small" id="gen-level">${[["easier", "쉽게"], ["same", "비슷하게"], ["harder", "어렵게"]].map(([k, v]) => `<button type="button" data-level="${k}" class="${k === "same" ? "on" : ""}">${v}</button>`).join("")}</div>
            <div class="ws-gen-row">
              <select class="select" id="gen-count" aria-label="문항 수">${[1, 2, 3, 4, 5].map((k) => `<option value="${k}" ${k === 3 ? "selected" : ""}>${k}문제</option>`).join("")}</select>
              <button class="btn-ghost" id="gen-go"><i data-lucide="wand-sparkles"></i>만들기</button>
            </div>
            <p class="mini" id="gen-status">만든 문제는 다른 AI가 다시 풀어 검산한 뒤 대화로 열려요</p>
          </div>
        </aside>
      </div>` : '<div class="ai-slot" style="margin-top:16px"><i data-lucide="info"></i><div>기출 업로드와 분석 리포트는 로그인해서 서버 화면으로 열었을 때 쓸 수 있어요.</div></div>'}

      <section class="panel ws-extra" id="ws-more">
        <div class="seg small ws-tabs">
          <button data-ws-tab="weak" class="on"><i data-lucide="target"></i>약점 TOP 3</button>
          <button data-ws-tab="units"><i data-lucide="list-tree"></i>학습 범위</button>
          <button data-ws-tab="chats"><i data-lucide="messages-square"></i>대화 ${sessions.length}</button>
          ${api ? '<button data-ws-tab="exams"><i data-lucide="trending-up"></i>시험 기록</button>' : ""}
        </div>
        <div data-ws-pane="weak">
          ${weak.length ? `<ul class="weak-list">${weak.map((w) => `
            <li style="--c:${COLOR[d]}">
              <div class="row"><a href="#/library/concept/${w.conceptId}" style="color:inherit;text-decoration:none">${esc(concept(w.conceptId)?.name ?? "")}</a><span>${pct(w.accuracy)} · ${w.attempts}문제</span></div>
              <div class="bar"><i style="width:${w.accuracy * 100}%"></i></div>
            </li>`).join("")}</ul>` : '<p class="mini">문제를 풀면 약점이 여기에 나타나요</p>'}
        </div>
        <div data-ws-pane="units" hidden>
          <div class="unit-list">${units.map((u) => `<span class="pill" style="--c:${COLOR[d]}">${esc(concept(u)?.name ?? "")}</span>`).join("")}</div>
        </div>
        ${api ? '<div data-ws-pane="exams" hidden><p class="mini">시험 기록을 불러오는 중…</p></div>' : ""}
        <div data-ws-pane="chats" hidden>
          ${sessions.length ? `<div class="list">${sessions.slice(0, 8).map((s) => `
            <a href="#/chat/${s.id}"><i data-lucide="message-circle"></i>${esc(s.title)}<span>${relTime(s.updatedAt)}</span></a>`).join("")}</div>`
            : '<p class="mini">아직 대화가 없어요. "이 프로젝트에서 새 학습"으로 시작해 보세요</p>'}
        </div>
      </section>`;
    $("#project-more").addEventListener("click", (e) => projectMenu(e.currentTarget, id));
    $("#ws-more").addEventListener("click", (e) => {
      const t = e.target.closest("[data-ws-tab]");
      if (!t) return;
      $$("#ws-more [data-ws-tab]").forEach((b) => b.classList.toggle("on", b === t));
      $$("#ws-more [data-ws-pane]").forEach((pane) => (pane.hidden = pane.dataset.wsPane !== t.dataset.wsTab));
      if (t.dataset.wsTab === "exams") drawExamHistory(id, $('#ws-more [data-ws-pane="exams"]'));
    });
    $$("[data-proj-edit]").forEach((b) => b.addEventListener("click", () => projectModal(p)));
    if (params?.get("tab") === "exams" && api) { $('#ws-more [data-ws-tab="exams"]')?.click(); requestAnimationFrame(() => $("#ws-more")?.scrollIntoView({ block: "start" })); }
    if (api) bindWorkspace(id, params?.get("exam") === "1");
  }

  function bindWorkspace(id, openExam = false) {
    const here = () => navKey() === `project:${id}`;
    const st = wsState[id];
    let data = null, timer = null, openExamOnLoad = false;

    async function load() {
      if (!here()) return;
      try { data = await Store.workspace(id); } catch (e) { $("#ws-files").innerHTML = `<p class="mini">${esc(e.message)}</p>`; return; }
      if (!here()) return;
      if (st.sel !== "all" && !data.materials.some((x) => x.id === st.sel)) st.sel = "all";
      draw();
      if (openExamOnLoad) {
        openExamOnLoad = false;
        if (data.problems.length) examOptions(); else toast("시험지를 만들려면 먼저 기출을 올려 주세요");
      }
      clearTimeout(timer);
      if (data.materials.some((x) => x.status === "uploaded" || x.status === "extracting" || x.answer_key_status === "running")) timer = setTimeout(load, 4000);
    }
    const sheets = () => data.materials.filter((x) => x.kind !== "answer_sheet");
    const answerFileOf = (mid) => data.materials.find((x) => x.kind === "answer_sheet" && x.answer_for_id === mid);
    const problemsOf = (mid) => data.problems.filter((q) => q.material_id === mid);

    function draw() { drawKpi(); drawFiles(); drawSheet(); drawReport(); icons(); if (st.view === "erd") requestAnimationFrame(drawErdLines); }

    function drawKpi() {
      const total = data.problems.length, ok = data.problems.filter(hasAnswer).length;
      $("#ws-kpi-files").innerHTML = `<span>올린 문항</span><b>${total}</b><small>정답 있음 ${total ? `${Math.round((ok / total) * 100)}%` : "–"} (${ok}/${total})</small>`;
    }

    function drawFiles() {
      const list = sheets();
      const allCount = data.problems.length;
      $("#ws-files").innerHTML = `
        <button class="ws-file ${st.sel === "all" ? "on" : ""}" data-ws-sel="all">
          <span class="ws-file-ic"><i data-lucide="library"></i></span>
          <span class="ws-file-main"><b>모든 자료</b><small>${list.length}개 파일 · ${allCount}문항</small></span>
        </button>
        ${list.map((m) => {
          const [label, icon] = MATERIAL_STATUS[m.status];
          const qs = problemsOf(m.id), ok = qs.filter(hasAnswer).length, af = answerFileOf(m.id);
          return `
          <div class="ws-file ${st.sel === m.id ? "on" : ""} ${m.status}" data-ws-sel="${m.id}" role="button" tabindex="0">
            <span class="ws-file-ic"><i data-lucide="${m.content_type === "application/pdf" ? "file-text" : "image"}"></i></span>
            <span class="ws-file-main">
              <b title="${esc(m.filename)}">${esc(m.filename)}</b>
              <small>${m.status === "ready" ? `${m.kind === "textbook" ? "교재" : "기출"} · ${qs.length}문항 · 정답 ${ok}/${qs.length}` : `<i data-lucide="${icon}" class="${m.status === "extracting" ? "spin" : ""}"></i>${label}`}</small>
              ${af ? `<span class="ws-tag ${af.status === "failed" ? "bad" : ""}"><i data-lucide="link-2"></i>정답 파일 ${af.status === "ready" && af.answer_map ? `${af.answer_map.matched}/${af.answer_map.total}` : MATERIAL_STATUS[af.status][0]}</span>` : ""}
              ${m.answer_key_status === "done" ? '<span class="ws-tag ok"><i data-lucide="file-check-2"></i>정답지</span>'
                : m.answer_key_status === "running" ? '<span class="ws-tag"><i data-lucide="loader" class="spin"></i>정답지 만드는 중</span>' : ""}
              ${m.error ? `<span class="ws-err">${esc(m.error)}</span>` : ""}
            </span>
            <button class="icon-btn ws-more" data-ws-menu="${m.id}" aria-label="자료 메뉴"><i data-lucide="ellipsis-vertical"></i></button>
          </div>`;
        }).join("")}
        ${list.length ? "" : '<div class="ws-empty"><i data-lucide="file-up"></i><b>아직 올린 기출이 없어요</b><span>PDF나 사진을 올리면 AI가 문항을 읽어 정답과 함께 정리해요</span><button class="btn-primary" data-ws-upload><i data-lucide="upload"></i>기출 올리기</button></div>'}`;
    }

    function drawSheet() {
      const mat = st.sel === "all" ? null : data.materials.find((x) => x.id === st.sel);
      const qs = mat ? problemsOf(mat.id) : data.problems;
      const ok = qs.filter(hasAnswer).length;
      const erdMat = mat ?? sheets().find((x) => x.status === "ready" && problemsOf(x.id).length);
      const keyBtn = mat && mat.status === "ready" && mat.problem_count
        ? (mat.answer_key_status === "done" ? `<a class="btn-ghost" href="#/answer-key/${mat.id}"><i data-lucide="file-check-2"></i>정답지</a>`
          : mat.answer_key_status === "running" ? '<span class="ws-tag"><i data-lucide="loader" class="spin"></i>정답지 만드는 중</span>'
          : `<button class="btn-ghost" data-ak-make="${mat.id}"><i data-lucide="file-pen-line"></i>정답지 만들기</button>`) : "";
      $("#ws-sheet").innerHTML = `
        <div class="ws-col-head">
          <div><h3><i data-lucide="table-2"></i>${mat ? esc(mat.filename) : "모든 문제"}</h3><small>${qs.length}문항 · 정답 있음 ${ok}/${qs.length}</small></div>
          <div class="ws-sheet-actions">
            <div class="seg small"><button data-ws-view="list" class="${st.view === "list" ? "on" : ""}"><i data-lucide="rows-3"></i>문제·정답</button><button data-ws-view="erd" class="${st.view === "erd" ? "on" : ""}"><i data-lucide="network"></i>정답 연결 보기</button></div>
            ${keyBtn}
          </div>
        </div>
        ${!qs.length ? '<div class="ws-empty"><i data-lucide="table-2"></i><b>아직 읽은 문항이 없어요</b><span>왼쪽에서 기출을 올리면 문항과 정답이 여기에 정리돼요</span></div>'
          : st.view === "erd" ? erdHTML(erdMat, erdMat ? problemsOf(erdMat.id) : [], erdMat ? answerFileOf(erdMat.id) : null, !mat)
          : listHTML(qs, !mat)}`;
    }

    function listHTML(qs, grouped) {
      let lastMat = null;
      return `<div class="ws-table" role="table" aria-label="문제와 정답">
        <div class="ws-tr ws-th" role="row"><span>번호</span><span>문제</span><span>정답</span><span>출처</span><span>상태</span></div>
        ${qs.map((q, i) => {
          const head = grouped && q.material_id !== lastMat ? `<div class="ws-group">${esc(data.materials.find((x) => x.id === q.material_id)?.filename ?? "")}</div>` : "";
          lastMat = q.material_id;
          const [label, tone] = ANS_STATUS[q.answer_status] ?? ["정답 없음", "none"];
          const opened = st.open.has(q.id);
          return `${head}
          <div class="ws-tr ${opened ? "open" : ""}" role="row" data-ws-row="${q.id}" tabindex="0">
            <span class="no">${q.number ?? i + 1}</span>
            <div class="stem"><div class="${opened ? "" : "clamp"}" data-math>${esc(q.stem)}</div>
              ${opened && q.choices ? `<ol class="ws-choices">${q.choices.map((c, k) => `<li class="${String(k + 1) === q.answer ? "on" : ""}"><span>${CIRC[k]}</span><span data-math>${esc(c)}</span></li>`).join("")}</ol>` : ""}
              <span class="ws-sub">${esc(QTYPE_NAME[q.problem_type] ?? "")} · 난이도 ${q.difficulty}${q.needs_figure ? " · 그림 문항" : ""}${concept(q.concept_ids?.[0]) ? ` · ${esc(concept(q.concept_ids[0]).name)}` : ""}</span>
            </div>
            <b class="ans ${q.answer ? "" : "none"}" data-math>${esc(ansLabel(q))}</b>
            <span class="src">${q.answer_source ? `<i class="sd sd-${q.answer_source}"></i>${SRC_LABEL[q.answer_source]}` : "—"}</span>
            <span class="ws-badge ${tone}">${label}</span>
          </div>`;
        }).join("")}
      </div>`;
    }

    // ERD: 실제 테이블 구조대로 problems ─1:1─ problem_answers ─N:1─ answer_sheet
    const ERD_MAX = 40;
    function erdHTML(mat, qs, af, auto) {
      if (!mat) return '<div class="ws-empty"><i data-lucide="network"></i><b>매핑을 그릴 문제지가 없어요</b></div>';
      const rows = qs.slice(0, ERD_MAX);
      const mp = af?.answer_map;
      return `
        ${auto ? `<p class="mini erd-note">자료를 고르지 않아 <b>${esc(mat.filename)}</b>의 연결을 보여 드려요. 왼쪽에서 다른 자료를 고를 수 있어요</p>` : ""}
        <p class="erd-tip"><i data-lucide="pencil"></i>번호나 정답을 누르면 고칠 수 있어요. 번호를 고치면 정답 파일과 다시 맞춰요</p>
        <div class="erd" id="erd">
          <svg class="erd-lines" id="erd-lines" aria-hidden="true"></svg>
          <div class="erd-ent">
            <div class="erd-h"><i data-lucide="table"></i>problems<small>문제지 · ${qs.length} rows</small></div>
            <div class="erd-c"><span><em>PK</em> id</span><span>number</span></div>
            ${rows.map((q, i) => `<div class="erd-r" data-pr="${q.id}"><code>${esc(q.id.slice(0, 10))}</code><button class="erd-edit" data-erd-num="${q.id}" title="번호 고치기">#${q.number ?? i + 1}<i data-lucide="pencil"></i></button></div>`).join("")}
          </div>
          <div class="erd-ent">
            <div class="erd-h"><i data-lucide="table"></i>problem_answers<small>1 : 1</small></div>
            <div class="erd-c"><span><em>FK</em> problem_id</span><span>answer</span><span>source</span></div>
            ${rows.map((q, i) => `<div class="erd-r ${hasAnswer(q) ? "" : q.answer ? "warn" : "missing"}" data-ar="${q.id}" data-src="${q.answer_source ?? ""}">
              <code>→ #${q.number ?? i + 1}</code><button class="erd-edit" data-erd-ans="${q.id}" title="정답 고치기"><b data-math>${esc(ansLabel(q))}</b><i data-lucide="pencil"></i></button><span class="src">${q.answer_source ? `<i class="sd sd-${q.answer_source}"></i>${SRC_LABEL[q.answer_source]}` : "없음"}</span></div>`).join("")}
          </div>
          <div class="erd-ent erd-sheet">
            <div class="erd-h"><i data-lucide="table"></i>materials<small>answer_sheet · N : 1</small></div>
            <div class="erd-c"><span><em>PK</em> id</span><span>filename</span></div>
            <div class="erd-r ${af ? "" : "missing"}" data-sr><code>${af ? esc(af.id.slice(0, 8)) : "NULL"}</code><span>${af ? esc(af.filename) : "연결된 정답 파일 없음"}</span></div>
            <div class="erd-kv">
              <div><span>UNIQUE</span><b>answer_for_id</b></div>
              <div><span>matched</span><b>${mp ? `${mp.matched} / ${mp.total}` : "–"}</b></div>
              <div><span>missing</span><b>${mp?.missing?.length ? mp.missing.slice(0, 8).join(", ") : "–"}</b></div>
              <div><span>extra</span><b>${mp?.extra?.length ? mp.extra.slice(0, 8).join(", ") : "–"}</b></div>
            </div>
            ${af ? "" : `<button class="btn-ghost erd-attach" data-attach-answer="${mat.id}"><i data-lucide="link-2"></i>정답 파일 연결</button>`}
          </div>
        </div>
        <div class="erd-legend">
          <span><i class="ln ok"></i>연결됨 (문항 1개에 정답 1개)</span><span><i class="ln warn"></i>확인 필요</span><span><i class="ln miss"></i>정답 없음</span>
          <span><i class="sd sd-printed"></i>시험지</span><span><i class="sd sd-file"></i>정답 파일</span><span><i class="sd sd-ai"></i>AI 풀이</span><span><i class="sd sd-manual"></i>직접 입력</span>
          ${qs.length > ERD_MAX ? `<span class="mini">처음 ${ERD_MAX}개 행만 표시</span>` : ""}
        </div>`;
    }

    function drawErdLines() {
      const box = $("#erd"), svg = $("#erd-lines");
      if (!box || !svg) return;
      const R = box.getBoundingClientRect();
      svg.setAttribute("width", R.width); svg.setAttribute("height", R.height);
      const mid = (el, side) => { const r = el.getBoundingClientRect(); return [side === "r" ? r.right - R.left : r.left - R.left, r.top - R.top + r.height / 2]; };
      const curve = ([x1, y1], [x2, y2], cls) => {
        const dx = Math.max(24, (x2 - x1) / 2);
        return `<path class="${cls}" d="M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}"/><circle class="${cls}" cx="${x1}" cy="${y1}" r="2.5"/><circle class="${cls}" cx="${x2}" cy="${y2}" r="2.5"/>`;
      };
      const sheetRow = $("[data-sr]", box);
      let paths = "";
      $$("[data-pr]", box).forEach((pr) => {
        const ar = $(`[data-ar="${CSS.escape(pr.dataset.pr)}"]`, box);
        if (!ar) return;
        const cls = ar.classList.contains("missing") ? "miss" : ar.classList.contains("warn") ? "warn" : "ok";
        paths += curve(mid(pr, "r"), mid(ar, "l"), cls);
        if (ar.dataset.src === "file" && sheetRow) paths += curve(mid(ar, "r"), mid(sheetRow, "l"), "file");
      });
      svg.innerHTML = paths;
    }

    function drawReport() {
      const P = data.problems, total = P.length;
      const host = $("#ws-report");
      if (!total) {
        host.innerHTML = `<div class="ws-col-head"><h3><i data-lucide="chart-pie"></i>분석 리포트</h3></div>
          <div class="ws-empty small"><i data-lucide="chart-no-axes-column"></i><b>아직 분석할 문제가 없어요</b><span>기출을 올리면 출제 유형·난이도·정답 비율을 정리해 드려요</span></div>
          <button class="btn-primary ws-exam" disabled><i data-lucide="file-text"></i>시험 준비하기</button>`;
        return;
      }
      const tally = (f) => P.reduce((a, q) => { const k = f(q); a[k] = (a[k] ?? 0) + 1; return a; }, {});
      const byConcept = Object.entries(tally((q) => concept(q.concept_ids?.[0])?.name ?? "분류 안 됨")).sort((a, b) => b[1] - a[1]);
      const topC = byConcept.slice(0, 6), restC = byConcept.slice(6).reduce((a, [, n]) => a + n, 0);
      const byDiff = [1, 2, 3, 4, 5].map((k) => P.filter((q) => q.difficulty === k).length);
      const byType = Object.entries(tally((q) => QTYPE_NAME[q.problem_type] ?? "기타")).sort((a, b) => b[1] - a[1]);
      const okN = P.filter(hasAnswer).length, warnN = P.filter((q) => ["conflict", "uncertain"].includes(q.answer_status)).length;
      const noneN = total - okN - warnN;
      const fig = P.filter((q) => q.needs_figure).length;
      const avg = P.reduce((a, q) => a + q.difficulty, 0) / total;
      const maxC = Math.max(...topC.map(([, n]) => n)), maxD = Math.max(1, ...byDiff);
      const pctOf = (n) => `${Math.round((n / total) * 100)}%`;
      host.innerHTML = `
        <div class="ws-col-head"><div><h3><i data-lucide="chart-pie"></i>분석 리포트</h3><small>올린 문항 ${total}개 기준</small></div></div>
        <ul class="ws-insights">
          <li><i data-lucide="target"></i><span>가장 많이 나온 유형은 <b>${esc(topC[0][0])}</b> (${topC[0][1]}문항, ${pctOf(topC[0][1])})</span></li>
          <li><i data-lucide="gauge"></i><span>평균 난이도 <b>${avg.toFixed(1)}</b> · ${avg >= 3.5 ? "어려운 문항 비중이 높아요" : avg >= 2.5 ? "중간 난도 중심이에요" : "기본 문항 위주예요"}</span></li>
          <li><i data-lucide="${noneN || warnN ? "circle-alert" : "badge-check"}"></i><span>정답 있음 <b>${okN}/${total}</b>${noneN + warnN ? ` · ${noneN + warnN}문항은 정답 파일 연결이나 정답지로 채워 주세요` : " · 모든 문항의 정답이 있어요"}</span></li>
          ${fig ? `<li><i data-lucide="image"></i><span>그림이 필요한 문항 <b>${fig}개</b> — 시험지에서는 원본을 함께 보세요</span></li>` : ""}
        </ul>
        <h4 class="ws-h4">출제 유형</h4>
        <div class="ws-bars">${topC.map(([name, k]) => `
          <div class="ws-bar"><span title="${esc(name)}">${esc(name)}</span><span class="track"><i style="width:${(k / maxC) * 100}%"></i></span><b>${k}</b></div>`).join("")}
          ${restC ? `<div class="ws-bar muted"><span>그 밖의 유형</span><span class="track"><i style="width:${(restC / maxC) * 100}%"></i></span><b>${restC}</b></div>` : ""}</div>
        <h4 class="ws-h4">난이도</h4>
        <div class="ws-diff">${byDiff.map((k, i) => `<div title="${DIFF_NAME[i]} ${k}문항"><span class="col"><i style="height:${(k / maxD) * 100}%"></i></span><b>${k}</b><small>${DIFF_NAME[i]}</small></div>`).join("")}</div>
        <h4 class="ws-h4">문항 형식</h4>
        <div class="ws-types">${byType.map(([name, k]) => `<span>${esc(name)} <b>${k}</b></span>`).join("")}</div>
        <h4 class="ws-h4">정답 현황</h4>
        <div class="ws-stack" role="img" aria-label="정답 확인 ${okN}, 확인 필요 ${warnN}, 정답 없음 ${noneN}">
          <i class="ok" style="flex:${okN}"></i><i class="warn" style="flex:${warnN}"></i><i class="none" style="flex:${noneN}"></i></div>
        <div class="ws-stack-legend"><span><i class="ok"></i>확인 ${okN}</span><span><i class="warn"></i>확인 필요 ${warnN}</span><span><i class="none"></i>정답 없음 ${noneN}</span></div>
        <button class="btn-primary ws-exam" data-exam><i data-lucide="file-text"></i>시험 준비하기</button>
        <p class="mini ws-exam-note">올린 문제로 화면에서 바로 시험을 보거나(타이머), 시험지로 인쇄해요</p>`;
    }

    // 정답 연결 편집: 정답 직접 고치기 · 번호 고치기
    function editAnswer(pid) {
      const q = data.problems.find((x) => x.id === pid);
      const save = async (body, msg) => {
        try { await Store.editProblem(q.material_id, pid, body); toast(msg); } catch (err) { toast(err.message); }
        load();
      };
      formModal({
        title: `${q.number ?? ""}번 정답 고치기`, submit: "저장",
        body: `<p class="modal-text clamp3" data-math>${esc(q.stem)}</p>
          ${q.choices ? `<div class="erd-pick">${q.choices.map((c, k) => `<label><input type="radio" name="erd-ans" value="${k + 1}" ${q.answer === String(k + 1) ? "checked" : ""} /><span>${CIRC[k]}</span><span data-math>${esc(c)}</span></label>`).join("")}</div>`
            : `<div class="field"><label for="erd-ans-text">정답</label><input id="erd-ans-text" value="${esc(q.answer)}" maxlength="200" /></div>`}
          <p class="mini">지금 정답의 출처: ${q.answer_source ? SRC_LABEL[q.answer_source] : "없음"}. 직접 고친 정답은 시험지·정답 파일·AI 풀이보다 우선해요.</p>
          ${q.manual ? '<button type="button" class="btn-ghost" data-erd-reset><i data-lucide="undo-2"></i>직접 고친 것 취소하고 원래대로</button>' : ""}`,
        onSubmit: (f) => {
          const v = q.choices ? $("input[name=erd-ans]:checked", f)?.value : $("#erd-ans-text", f).value.trim();
          if (!v) { toast(q.choices ? "보기를 골라 주세요" : "정답을 적어 주세요"); return false; }
          save({ manual_answer: v }, `${q.number ?? ""}번 정답을 고쳤어요`);
        },
      });
      $("[data-erd-reset]")?.addEventListener("click", () => { closeOverlays(); save({ reset_manual: true }, "원래 정답으로 되돌렸어요"); });
      icons();
    }
    function editNumber(pid) {
      const q = data.problems.find((x) => x.id === pid);
      formModal({
        title: "문항 번호 고치기", submit: "저장",
        body: `<p class="modal-text clamp3" data-math>${esc(q.stem)}</p>
          <div class="field"><label for="erd-num">번호</label><input id="erd-num" type="number" min="0" max="9999" value="${q.number ?? ""}" /></div>
          <p class="mini">AI가 번호를 잘못 읽었을 때 고쳐 주세요. 정답 파일이 연결돼 있으면 새 번호로 다시 맞춰요.</p>`,
        onSubmit: (f) => {
          const n = Number($("#erd-num", f).value);
          if (!Number.isInteger(n) || n < 0) { toast("번호를 숫자로 적어 주세요"); return false; }
          Store.editProblem(q.material_id, pid, { number: n })
            .then((r) => toast(r.remapped ? `번호를 고치고 정답 파일과 다시 맞췄어요 (${r.remapped.matched}/${r.remapped.total})` : "번호를 고쳤어요"))
            .catch((err) => toast(err.message)).finally(load);
        },
      });
    }

    function examOptions() {
      const mats = sheets().filter((x) => problemsOf(x.id).length);
      const total = data.problems.length;
      formModal({
        title: "시험 준비하기", submit: "시험 시작",
        body: `
          <div class="field"><label for="ex-scope">범위</label><select id="ex-scope" class="select">
            <option value="all">모든 자료 (${total}문항)</option>
            ${mats.map((x) => `<option value="${x.id}" ${st.sel === x.id ? "selected" : ""}>${esc(x.filename)} (${problemsOf(x.id).length}문항)</option>`).join("")}</select></div>
          <div class="field"><label for="ex-n">문항 수</label><select id="ex-n" class="select">
            ${[["all", "전체"], ["10", "10문항"], ["20", "20문항"], ["30", "30문항"]].map(([v, t]) => `<option value="${v}">${t}</option>`).join("")}</select></div>
          <label class="check"><input type="checkbox" id="ex-shuffle" /> 문항 순서 섞기</label>
          <div class="field"><label>어떻게 볼까요?</label><div class="seg ex-mode">
            <button type="button" data-ex-mode="take" class="on"><i data-lucide="timer"></i>화면에서 시험 보기</button>
            <button type="button" data-ex-mode="print"><i data-lucide="printer"></i>인쇄용 시험지</button></div></div>
          <div data-ex-pane="take">${takeFields()}</div>
          <div data-ex-pane="print" hidden><label class="check"><input type="checkbox" id="ex-key" checked /> 마지막 장에 정답표 넣기</label></div>`,
        onMount: (f) => bindModeSeg(f),
        onSubmit: (f) => {
          const take = $("[data-ex-mode].on", f).dataset.exMode === "take";
          const q = new URLSearchParams({ m: $("#ex-scope", f).value, n: $("#ex-n", f).value });
          if ($("#ex-shuffle", f).checked) q.set("seed", String(Math.floor(Math.random() * 1e9)));
          if (take) readTake(f, q); else q.set("key", $("#ex-key", f).checked ? "1" : "0");
          go(`/exam/${id}?${q}`);
        },
      });
    }

    function fileMenu(anchor, mid) {
      const m = data.materials.find((x) => x.id === mid), af = answerFileOf(mid);
      const ready = m.status === "ready" && m.problem_count;
      openMenu(anchor, [
        { label: m.filename, header: true },
        ready && { icon: "link-2", label: af ? "정답 파일 바꾸기" : "정답 파일 연결", run: () => uploadAnswerFile(id, mid, load) },
        ready && m.answer_key_status === "done" && { icon: "file-check-2", label: "정답지 보기", run: () => go(`/answer-key/${mid}`) },
        ready && m.answer_key_status !== "running" && { icon: "file-pen-line", label: m.answer_key_status === "done" ? "정답지 다시 만들기" : "정답지 만들기", run: () => makeAnswerKey(mid).catch((err) => { toast(err.message); load(); }) },
        "-",
        af && { icon: "unlink", label: "정답 파일 빼기", danger: true, run: () => confirmModal({
          title: "정답 파일을 뺄까요?", text: "정답 파일에서 가져온 정답과 해설을 거두고, 시험지에 인쇄돼 있던 정답으로 돌아가요.", action: "빼기",
          run: async () => { try { await Store.deleteMaterial(af.id); toast("정답 파일을 뺐어요"); } catch (err) { toast(err.message); } load(); } }) },
        { icon: "trash-2", label: "자료 삭제", danger: true, run: () => confirmModal({
          title: "올린 자료를 삭제할까요?", text: "원본 파일과 AI가 읽어 둔 문항, 연결된 정답 파일이 삭제돼요. 그것으로 만든 문제와 풀이 기록은 남아요.",
          run: async () => { try { await Store.deleteMaterial(mid); toast("삭제했어요"); } catch (err) { toast(err.message); } load(); } }) },
      ]);
    }

    view.onclick = async (e) => {
      const el = (s) => e.target.closest(s);
      let x;
      if (el("[data-ws-upload]")) return uploadSheet(id, load);
      if ((x = el("[data-ws-menu]"))) { e.stopPropagation(); return fileMenu(x, x.dataset.wsMenu); }
      if ((x = el("[data-ws-sel]"))) { st.sel = x.dataset.wsSel; st.open.clear(); drawFiles(); drawSheet(); icons(); if (st.view === "erd") requestAnimationFrame(drawErdLines); return; }
      if ((x = el("[data-ws-view]"))) { st.view = x.dataset.wsView; drawSheet(); icons(); if (st.view === "erd") requestAnimationFrame(drawErdLines); return; }
      if ((x = el("[data-ws-row]"))) { const k = x.dataset.wsRow; st.open.has(k) ? st.open.delete(k) : st.open.add(k); drawSheet(); icons(); return; }
      if ((x = el("[data-attach-answer]"))) return uploadAnswerFile(id, x.dataset.attachAnswer, load);
      if ((x = el("[data-erd-ans]"))) return editAnswer(x.dataset.erdAns);
      if ((x = el("[data-erd-num]"))) return editNumber(x.dataset.erdNum);
      if ((x = el("[data-ak-make]"))) { x.disabled = true; return makeAnswerKey(x.dataset.akMake).catch((err) => { toast(err.message); load(); }); }
      if (el("[data-exam]")) return examOptions();
      if ((x = el("[data-level]"))) { $$("#gen-level [data-level]").forEach((b) => b.classList.toggle("on", b === x)); return; }
      if (el("#gen-go")) {
        const btn = $("#gen-go"), level = $("#gen-level .on").dataset.level, count = Number($("#gen-count").value);
        btn.disabled = true;
        try {
          const sid = await withAIProgress({
            title: `기출을 닮은 문제 ${count}개를 만드는 중`,
            steps: ["기출 스타일 분석", "새 문제 만들기", "다른 AI가 다시 풀어 검산", "화면 준비"], expectMs: 35000,
            run: () => Store.generateFromPast(id, { level, count }),
          });
          toast("새 문제를 만들었어요");
          go(`/chat/${sid}`);
        } catch (err) { toast(err.message); if (here()) { btn.disabled = false; $("#gen-status").textContent = err.message; } }
      }
    };
    view.onkeydown = (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const t = e.target.closest("[data-ws-sel], [data-ws-row]");
      if (t && !e.target.closest("button")) { e.preventDefault(); t.click(); }
    };
    if (openExam) { history.replaceState(null, "", `#/project/${id}`); openExamOnLoad = true; }
    const ro = new ResizeObserver(() => { if (st.view === "erd" && here()) drawErdLines(); });
    ro.observe($("#ws-sheet"));
    load();
  }

  // ================= 시험지 (올린 문제로 실제 시험지 형태) =================
  const seeded = (seed) => () => { seed |= 0; seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  async function renderExamPaper(projectId, params) {
    const p = Store.project(projectId);
    if (!p) { toast("프로젝트를 찾을 수 없어요"); return go("/"); }
    view.innerHTML = '<p class="mini">시험지를 준비하는 중…</p>';
    let w;
    try { w = await Store.workspace(projectId); } catch (e) { view.innerHTML = `<p class="mini">${esc(e.message)}</p>`; return; }
    if (route().parts[0] !== "exam") return;
    const scope = params.get("m") ?? "all";
    const only = params.get("ids") ? new Set(params.get("ids").split(",")) : null;
    let list = w.problems.filter((q) => (scope === "all" || q.material_id === scope) && (!only || only.has(q.id)));
    if (params.get("seed")) {
      const rnd = seeded(Number(params.get("seed")));
      list = list.map((q) => [rnd(), q]).sort((a, b) => a[0] - b[0]).map(([, q]) => q);
    }
    const nParam = params.get("n");
    if (nParam && nParam !== "all") list = list.slice(0, Number(nParam));
    const withKey = params.get("key") !== "0";
    const pts = (q) => (q.difficulty >= 4 ? 4 : q.difficulty >= 2 ? 3 : 2);
    const totalPts = list.reduce((a, q) => a + pts(q), 0);
    const minutes = Math.max(10, Math.round(list.length * 3));
    const subject = concept(p.subjectId)?.name ?? "";
    const year = new Date().getFullYear() + 1;
    const scopeName = scope === "all" ? "" : w.materials.find((x) => x.id === scope)?.filename ?? "";
    if (params.get("take") === "1") return renderExamTake({ p, list, params, pts, subject, scopeName });

    view.innerHTML = `
      <div class="exam-toolbar print-hide">
        <a class="ak-back" href="#/project/${projectId}"><i data-lucide="arrow-left"></i>프로젝트로</a>
        <span class="mini">${list.length}문항 · ${totalPts}점${scopeName ? ` · ${esc(scopeName)}` : ""}</span>
        <div class="page-actions">
          <button class="btn-ghost" data-exam-shuffle><i data-lucide="shuffle"></i>다시 섞기</button>
          ${list.length ? '<button class="btn-ghost" data-exam-take><i data-lucide="timer"></i>화면에서 시험 보기</button>' : ""}
          <button class="btn-primary" data-exam-print><i data-lucide="printer"></i>인쇄 · PDF 저장</button>
        </div>
      </div>
      ${!list.length ? '<div class="empty"><i data-lucide="file-x"></i><b>시험지에 넣을 문항이 없어요</b></div>' : `
      <article class="exam-paper">
        <header class="exam-cover">
          <div class="exam-kicker">${year}학년도 대비 · Eureka 모의시험</div>
          <h1>${esc(subject || p.name)} 영역</h1>
          <div class="exam-name">${esc(p.name)}</div>
          <table class="exam-id"><tr><th>성명</th><td></td><th>수험번호</th><td></td><th>점수</th><td></td></tr></table>
          <div class="exam-info"><span>${list.length}문항</span><span>${totalPts}점 만점</span><span>시험 시간 ${minutes}분</span></div>
          <ul class="exam-rules"><li>문항에 따라 배점이 다르니 각 물음 끝의 배점을 참고하세요.</li><li>답은 문제지 여백이나 별도 답안지에 쓰고, 마지막 장의 정답표로 채점하세요.</li></ul>
        </header>
        <div class="exam-body">
          ${list.map((q, i) => `
            <section class="exam-q">
              <div class="exam-qh"><b>${i + 1}.</b><span data-math>${esc(q.stem)}</span><em class="exam-pts">[${pts(q)}점]</em></div>
              ${q.choices ? `<ol class="exam-choices ${q.choices.every((c) => c.length <= 8) ? "inline" : ""}">${q.choices.map((c, k) => `<li><span class="c">${CIRC[k]}</span><span data-math>${esc(c)}</span></li>`).join("")}</ol>`
                : '<div class="exam-blank">답 : <span></span></div>'}
              ${q.needs_figure ? `<p class="exam-note">※ 그림이 필요한 문항이에요. 원본 시험지를 함께 보세요. <button class="link-btn print-hide" data-orig="${q.material_id}" data-page="${q.page ?? ""}">원본 보기${q.page ? ` (${q.page}쪽)` : ""}</button></p>` : ""}
            </section>`).join("")}
        </div>
        <footer class="exam-foot">— 끝 —</footer>
      </article>
      ${withKey ? `
      <article class="exam-paper exam-key">
        <h2>정답표</h2>
        <p class="mini">${esc(p.name)} · ${list.length}문항 · 정답이 확인되지 않은 문항은 '–'</p>
        <div class="exam-key-grid">${list.map((q, i) => `<div><span>${i + 1}</span><b data-math>${esc(hasAnswer(q) ? ansLabel(q) : "–")}</b></div>`).join("")}</div>
      </article>` : ""}`}`;
    icons();
    view.onclick = (e) => {
      if (e.target.closest("[data-exam-print]")) return window.print();
      const o = e.target.closest("[data-orig]");
      if (o) return openOriginal(o.dataset.orig, o.dataset.page);
      if (e.target.closest("[data-exam-take]")) return takeOptions(projectId, params);
      if (e.target.closest("[data-exam-shuffle]")) {
        const q = new URLSearchParams(params);
        q.set("seed", String(Math.floor(Math.random() * 1e9)));
        location.hash = `#/exam/${projectId}?${q}`;
      }
    };
  }

  // ================= 시험 기록 · 점수 추이 =================
  const mmss = (sec) => `${Math.floor(sec / 60)}:${String(Math.round(sec) % 60).padStart(2, "0")}`;
  // 점수(%) 꺾은선 — 오래된 것부터 왼쪽
  function trendSVG(rows) {
    const pts = rows.filter((r) => r.rate != null).slice(0, 30).reverse();
    if (pts.length < 2) return "";
    const W = 1000, H = 170, L = 34, Rr = 12, T = 14, B = 26;
    const x = (i) => L + (i * (W - L - Rr)) / (pts.length - 1), y = (v) => T + (1 - v) * (H - T - B);
    const line = pts.map((r, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(r.rate).toFixed(1)}`).join(" ");
    const best = Math.max(...pts.map((r) => r.rate));
    return `
      <svg class="trend" viewBox="0 0 ${W} ${H}" role="img" aria-label="시험 점수 추이, 최근 ${Math.round(pts.at(-1).rate * 100)}%">
        ${[0, 0.5, 1].map((v) => `<line x1="${L}" x2="${W - Rr}" y1="${y(v)}" y2="${y(v)}" class="grid"/><text x="${L - 6}" y="${y(v) + 4}" class="ax" text-anchor="end">${v * 100}</text>`).join("")}
        <path d="${line} L${x(pts.length - 1)},${y(0)} L${x(0)},${y(0)} Z" class="area"/>
        <path d="${line}" class="ln"/>
        ${pts.map((r, i) => `<circle cx="${x(i)}" cy="${y(r.rate)}" r="${r.rate === best ? 5 : 3.5}" class="${r.rate === best ? "best" : ""}"><title>${new Date(r.created_at).toLocaleDateString("ko-KR")} · ${Math.round(r.rate * 100)}%</title></circle>`).join("")}
        <text x="${L}" y="${H - 6}" class="ax">${new Date(pts[0].created_at).toLocaleDateString("ko-KR", { month: "numeric", day: "numeric" })}</text>
        <text x="${W - Rr}" y="${H - 6}" class="ax" text-anchor="end">${new Date(pts.at(-1).created_at).toLocaleDateString("ko-KR", { month: "numeric", day: "numeric" })}</text>
      </svg>`;
  }
  async function drawExamHistory(projectId, el) {
    if (!el || el.dataset.loaded) return;
    let rows;
    try { rows = await Store.listExams(projectId); } catch (err) { el.innerHTML = `<p class="mini">${esc(err.message)}</p>`; return; }
    el.dataset.loaded = "1";
    if (!rows.length) {
      el.innerHTML = '<p class="mini">아직 시험 기록이 없어요. 오른쪽 "시험 준비하기"에서 화면 시험을 보면 점수와 걸린 시간이 여기에 쌓여요</p>';
      return;
    }
    const rates = rows.filter((r) => r.rate != null).map((r) => r.rate);
    el.innerHTML = `
      <div class="exh-stats">
        <div><span>시험</span><b>${rows.length}번</b></div>
        <div><span>최근</span><b>${rates.length ? `${Math.round(rates[0] * 100)}%` : "–"}</b></div>
        <div><span>최고</span><b>${rates.length ? `${Math.round(Math.max(...rates) * 100)}%` : "–"}</b></div>
        <div><span>평균</span><b>${rates.length ? `${Math.round((rates.reduce((a, b) => a + b, 0) / rates.length) * 100)}%` : "–"}</b></div>
      </div>
      ${trendSVG(rows) || '<p class="mini">시험을 두 번 이상 보면 점수 추이 그래프가 나와요</p>'}
      <div class="exh-list">${rows.map((r) => `
        <a class="exh-row" href="#/exam-record/${r.id}">
          <span class="exh-rate ${r.rate >= 0.8 ? "ok" : r.rate < 0.5 ? "bad" : ""}">${r.rate == null ? "–" : `${Math.round(r.rate * 100)}%`}</span>
          <span class="exh-main"><b>${esc(r.title)}</b><small>${new Date(r.created_at).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })} · ${r.score}/${r.total_points}점 · ${r.correct}/${r.total}문항${r.auto_submitted ? " · 시간 초과 제출" : ""}</small></span>
          <span class="exh-time"><i data-lucide="timer"></i>${mmss(r.used_sec)}${r.time_limit_sec ? ` / ${Math.round(r.time_limit_sec / 60)}분` : ""}</span>
          <i data-lucide="chevron-right" class="go"></i>
        </a>`).join("")}</div>`;
    icons();
  }

  async function renderExamRecord(id) {
    view.innerHTML = '<p class="mini">시험 기록을 불러오는 중…</p>';
    let r;
    try { r = await Store.exam(id); } catch (err) { view.innerHTML = `<div class="empty"><i data-lucide="file-x"></i><b>${esc(err.message)}</b></div>`; icons(); return; }
    if (route().parts[0] !== "exam-record") return;
    const label = (it, a) => (a ? (it.choices ? CIRC[Number(a) - 1] ?? a : a) : "–");
    const maxSec = Math.max(1, ...r.items.map((i) => i.sec));
    const avg = r.items.reduce((a, i) => a + i.sec, 0) / r.items.length;
    const wrong = r.items.filter((i) => i.correct === false).map((i) => i.problem_id);
    const slow = [...r.items].map((it, k) => ({ ...it, k })).sort((a, b) => b.sec - a.sec).slice(0, 3);
    view.innerHTML = `
      <div class="xt-result">
        ${r.project_id ? `<a class="ak-back" href="#/project/${r.project_id}?tab=exams"><i data-lucide="arrow-left"></i>시험 기록</a>` : ""}
        <div class="xt-score panel">
          <span>${esc(r.title)} · ${new Date(r.created_at).toLocaleString("ko-KR")}</span>
          <b>${r.score}<small> / ${r.total_points}점</small></b>
          <div class="xt-stats"><div><span>맞힌 문항</span><b>${r.correct}/${r.total}</b></div>
            <div><span>걸린 시간</span><b>${mmss(r.used_sec)}${r.time_limit_sec ? `<small> / ${Math.round(r.time_limit_sec / 60)}분</small>` : ""}</b></div>
            <div><span>문항당 평균</span><b>${mmss(avg)}</b></div>
            <div><span>안 푼 문항</span><b>${r.skipped}</b></div></div>
          ${r.auto_submitted ? '<p class="mini">시간이 다 돼서 저절로 제출된 시험이에요</p>' : ""}
          <div class="page-actions">
            ${wrong.length && r.project_id ? '<button class="btn-primary" data-er-retry><i data-lucide="rotate-ccw"></i>틀린 문항만 다시 풀기</button>' : ""}
            <button class="btn-ghost danger-text" data-er-del><i data-lucide="trash-2"></i>기록 삭제</button>
          </div>
        </div>
        <div class="panel xt-slow"><h3><i data-lucide="hourglass"></i>시간이 오래 걸린 문항</h3>
          <div class="xt-slow-list">${slow.map((it) => `<div><b>${it.k + 1}번</b><span>${mmss(it.sec)}</span><small>${it.correct ? "맞음" : !it.my ? "안 풂" : it.correct === false ? "틀림" : "채점 못 함"}</small></div>`).join("")}</div></div>
        <div class="panel xt-table"><h3><i data-lucide="list-checks"></i>문항별 결과 · 걸린 시간</h3>
          ${r.items.map((it, k) => `<div class="xt-row ${it.correct ? "ok" : it.correct === false ? "bad" : ""}">
            <b>${k + 1}</b><span class="xt-st"><i data-lucide="${it.correct ? "circle-check" : it.correct === false ? "circle-x" : "circle-help"}"></i>${it.correct ? "맞음" : !it.my ? "안 풂" : it.correct === false ? "틀림" : "채점 못 함"}</span>
            <span class="xt-stem1" data-math>${esc((it.stem || "").slice(0, 80))}</span>
            <span class="xt-ans">내 답 <b data-math>${esc(label(it, it.my))}</b> · 정답 <b data-math>${esc(label(it, it.answer))}</b></span>
            <span class="xt-secbar ${it.sec > avg * 1.5 ? "slow" : ""}"><i style="width:${(it.sec / maxSec) * 100}%"></i><em>${mmss(it.sec)}</em></span></div>`).join("")}
        </div>
      </div>`;
    icons();
    view.onclick = (e) => {
      if (e.target.closest("[data-er-retry]")) return go(`/exam/${r.project_id}?${new URLSearchParams({ m: r.scope || "all", take: "1", per: String(r.per), t: "0", ids: wrong.join(",") })}`);
      if (e.target.closest("[data-er-del]")) return confirmModal({ title: "이 시험 기록을 지울까요?", text: "점수 추이에서도 빠져요. 문제 풀이 기록과 오답노트는 그대로 남아요.",
        run: async () => { try { await Store.deleteExam(id); toast("시험 기록을 지웠어요"); go(r.project_id ? `/project/${r.project_id}?tab=exams` : "/"); } catch (err) { toast(err.message); } } });
    };
  }

  // ================= 화면에서 시험 보기 =================
  // 한 문제씩 / 4문제씩, 타이머(선택) — 제출하면 바로 채점하고 틀린 문항은 오답노트에 담긴다
  const takeFields = (n = 0) => `
    <div class="field"><label>한 화면에</label><div class="seg ex-per">
      <button type="button" data-per="1" class="on">한 문제씩</button><button type="button" data-per="4">4문제씩</button></div></div>
    <div class="field ex-timer"><label class="check"><input type="checkbox" id="ex-timer" checked /> 타이머 켜기</label>
      <select id="ex-min" class="select">${[10, 20, 30, 40, 50, 60, 80, 100].map((m) => `<option value="${m}" ${m === Math.min(100, Math.max(10, Math.round(n * 3 / 10) * 10 || 30)) ? "selected" : ""}>${m}분</option>`).join("")}</select></div>`;
  function bindModeSeg(f) {
    f.addEventListener("click", (e) => {
      const b = e.target.closest("[data-ex-mode], [data-per]");
      if (!b) return;
      $$(b.dataset.exMode ? "[data-ex-mode]" : "[data-per]", f).forEach((x) => x.classList.toggle("on", x === b));
      if (b.dataset.exMode) {
        $$("[data-ex-pane]", f).forEach((x) => (x.hidden = x.dataset.exPane !== b.dataset.exMode));
        const sub = $("[type=submit]", f);
        if (sub) sub.textContent = b.dataset.exMode === "take" ? "시험 시작" : "시험지 보기";
      }
    });
    const t = $("#ex-timer", f), m = $("#ex-min", f);
    if (t) t.onchange = () => (m.disabled = !t.checked);
  }
  function readTake(f, q) {
    q.set("take", "1");
    q.set("per", $("[data-per].on", f).dataset.per);
    q.set("t", $("#ex-timer", f).checked ? $("#ex-min", f).value : "0");
  }
  function takeOptions(projectId, base, title = "화면에서 시험 보기") {
    const n = base.get("ids") ? base.get("ids").split(",").length : 0;
    formModal({
      title, submit: "시작",
      body: takeFields(n) + '<p class="mini">답을 고르면 저절로 저장돼요. 제출하면 바로 채점하고, 틀린 문항은 오답노트에 담아요.</p>',
      onMount: (f) => bindModeSeg(f),
      onSubmit: (f) => {
        const q = new URLSearchParams(base);
        ["key", "take", "per", "t"].forEach((k) => q.delete(k));
        readTake(f, q);
        go(`/exam/${projectId}?${q}`);
      },
    });
  }
  // 정답지에서 '틀린 문항': 이 자료 문항 중 마지막으로 푼 것이 틀린 것
  function akWrong(key) {
    const ids = new Set(key.items.map((i) => i.id)), last = {};
    Store.state.attempts.forEach((a) => { if (ids.has(a.problemId)) last[a.problemId] = a.correct; });
    return Object.keys(last).filter((k) => last[k] === false);
  }
  async function openOriginal(materialId, page) {
    const win = window.open("", "_blank"); // 팝업 차단을 피하려고 먼저 연다
    try {
      const blob = await Store.materialBlob(materialId);
      const url = URL.createObjectURL(blob);
      if (blob.type.startsWith("image/")) {
        win?.close();
        openSheet({ title: "원본 보기", wide: true, body: `<img class="orig-img" src="${url}" alt="올린 원본" />`, onSubmit: () => {} });
      } else if (win) win.location.href = url + (page ? `#page=${page}` : "");
      else location.href = url;
    } catch (err) { win?.close(); toast(err.message); }
  }

  let takeTimer = null;
  function renderExamTake({ p, list, params, pts, subject, scopeName }) {
    clearInterval(takeTimer);
    if (!list.length) { view.innerHTML = '<div class="empty"><i data-lucide="file-x"></i><b>시험 볼 문항이 없어요</b></div>'; icons(); return; }
    const per = params.get("per") === "4" ? 4 : 1;
    const limit = Number(params.get("t") || 0) * 60_000;
    const KEY = `eureka.take.${p.id}.${list.map((q) => q.id).join(",").slice(0, 400)}`;
    const here = location.hash;
    let s = null;
    try { s = JSON.parse(sessionStorage.getItem(KEY)); } catch { /* 저장소 없음 */ }
    if (!s || s.done) s = { answers: {}, page: 0, startedAt: Date.now(), done: false };
    const save = () => { try { sessionStorage.setItem(KEY, JSON.stringify(s)); } catch { /* 무시 */ } };
    const pages = Math.ceil(list.length / per);
    const answered = () => list.filter((q) => (s.answers[q.id] ?? "") !== "").length;
    const left = () => Math.max(0, s.startedAt + limit - Date.now());
    const clock = (ms) => { const t = Math.ceil(ms / 1000); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`; };
    const totalPts = list.reduce((a, q) => a + pts(q), 0);

    const qHTML = (q, i) => {
      const my = s.answers[q.id] ?? "";
      return `
      <section class="xt-q" data-q="${q.id}">
        <div class="xt-qh"><b>${i + 1}</b><span class="xt-pts">${pts(q)}점</span>
          ${q.needs_figure ? `<button class="xt-orig" data-orig="${q.material_id}" data-page="${q.page ?? ""}"><i data-lucide="file-image"></i>원본 보기${q.page ? ` (${q.page}쪽)` : ""}</button>` : ""}</div>
        <p class="xt-stem" data-math>${esc(q.stem)}</p>
        ${q.needs_figure ? '<p class="exam-note">※ 그림이 필요한 문항이에요. 원본을 함께 보세요.</p>' : ""}
        ${q.choices ? `<div class="xt-choices">${q.choices.map((c, k) => `
          <button type="button" class="xt-c ${my === String(k + 1) ? "on" : ""}" data-pick="${k + 1}" aria-pressed="${my === String(k + 1)}"><span class="c">${CIRC[k]}</span><span data-math>${esc(c)}</span></button>`).join("")}</div>`
          : `<label class="xt-short"><span>답</span><input data-short value="${esc(my)}" maxlength="200" placeholder="답을 적어 주세요" autocomplete="off" /></label>`}
      </section>`;
    };

    // 문항별 시간: 한 화면에 머문 시간을 그 화면의 문항들에 나눠 더한다 (한 문제씩이면 그 문항의 시간)
    s.secs ??= {};
    let pageAt = Date.now();
    const tick = () => {
      const shown = list.slice(s.page * per, s.page * per + per), sec = (Date.now() - pageAt) / 1000;
      if (document.visibilityState === "visible") shown.forEach((q) => (s.secs[q.id] = (s.secs[q.id] ?? 0) + sec / shown.length));
      pageAt = Date.now();
    };
    function draw() {
      const from = s.page * per, shown = list.slice(from, from + per);
      view.innerHTML = `
        <div class="xt">
          <div class="xt-bar">
            <a class="ak-back" href="#/project/${p.id}" data-xt-leave><i data-lucide="x"></i>나가기</a>
            <div class="xt-title"><b>${esc(subject || p.name)}</b><span>${list.length}문항 · ${totalPts}점${scopeName ? ` · ${esc(scopeName)}` : ""}</span></div>
            <div class="xt-prog"><span>답한 문항 <b id="xt-done">${answered()}</b>/${list.length}</span><i><em style="width:${(answered() / list.length) * 100}%"></em></i></div>
            ${limit ? `<div class="xt-clock" id="xt-clock"><i data-lucide="timer"></i><b>${clock(left())}</b></div>` : `<div class="xt-clock off" id="xt-clock"><i data-lucide="clock"></i><b>${clock(Date.now() - s.startedAt)}</b></div>`}
            <button class="btn-primary" data-xt-submit><i data-lucide="send"></i>제출</button>
          </div>
          <div class="xt-omr" aria-label="문항 바로 가기">${list.map((q, i) => `<button class="${(s.answers[q.id] ?? "") !== "" ? "done" : ""} ${i >= from && i < from + per ? "cur" : ""}" data-jump="${i}">${i + 1}</button>`).join("")}</div>
          <div class="xt-body ${per === 4 ? "four" : "one"}">${shown.map((q, k) => qHTML(q, from + k)).join("")}</div>
          <div class="xt-nav">
            <button class="btn-ghost" data-xt-prev ${s.page === 0 ? "disabled" : ""}><i data-lucide="chevron-left"></i>이전</button>
            <span class="mini">${s.page + 1} / ${pages}</span>
            ${s.page < pages - 1 ? '<button class="btn-ghost" data-xt-next>다음<i data-lucide="chevron-right"></i></button>'
              : '<button class="btn-primary" data-xt-submit><i data-lucide="send"></i>제출하기</button>'}
          </div>
        </div>`;
      icons();
    }
    const refreshProgress = () => {
      $("#xt-done").textContent = answered();
      $(".xt-prog em").style.width = `${(answered() / list.length) * 100}%`;
      list.forEach((q, i) => $(`.xt-omr [data-jump="${i}"]`)?.classList.toggle("done", (s.answers[q.id] ?? "") !== ""));
    };
    const goPage = (n) => { tick(); s.page = Math.max(0, Math.min(pages - 1, n)); save(); draw(); view.scrollIntoView?.({ block: "start" }); };

    async function submit(auto = false) {
      if (s.done) return;
      clearInterval(takeTimer);
      tick();
      s.done = true;
      save();
      const usedMs = Date.now() - s.startedAt;
      view.innerHTML = '<div class="xt-grading"><i data-lucide="loader" class="spin"></i><b>채점하는 중…</b></div>';
      icons();
      Store.ensureProblems(list.map((q) => ({ ...q })));
      const rows = [];
      for (const q of list) {
        const my = (s.answers[q.id] ?? "").trim();
        if (!my) { rows.push({ q, my, correct: false, skipped: true, answer: q.answer }); continue; }
        try {
          const r = await Store.answer({ problemId: q.id, answer: my, projectId: p.id });
          rows.push({ q, my, correct: r.correct, answer: Store.problem?.(q.id)?.answer ?? q.answer });
        } catch (err) {
          rows.push({ q, my, correct: null, answer: q.answer, why: err.message });
        }
      }
      try { sessionStorage.removeItem(KEY); } catch { /* 무시 */ }
      rows.forEach((r) => (r.sec = Math.round(s.secs[r.q.id] ?? 0)));
      // 시험 기록 남기기 (점수 추이 · 오래 걸린 문항)
      let saved = null;
      if (Store.mode === "api") {
        try {
          saved = await Store.saveExam(p.id, {
            title: `${subject || p.name}${scopeName ? ` · ${scopeName}` : ""}${params.get("ids") ? " · 틀린 문항" : ""}`.slice(0, 200),
            scope: params.get("m") ?? "all", per, time_limit_sec: limit ? Math.round(limit / 1000) : null,
            used_sec: Math.round(usedMs / 1000), auto_submitted: auto,
            items: rows.map((r) => ({ problem_id: r.q.id, number: r.q.number ?? null, my: r.my, answer: r.answer ? String(r.answer).slice(0, 200) : null,
              correct: r.correct, points: pts(r.q), sec: r.sec })),
          });
        } catch (err) { toast(`시험 기록을 저장하지 못했어요: ${err.message}`); }
      }
      if (location.hash !== here) return;
      showResult(rows, usedMs, auto, saved);
    }

    function showResult(rows, usedMs, auto, saved = null) {
      const diff = saved?.previous_rate != null && saved.rate != null ? Math.round((saved.rate - saved.previous_rate) * 100) : null;
      const slow = rows.filter((r) => r.sec > 0).sort((a, b) => b.sec - a.sec).slice(0, 3);
      const mmss = (sec) => `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
      const graded = rows.filter((r) => r.correct !== null);
      const right = rows.filter((r) => r.correct);
      const score = right.reduce((a, r) => a + pts(r.q), 0);
      const wrongIds = rows.filter((r) => r.correct === false).map((r) => r.q.id);
      const label = (q, a) => (a ? (q.choices ? CIRC[Number(a) - 1] ?? a : a) : "–");
      view.innerHTML = `
        <div class="xt-result">
          <div class="xt-score panel">
            ${auto ? '<p class="mini"><i data-lucide="alarm-clock"></i> 시간이 다 돼서 저절로 제출했어요</p>' : ""}
            <span>${esc(subject || p.name)} · ${list.length}문항</span>
            <b>${score}<small> / ${totalPts}점</small></b>
            ${saved ? `<p class="xt-trend ${diff > 0 ? "up" : diff < 0 ? "down" : ""}">${diff == null ? "이 프로젝트의 첫 시험 기록이에요"
              : `지난번보다 <b>${diff > 0 ? "+" : ""}${diff}%p</b>${saved.best_rate != null && saved.rate > saved.best_rate ? " · 최고 기록!" : ""}`} · ${saved.attempts}번째 시험</p>` : ""}
            <div class="xt-stats"><div><span>맞힌 문항</span><b>${right.length}/${list.length}</b></div>
              <div><span>걸린 시간</span><b>${clock(usedMs)}</b></div>
              <div><span>안 푼 문항</span><b>${rows.filter((r) => r.skipped).length}</b></div></div>
            ${graded.length < rows.length - rows.filter((r) => r.skipped).length ? `<p class="mini">정답이 아직 없는 ${rows.length - graded.length - rows.filter((r) => r.skipped).length}문항은 채점하지 못했어요</p>` : ""}
            <div class="page-actions">
              ${wrongIds.length ? '<button class="btn-primary" data-xt-retry><i data-lucide="rotate-ccw"></i>틀린 문항만 다시 풀기</button>' : ""}
              ${wrongIds.length ? '<a class="btn-ghost" href="#/notes"><i data-lucide="circle-x"></i>오답노트 보기</a>' : ""}
              <button class="btn-ghost" data-xt-again><i data-lucide="refresh-cw"></i>처음부터 다시</button>
              ${saved ? `<a class="btn-ghost" href="#/project/${p.id}?tab=exams"><i data-lucide="trending-up"></i>점수 추이</a>` : ""}
              <a class="btn-ghost" href="#/project/${p.id}"><i data-lucide="folder"></i>프로젝트로</a>
            </div>
          </div>
          ${slow.length ? `<div class="panel xt-slow"><h3><i data-lucide="hourglass"></i>시간이 오래 걸린 문항</h3>
            <div class="xt-slow-list">${slow.map((r) => `<div><b>${rows.indexOf(r) + 1}번</b><span>${mmss(r.sec)}</span><small>${r.correct ? "맞음" : r.skipped ? "안 풂" : r.correct === false ? "틀림" : "채점 못 함"}</small></div>`).join("")}</div>
            <p class="mini">평균 ${mmss(Math.round(rows.reduce((a, r) => a + r.sec, 0) / rows.length))} · 오래 걸렸는데 틀린 문항부터 다시 보면 좋아요</p></div>` : ""}
          <div class="panel xt-table"><h3><i data-lucide="list-checks"></i>문항별 결과</h3>
            ${rows.map((r, i) => `<div class="xt-row ${r.correct ? "ok" : r.correct === false ? "bad" : ""}">
              <b>${i + 1}</b><span class="xt-st"><i data-lucide="${r.correct ? "circle-check" : r.correct === false ? "circle-x" : "circle-help"}"></i>${r.correct ? "맞음" : r.skipped ? "안 풂" : r.correct === false ? "틀림" : "채점 못 함"}</span>
              <span class="xt-stem1" data-math>${esc(r.q.stem.slice(0, 80))}</span>
              <span class="xt-ans">내 답 <b data-math>${esc(label(r.q, r.my))}</b></span>
              <span class="xt-ans">정답 <b data-math>${esc(label(r.q, r.answer))}</b></span>
              <span class="xt-ans xt-sec">${mmss(r.sec)}</span></div>`).join("")}
          </div>
        </div>`;
      icons();
      view.onclick = (e) => {
        if (e.target.closest("[data-xt-retry]")) {
          const q = new URLSearchParams(params);
          q.set("ids", wrongIds.join(","));
          q.delete("seed");
          return go(`/exam/${p.id}?${q}`);
        }
        if (e.target.closest("[data-xt-again]")) return renderExamTake({ p, list, params, pts, subject, scopeName });
      };
    }

    draw();
    takeTimer = setInterval(() => {
      if (location.hash !== here || s.done) return clearInterval(takeTimer);
      const c = $("#xt-clock b");
      if (!c) return;
      if (limit) {
        const ms = left();
        c.textContent = clock(ms);
        $("#xt-clock").classList.toggle("warn", ms <= 5 * 60_000);
        if (ms <= 0) submit(true);
      } else c.textContent = clock(Date.now() - s.startedAt);
    }, 1000);
    if (limit && left() <= 0) return submit(true);

    view.onclick = (e) => {
      let x;
      if ((x = e.target.closest("[data-orig]"))) return openOriginal(x.dataset.orig, x.dataset.page);
      if ((x = e.target.closest("[data-pick]"))) {
        const id = x.closest("[data-q]").dataset.q;
        s.answers[id] = s.answers[id] === x.dataset.pick ? "" : x.dataset.pick; // 다시 누르면 지움
        save();
        $$(`[data-q="${CSS.escape(id)}"] [data-pick]`).forEach((b) => { const on = b.dataset.pick === s.answers[id]; b.classList.toggle("on", on); b.setAttribute("aria-pressed", on); });
        refreshProgress();
        if (per === 1 && s.answers[id] && s.page < pages - 1) setTimeout(() => goPage(s.page + 1), 260);
        return;
      }
      if ((x = e.target.closest("[data-jump]"))) return goPage(Math.floor(Number(x.dataset.jump) / per));
      if (e.target.closest("[data-xt-prev]")) return goPage(s.page - 1);
      if (e.target.closest("[data-xt-next]")) return goPage(s.page + 1);
      if (e.target.closest("[data-xt-leave]")) {
        e.preventDefault();
        return confirmModal({ title: "시험을 그만둘까요?", text: "고른 답은 이 창을 닫기 전까지 남아 있어서, 다시 들어오면 이어서 풀 수 있어요.", action: "나가기",
          run: () => { clearInterval(takeTimer); go(`/project/${p.id}`); } });
      }
      if (e.target.closest("[data-xt-submit]")) {
        const miss = list.length - answered();
        if (!miss) return submit();
        return confirmModal({ title: "제출할까요?", text: `아직 답하지 않은 문항이 ${miss}개 있어요. 안 푼 문항은 틀린 것으로 계산해요.`, action: "제출",
          run: () => submit() });
      }
    };
    view.oninput = (e) => {
      const inp = e.target.closest("[data-short]");
      if (!inp || location.hash !== here) return;
      s.answers[inp.closest("[data-q]").dataset.q] = inp.value;
      save();
      refreshProgress();
    };
    view.onkeydown = (e) => {
      if (location.hash !== here || s.done) return;
      if (e.target.closest("input")) { if (e.key === "Enter" && s.page < pages - 1) goPage(s.page + 1); return; }
      if (e.key === "ArrowRight") goPage(s.page + 1);
      else if (e.key === "ArrowLeft") goPage(s.page - 1);
      else if (per === 1 && /^[1-5]$/.test(e.key)) $(`.xt-q [data-pick="${e.key}"]`)?.click();
    };
  }

  // ================= AI 작업 진행 팝업 =================
  // 배경을 흐리게 덮고, 회전하는 원형 진행률과 단계를 보여 준다. 서버 처리가 끝나야 닫히고 결과를 연다.
  // - p.set(0~1): 서버가 알려 준 실제 진행률 (정답지·업로드처럼)  - p.step(i): 단계 표시
  // - 실제 진행률이 없으면 예상 시간(expectMs)에 맞춰 90%까지 천천히 차오르고, 응답이 오면 100%
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  function withAIProgress({ title, steps = ["준비하기", "AI가 처리하기", "결과 정리하기"], expectMs = 20000, run }) {
    const R = 52, LEN = 2 * Math.PI * R;
    const el = document.createElement("div");
    el.className = "ai-progress";
    el.setAttribute("role", "dialog");
    el.setAttribute("aria-modal", "true");
    el.setAttribute("aria-label", title);
    el.innerHTML = `
      <div class="ai-card">
        <div class="ai-ring">
          <svg viewBox="0 0 120 120" aria-hidden="true">
            <defs><linearGradient id="ai-grad" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stop-color="#4fc3ff"/><stop offset=".5" stop-color="#6b7cff"/><stop offset="1" stop-color="#c06bff"/></linearGradient></defs>
            <circle cx="60" cy="60" r="${R}" class="track"/>
            <circle cx="60" cy="60" r="${R}" class="bar" stroke-dasharray="${LEN}" stroke-dashoffset="${LEN}"/>
          </svg>
          <div class="ai-pct"><b>0</b><small>%</small></div>
        </div>
        <h2>${esc(title)}</h2>
        <p class="ai-now" aria-live="polite"></p>
        <ol class="ai-steps">${steps.map((s) => `<li><i></i><span>${esc(s)}</span></li>`).join("")}</ol>
        <p class="ai-foot">처리가 끝나면 결과를 바로 보여 드려요</p>
      </div>`;
    document.body.append(el);
    requestAnimationFrame(() => el.classList.add("in"));

    const bar = $(".bar", el), pctEl = $(".ai-pct b", el), nowEl = $(".ai-now", el), items = $$(".ai-steps li", el);
    const t0 = performance.now();
    let real = null, shown = 0, stepIdx = 0, stepForced = false, finished = false, raf;
    const paint = () => {
      const t = performance.now() - t0;
      const est = 0.9 * (1 - Math.exp(-t / (expectMs / 2.2)));  // 예상 시간의 약 90% 시점에 80%쯤
      const target = finished ? 1 : Math.min(0.97, Math.max(real ?? 0, real == null ? est : 0));
      shown += (target - shown) * (finished ? 0.25 : 0.06);
      if (finished && 1 - shown < 0.004) shown = 1;
      bar.style.strokeDashoffset = LEN * (1 - shown);
      pctEl.textContent = Math.round(shown * 100);
      if (!stepForced && !finished) stepIdx = Math.min(steps.length - 1, Math.floor(shown * steps.length * 1.05));
      items.forEach((li, i) => li.className = finished || i < stepIdx ? "done" : i === stepIdx ? "now" : "");
      nowEl.textContent = finished ? "완료했어요" : `${steps[stepIdx]}…`;
      if (!finished || shown < 1) raf = requestAnimationFrame(paint);
    };
    raf = requestAnimationFrame(paint);

    // 마우스를 따라 카드가 살짝 기울어진다
    const card = $(".ai-card", el);
    const tilt = (e) => {
      if (reduceMotion) return;
      const r = card.getBoundingClientRect();
      const dx = (e.clientX - (r.left + r.width / 2)) / innerWidth, dy = (e.clientY - (r.top + r.height / 2)) / innerHeight;
      card.style.transform = `perspective(900px) rotateY(${dx * 14}deg) rotateX(${-dy * 14}deg)`;
    };
    el.addEventListener("pointermove", tilt);

    const p = {
      set: (x) => { real = Math.max(0, Math.min(1, x)); },
      step: (i) => { stepForced = true; stepIdx = Math.max(stepIdx, Math.min(steps.length - 1, i)); },
    };
    const close = () => new Promise((resolve) => {
      el.classList.remove("in");
      el.classList.add("out");
      setTimeout(() => { cancelAnimationFrame(raf); el.remove(); resolve(); }, 260);
    });
    const minShow = new Promise((r) => setTimeout(r, 650)); // 너무 빨리 끝나도 깜빡이지 않게
    return Promise.resolve().then(() => run(p)).then(async (result) => {
      await minShow;
      finished = true;
      await new Promise((r) => setTimeout(r, 520));
      await close();
      return result;
    }, async (err) => { await close(); throw err; });
  }

  // 서버 작업이 끝날 때까지 몇 초마다 확인 (onTick 으로 진행률 반영)
  async function waitFor(fetch, done, { every = 2500, timeout = 10 * 60_000, onTick } = {}) {
    const end = Date.now() + timeout;
    for (;;) {
      const v = await fetch();
      onTick?.(v);
      if (done(v)) return v;
      if (Date.now() > end) throw new Error("시간이 오래 걸리고 있어요. 잠시 후 다시 확인해 주세요");
      await new Promise((r) => setTimeout(r, every));
    }
  }

  // 정답지 만들기: 실제 진행률(풀이를 마친 문항 수)을 보여 주고, 끝나면 정답지를 연다
  function makeAnswerKey(materialId) {
    return withAIProgress({
      title: "정답지를 만드는 중",
      steps: ["문항 읽기", "문항마다 직접 풀기", "정답표와 맞춰 보고 검산", "해설 정리"], expectMs: 90000,
      run: async (p) => {
        await Store.startAnswerKey(materialId);
        p.step(1);
        const key = await waitFor(() => Store.answerKey(materialId), (k) => k.material.answer_key_status !== "running", {
          every: 3000,
          onTick: (k) => {
            const total = k.material.problem_count || k.items.length || 1;
            p.set(0.05 + 0.9 * (k.material.answer_key_done / total));
            if (k.material.answer_key_done) p.step(k.material.answer_key_done >= total ? 3 : 2);
          },
        });
        if (key.material.answer_key_status === "failed") throw new Error(key.material.answer_key_error ?? "정답지를 만들지 못했어요");
        return key;
      },
    }).then(() => (location.hash === `#/answer-key/${materialId}` ? renderAnswerKey(materialId) : go(`/answer-key/${materialId}`)));
  }

  // ================= 정답지 =================
  const CIRC = "①②③④⑤⑥⑦⑧⑨";
  const AK_STATUS = {
    manual: ["직접 입력", "user-check", "ok", "정답 연결 화면에서 직접 고친 정답이에요"],
    sheet: ["정답표", "file-check", "ok", ""],
    confirmed: ["정답 확인", "badge-check", "ok", "시험지 정답과 AI 풀이가 같아요"],
    verified: ["검산 완료", "badge-check", "ok", "두 번 풀어 같은 답이 나왔어요"],
    conflict: ["정답표와 다름", "triangle-alert", "warn", "시험지 정답과 AI 풀이가 달라요. 한 번 확인해 주세요"],
    uncertain: ["확인 필요", "circle-help", "warn", "두 번 푼 답이 달라요. 한 번 확인해 주세요"],
    failed: ["풀이 실패", "circle-x", "bad", "이 문항은 풀지 못했어요"],
    none: ["아직 없음", "circle-dashed", "", ""],
  };
  const akLabel = (it, a = it.answer) => (!a ? "–" : it.choices ? `${CIRC[Number(a) - 1] ?? a}` : texAns(a));
  let akTimer = null;

  async function renderAnswerKey(materialId) {
    clearTimeout(akTimer);
    view.innerHTML = '<p class="mini">정답지를 불러오는 중…</p>';
    let key;
    try { key = await Store.answerKey(materialId); } catch (e) { view.innerHTML = `<div class="empty"><i data-lucide="file-x"></i><b>${esc(e.message)}</b></div>`; icons(); return; }
    if (route().parts[0] !== "answer-key" || route().parts[1] !== materialId) return;
    const mat = key.material, c = key.counts;
    const running = mat.answer_key_status === "running";
    const has = key.items.some((i) => i.status !== "none");
    const need = (c.conflict ?? 0) + (c.uncertain ?? 0) + (c.failed ?? 0);

    view.innerHTML = `
      <div class="ak-card">
      <div class="page-head ak-head">
        <div>
          <a class="ak-back" href="#/project/${mat.project_id}"><i data-lucide="arrow-left"></i>프로젝트로</a>
          <h1><i data-lucide="file-check-2"></i>정답지</h1>
          <p>${esc(mat.filename)} · ${key.items.length}문항${mat.answer_key_at ? ` · ${relTime(Date.parse(mat.answer_key_at))} 만듦` : ""}</p>
          ${key.answer_file ? `<p class="ak-file"><i data-lucide="link-2"></i>정답 파일 <b>${esc(key.answer_file.filename)}</b>${key.answer_file.map ? ` · ${key.answer_file.map.matched}/${key.answer_file.map.total}문항 1:1 연결` : ""}</p>` : ""}
        </div>
        <div class="page-actions ak-actions">
          ${has && !running ? `<button class="btn-ghost" data-ak-take><i data-lucide="timer"></i>이 문제지로 시험 보기</button>
            ${akWrong(key).length ? `<button class="btn-ghost" data-ak-retry><i data-lucide="rotate-ccw"></i>틀린 문항만 다시 풀기 (${akWrong(key).length})</button>` : ""}
            <button class="btn-ghost" data-ak-rebuild><i data-lucide="refresh-cw"></i>다시 만들기</button>
            <button class="btn-primary" data-ak-print><i data-lucide="printer"></i>인쇄 · PDF 저장</button>` : ""}
        </div>
      </div>
      ${has ? `
        <div class="ak-summary">
          <span class="ak-chip ok"><i data-lucide="badge-check"></i>정답 확인 ${(c.confirmed ?? 0) + (c.verified ?? 0) + (c.sheet ?? 0) + (c.manual ?? 0)}</span>
          ${need ? `<span class="ak-chip warn"><i data-lucide="triangle-alert"></i>확인 필요 ${need}</span>` : '<span class="ak-chip">모든 문항이 확인됐어요</span>'}
          <span class="mini">정답표가 있던 문항은 AI 풀이와 맞춰 봤고, 없던 문항은 두 번 풀어 비교했어요</span>
        </div>
      ` : ""}
      </div>
      ${running ? `<div class="ak-progress panel"><i data-lucide="loader" class="spin"></i><div><b>정답지를 만들고 있어요</b><p>문항마다 직접 풀고, 정답표가 없는 문항은 한 번 더 풀어 검산해요. 문항 수에 따라 1~3분 정도 걸려요.</p></div></div>` : ""}
      ${!has && !running ? `<div class="empty"><i data-lucide="file-pen-line"></i><b>${mat.answer_key_status === "failed" ? esc(mat.answer_key_error ?? "정답지를 만들지 못했어요") : "아직 정답지가 없어요"}</b>
        <p>문항마다 정답과 단계별 해설을 만들고, 정답표가 없는 문항은 한 번 더 풀어 검산해요.</p>
        <button class="btn-primary" data-ak-start><i data-lucide="sparkles"></i>정답지 만들기</button></div>` : ""}
      ${has ? `
        <section class="panel ak-quick">
          <h3><i data-lucide="table-2"></i>빠른 정답</h3>
          <div class="ak-grid">${key.items.map((it, n) => `
            <a href="#ak-${it.id}" class="ak-cell ${AK_STATUS[it.status][2]}" data-ak-jump="${it.id}" title="${esc(AK_STATUS[it.status][0])}">
              <span>${it.number ?? n + 1}</span><b data-math>${esc(akLabel(it))}</b></a>`).join("")}</div>
        </section>
        <div class="ak-list">${key.items.map((it, n) => {
          const [label, icon, tone, note] = AK_STATUS[it.status];
          return `
          <article class="panel ak-item" id="ak-${it.id}" data-problem-id="${esc(it.id)}" data-number="${it.number ?? n + 1}">
            <div class="ak-item-head"><b>${it.number ?? n + 1}번</b>
              <span class="ak-badge ${tone}"><i data-lucide="${icon}"></i>${label}</span>
              ${it.from_answer_file ? '<span class="ak-badge"><i data-lucide="link-2"></i>정답 파일</span>' : ""}
              ${it.needs_figure ? `<span class="ak-badge"><i data-lucide="image"></i>그림 문항</span><button type="button" class="ak-ask" data-orig="${mat.id}" data-page="${it.page ?? ""}"><i data-lucide="file-image"></i>원본 보기${it.page ? ` (${it.page}쪽)` : ""}</button>` : ""}
              ${it.manual ? '<span class="ak-badge"><i data-lucide="user-check"></i>직접 입력</span>' : ""}
              <button type="button" class="ak-ask" data-ak-ask="${esc(it.id)}" data-number="${it.number ?? n + 1}" title="이 문항에 대해 AI 에게 묻기 (해설을 드래그해도 돼요)"><i data-lucide="message-square-quote"></i>질문하기</button></div>
            <p class="stem" data-math>${esc(it.stem)}</p>
            ${it.choices ? `<ol class="ak-choices">${it.choices.map((ch, k) => `<li class="${String(k + 1) === it.answer ? "on" : ""}"><span>${CIRC[k]}</span><span data-math>${esc(ch)}</span></li>`).join("")}</ol>` : ""}
            <div class="ak-answer"><span>정답</span><b data-math>${esc(akLabel(it))}</b>
              ${it.status === "conflict" ? `<small data-math>시험지 정답 ${esc(akLabel(it, it.sheet_answer))} · AI 풀이 ${esc(akLabel(it, it.ai_answer))}</small>` : ""}
              ${note && tone !== "ok" ? `<small>${esc(note)}</small>` : ""}</div>
            ${it.sheet_explanation ? `<div class="ak-solution ak-sheet-sol"><span>정답 파일 해설</span>${it.sheet_explanation.split(/\n+/).filter(Boolean).map((l) => `<p data-math>${esc(l)}</p>`).join("")}</div>` : ""}
            ${it.solution ? `<div class="ak-solution"><span>${it.sheet_explanation ? "AI 해설" : "해설"}</span>${it.solution.split(/\n+/).filter(Boolean).map((l) => `<p data-math>${esc(l)}</p>`).join("")}</div>` : ""}
          </article>`;
        }).join("")}</div>` : ""}`;
    icons();

    view.onclick = async (e) => {
      const jump = e.target.closest("[data-ak-jump]");
      if (jump) { e.preventDefault(); $(`#ak-${CSS.escape(jump.dataset.akJump)}`)?.scrollIntoView({ behavior: "smooth", block: "start" }); return; }
      if (e.target.closest("[data-ak-print]")) return window.print();
      const o = e.target.closest("[data-orig]");
      if (o) return openOriginal(o.dataset.orig, o.dataset.page);
      if (e.target.closest("[data-ak-take]")) return takeOptions(mat.project_id, new URLSearchParams({ m: mat.id }));
      if (e.target.closest("[data-ak-retry]")) return takeOptions(mat.project_id, new URLSearchParams({ m: mat.id, ids: akWrong(key).join(",") }), "틀린 문항 다시 풀기");
      const askBtn = e.target.closest("[data-ak-ask]");
      if (askBtn) return openAsk({ problemId: askBtn.dataset.akAsk, number: askBtn.dataset.number });
      if (e.target.closest("[data-ak-start], [data-ak-rebuild]")) {
        makeAnswerKey(materialId).catch((err) => { toast(err.message); renderAnswerKey(materialId); });
      }
    };
    if (running) akTimer = setTimeout(() => renderAnswerKey(materialId), 4000);
  }

  // ================= 답변: 정답지에서 드래그한 부분을 인용해 AI 에게 이어 묻기 =================
  // 글을 고르면 '답변' 버튼이 뜨고, 누르면 오른쪽 대화 창에 인용으로 붙는다. 답은 풀이·그래프·검산 형식(explanationHTML).
  const ASK_PRESETS = [["더 자세히 설명해 줘", "list-plus"], ["그래프로 그려 줘", "chart-spline"],
    ["왜 이렇게 되는지 알려 줘", "circle-help"], ["비슷한 예제로 보여 줘", "copy-plus"]];
  const akAsk = { materialId: null, problemId: null, number: null, quote: "", turns: [], busy: false, seq: 0 };
  let askPop = null;

  // 고른 글 → 문항 + 인용 글. KaTeX 수식은 화면 글자 대신 원래 LaTeX($…$)로 바꿔 AI 가 식을 정확히 읽게 한다
  function selectedQuote() {
    const sel = getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
    const range = sel.getRangeAt(0).cloneRange();
    const el = (n) => (n.nodeType === 1 ? n : n.parentElement);
    const item = el(range.startContainer)?.closest(".ak-item");
    if (!item || item !== el(range.endContainer)?.closest(".ak-item")) return null;
    const k0 = el(range.startContainer).closest(".katex"), k1 = el(range.endContainer).closest(".katex");
    if (k0) range.setStartBefore(k0);
    if (k1) range.setEndAfter(k1);
    const frag = range.cloneContents();
    frag.querySelectorAll(".katex").forEach((k) => {
      const tex = k.querySelector('annotation[encoding="application/x-tex"]')?.textContent;
      k.replaceWith(tex ? ` $${tex.trim()}$ ` : k.textContent);
    });
    const text = frag.textContent.replace(/\s+/g, " ").trim();
    if (text.length < 2) return null;
    return { problemId: item.dataset.problemId, number: item.dataset.number, text: text.slice(0, 1500),
      rect: sel.getRangeAt(0).getBoundingClientRect() };
  }

  function hideAskPop() { askPop?.remove(); askPop = null; }
  function showAskPop() {
    hideAskPop();
    if (route().parts[0] !== "answer-key") return;
    const q = selectedQuote();
    if (!q) return;
    askPop = document.createElement("button");
    askPop.type = "button";
    askPop.className = "ask-pop";
    askPop.innerHTML = '<i data-lucide="message-square-quote"></i>답변';
    document.body.append(askPop);
    lucide.createIcons();
    const w = askPop.offsetWidth, h = askPop.offsetHeight;
    const left = Math.min(innerWidth - w - 8, Math.max(8, q.rect.left + q.rect.width / 2 - w / 2));
    const top = q.rect.top - h - 10 > 8 ? q.rect.top - h - 10 : q.rect.bottom + 10;
    askPop.style.left = `${left}px`;
    askPop.style.top = `${top}px`;
    askPop.onmousedown = (e) => e.preventDefault(); // 누르는 순간 선택이 풀리지 않게
    askPop.onclick = () => {
      hideAskPop();
      getSelection().removeAllRanges();
      openAsk({ problemId: q.problemId, number: q.number, quote: q.text });
    };
  }
  const popLater = (e, ms = 0) => { if (!e.target.closest?.(".ask-pop, .ask-panel")) setTimeout(showAskPop, ms); };
  document.addEventListener("mouseup", (e) => popLater(e));
  document.addEventListener("touchend", (e) => popLater(e, 350));
  document.addEventListener("keyup", (e) => { if (e.shiftKey || e.key === "Shift") popLater(e); });
  document.addEventListener("selectionchange", () => { if (askPop && getSelection().isCollapsed) hideAskPop(); });
  document.addEventListener("scroll", hideAskPop, true);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && $(".ask-panel")) closeAsk(); });
  window.addEventListener("hashchange", () => {
    hideAskPop();
    const [page, id] = route().parts;
    if (page !== "answer-key" || id !== akAsk.materialId) closeAsk(); // 다른 화면·다른 정답지로 가면 닫는다
  });

  function openAsk({ problemId, number, quote = "" }) {
    const materialId = route().parts[1];
    if (akAsk.materialId !== materialId || akAsk.problemId !== problemId) {
      Object.assign(akAsk, { materialId, problemId, number, turns: [] }); // 다른 문항이면 새 대화
    }
    akAsk.quote = quote;
    let panel = $(".ask-panel");
    if (!panel) {
      panel = document.createElement("aside");
      panel.className = "ask-panel";
      panel.setAttribute("role", "dialog");
      panel.setAttribute("aria-label", "답변");
      document.body.append(panel);
      document.body.classList.add("ask-open");
      panel.addEventListener("click", onAskClick);
      panel.addEventListener("submit", (e) => { e.preventDefault(); sendAsk($("#ask-input").value); });
      panel.addEventListener("input", (e) => { if (e.target.id === "ask-input") autoGrow(e.target); });
      panel.addEventListener("keydown", (e) => {
        if (e.target.id === "ask-input" && e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendAsk(e.target.value); }
      });
    }
    renderAsk();
    $("#ask-input")?.focus();
  }

  function closeAsk() {
    $(".ask-panel")?.remove();
    document.body.classList.remove("ask-open");
  }

  const autoGrow = (t) => { t.style.height = "auto"; t.style.height = `${Math.min(160, t.scrollHeight)}px`; };

  function renderAsk({ keepDraft = true } = {}) {
    const panel = $(".ask-panel");
    if (!panel) return;
    const draft = keepDraft ? ($("#ask-input")?.value ?? "") : "";
    const turns = akAsk.turns.map((t) => `
      <div class="ask-turn">
        <div class="ask-user">${t.quote ? `<blockquote data-math>${esc(t.quote)}</blockquote>` : ""}<p>${esc(t.q)}</p></div>
        <div class="ask-bot">${t.e ? explanationHTML(t.e, t.key)
          : t.error ? `<p class="ask-err"><i data-lucide="circle-alert"></i>${esc(t.error)} <button type="button" data-ask-retry="${t.key}">다시 묻기</button></p>`
          : '<div class="ask-typing"><i></i><i></i><i></i><span>풀이를 정리하고 있어요</span></div>'}</div>
      </div>`).join("");
    panel.innerHTML = `
      <header class="ask-head">
        <div><b><i data-lucide="message-square-quote"></i>답변</b><small>${akAsk.number ? `${esc(akAsk.number)}번 문항` : "이 문항"}에 대해 물어보세요</small></div>
        <button type="button" class="icon-btn" data-ask-close aria-label="닫기"><i data-lucide="x"></i></button>
      </header>
      <div class="ask-thread">${turns || `<div class="ask-empty"><i data-lucide="text-select"></i>
        <p>정답지에서 궁금한 수식이나 풀이를 <b>드래그</b>하면 '답변' 버튼이 떠요.<br>그 부분을 인용해 더 자세한 설명이나 그래프를 부탁할 수 있어요.</p></div>`}</div>
      <form class="ask-form">
        ${akAsk.quote ? `<div class="ask-quote"><i data-lucide="corner-down-right"></i><span data-math>${esc(akAsk.quote)}</span>
          <button type="button" data-ask-unquote aria-label="인용 빼기"><i data-lucide="x"></i></button></div>` : ""}
        <div class="ask-presets">${ASK_PRESETS.map(([q, ic]) => `<button type="button" data-ask-preset="${esc(q)}" ${akAsk.busy ? "disabled" : ""}><i data-lucide="${ic}"></i>${esc(q)}</button>`).join("")}</div>
        <div class="ask-box">
          <textarea id="ask-input" rows="1" maxlength="500" placeholder="${akAsk.quote ? "인용한 부분에 대해 물어보세요" : "이 문항에 대해 물어보세요"}">${esc(draft)}</textarea>
          <button type="submit" class="ask-send" aria-label="보내기" ${akAsk.busy ? "disabled" : ""}><i data-lucide="arrow-up"></i></button>
        </div>
      </form>`;
    icons();
    const input = $("#ask-input");
    if (input) autoGrow(input);
    const th = $(".ask-thread", panel);
    th.scrollTop = th.scrollHeight;
  }

  function onAskClick(e) {
    if (e.target.closest("[data-ask-close]")) return closeAsk();
    if (e.target.closest("[data-ask-unquote]")) { akAsk.quote = ""; return renderAsk(); }
    const preset = e.target.closest("[data-ask-preset]");
    if (preset) return sendAsk(preset.dataset.askPreset);
    const retry = e.target.closest("[data-ask-retry]");
    if (retry) {
      const i = akAsk.turns.findIndex((t) => t.key === retry.dataset.askRetry);
      if (i < 0 || akAsk.busy) return;
      const [t] = akAsk.turns.splice(i, 1);
      akAsk.quote = t.quote;
      sendAsk(t.q);
    }
  }

  // 지난 답은 요약·단계 글만 짧게 넘긴다 (이어 묻기의 맥락)
  const askSummary = (e) => [e.summary, ...(e.steps ?? []).map((s) => `${s.title}: ${s.text}`), e.result && `답: ${e.result}`]
    .filter(Boolean).join(" ").slice(0, 1900);

  async function sendAsk(text) {
    const q = String(text ?? "").trim();
    if (!q || akAsk.busy) return;
    const history = akAsk.turns.filter((t) => t.e).slice(-6).map((t) => ({ q: t.q.slice(0, 500), a: askSummary(t.e) }));
    const turn = { q: q.slice(0, 500), quote: akAsk.quote, key: `ask-${++akAsk.seq}` };
    const ctx = { materialId: akAsk.materialId, problemId: akAsk.problemId };
    akAsk.turns.push(turn);
    akAsk.quote = "";
    akAsk.busy = true;
    renderAsk({ keepDraft: false });
    try {
      const res = await Store.askAnswerKey(ctx.materialId, { problem_id: ctx.problemId, question: turn.q, quote: turn.quote, history });
      turn.e = res.explanation;
    } catch (err) {
      turn.error = err.message || "답변을 만들지 못했어요";
    }
    akAsk.busy = false;
    if (akAsk.materialId === ctx.materialId && akAsk.problemId === ctx.problemId) renderAsk();
  }

  document.addEventListener("click", (e) => { if (e.target.closest("[data-print-notes]")) window.print(); });
  // ================= 오답노트 =================
  const noteFilter = { domain: "all", error: "all", openOnly: true, project: null };

  function renderNotes() {
    const { params } = route();
    noteFilter.domain = params.get("domain") ?? "all";
    noteFilter.project = params.get("project");
    const proj = noteFilter.project && Store.project(noteFilter.project);

    view.innerHTML = `
      <div class="page-head">
        <div>
          <h1><i data-lucide="circle-x"></i>오답노트</h1>
          <p>${proj ? `${esc(proj.name)}의 오답 · <a href="#/notes" style="color:inherit">전체 보기</a>` : "틀린 문제를 다시 풀어 맞히면 극복으로 표시돼요"}</p>
        </div>
        <div class="page-actions print-hide"><button class="btn-ghost" data-print-notes title="지금 보이는 오답을 인쇄하거나 PDF로 저장"><i data-lucide="printer"></i>인쇄 · PDF 저장</button></div>
      </div>
      <div class="note-stats" id="note-stats"></div>
      <div class="toolbar glass-bar">
        <div class="seg" id="note-domains">
          <button data-domain="all">전체</button>
          ${(() => { const ds = [...new Set(Store.state.wrongNotes.map((w) => Store.problem(w.problemId)?.domain).filter(Boolean))];
            return (ds.length ? ds.sort((a, b) => domainOrder(a) - domainOrder(b)) : myDomains()); })()
            .map((d) => `<button data-domain="${d}" style="--c:${COLOR[d]}"><span class="sw"></span>${DOMAIN_NAME[d]}</button>`).join("")}
        </div>
        <select class="select" id="note-error" aria-label="틀린 이유">
          <option value="all">틀린 이유: 전체</option>
          ${Object.entries(ERROR_TYPES).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}
        </select>
        <label class="check"><input type="checkbox" id="note-open" /> 안 푼 것만</label>
        <span class="count" id="note-count"></span>
      </div>
      <div class="notes" id="note-list"></div>`;

    $("#note-error").value = noteFilter.error;
    $("#note-open").checked = noteFilter.openOnly;
    renderNoteList();

    view.onclick = (e) => {
      const dom = e.target.closest("[data-domain]");
      if (dom) { noteFilter.domain = dom.dataset.domain; return renderNoteList(); }
      const retry = e.target.closest("[data-retry]");
      if (retry) return retryModal(retry.dataset.retry);
      const del = e.target.closest("[data-del-note]");
      if (del) return confirmModal({
        title: "오답노트에서 삭제할까요?", text: "이 문제의 오답 기록이 삭제돼요.",
        run: () => { Store.deleteNote(del.dataset.delNote); renderNoteList(); toast("삭제했어요"); },
      });
    };
    view.onchange = (e) => {
      if (e.target.id === "note-error") { noteFilter.error = e.target.value; renderNoteList(); }
      if (e.target.id === "note-open") { noteFilter.openOnly = e.target.checked; renderNoteList(); }
      if (e.target.dataset.setError) { Store.setErrorType(e.target.dataset.setError, e.target.value); renderNoteStats(); }
    };
  }

  // 요약: 남은 오답 · 이번 주 극복 · 가장 많이 틀린 이유
  function renderNoteStats() {
    const notes = Store.state.wrongNotes.filter((w) => !noteFilter.project || w.projectId === noteFilter.project);
    const open = notes.filter((w) => !w.resolvedAt);
    const week = notes.filter((w) => w.resolvedAt && w.resolvedAt > Date.now() - 7 * DAY).length;
    const counts = {};
    open.filter((w) => w.errorType !== "unknown").forEach((w) => (counts[w.errorType] = (counts[w.errorType] ?? 0) + 1));
    const [topType, topN] = Object.entries(counts).sort((a, b) => b[1] - a[1])[0] ?? [];
    $("#note-stats").innerHTML = `
      <div class="glass-tile"><span><i data-lucide="target"></i>남은 오답</span><b>${open.length}<small>문제</small></b></div>
      <div class="glass-tile"><span><i data-lucide="trophy"></i>이번 주 극복</span><b>${week}<small>문제</small></b></div>
      <div class="glass-tile"><span><i data-lucide="search-check"></i>가장 많이 틀린 이유</span>
        <b class="text">${topType ? `${ERROR_TYPES[topType]}<small>${topN}문제</small>` : "<small>아직 분류 전이에요</small>"}</b></div>`;
  }

  function renderNoteList() {
    renderNoteStats();
    $$("#note-domains [data-domain]").forEach((b) => b.classList.toggle("on", b.dataset.domain === noteFilter.domain));
    const list = Store.state.wrongNotes
      .filter((w) => noteFilter.domain === "all" || Store.problem(w.problemId).domain === noteFilter.domain)
      .filter((w) => noteFilter.error === "all" || w.errorType === noteFilter.error)
      .filter((w) => !noteFilter.openOnly || !w.resolvedAt)
      .filter((w) => !noteFilter.project || w.projectId === noteFilter.project)
      .sort((a, b) => (!!a.resolvedAt - !!b.resolvedAt) || b.createdAt - a.createdAt);
    $("#note-count").textContent = `${list.length}문제`;
    $("#note-list").innerHTML = list.length ? list.map((w) => {
      const p = Store.problem(w.problemId);
      if (!p) return "";
      const c = concept(p.conceptIds[0]) ?? { id: "", name: DOMAIN_NAME[p.domain] };
      return `
        <article class="note glass-card ${w.resolvedAt ? "resolved" : ""}" style="--c:${COLOR[p.domain]}">
          <header class="note-top">
            <span class="subject-pill"><span class="sw"></span>${esc(subjectOf(c.id)?.name ?? DOMAIN_NAME[p.domain])}</span>
            <a class="concept-link" href="#/library/concept/${c.id}">${esc(c.name)}</a>
            <span class="stars" title="난이도 ${p.difficulty}">${"★".repeat(p.difficulty)}${"☆".repeat(5 - p.difficulty)}</span>
            ${w.resolvedAt ? '<span class="pill done-pill"><i data-lucide="check"></i>극복</span>' : ""}
            <time>${relTime(w.createdAt)}</time>
          </header>
          <div class="note-q">
            <p class="stem" data-math>${esc(p.stem)}</p>
            ${isShort(p) ? `<div class="note-short"><span class="pill">${TYPE_LABEL[ptype(p)] ?? "단답형"}</span>내 답 <b>${esc((w.answer || "–").length > 80 ? `${w.answer.slice(0, 80)}…` : w.answer || "–")}</b></div>` : `
            <ol class="note-choices">
              ${p.choices.map((ch, i) => `<li class="${String(i + 1) === w.answer ? "mine" : ""}"><span class="n">${i + 1}</span><span data-math>${esc(ch)}</span>${String(i + 1) === w.answer ? '<em>내 답</em>' : ""}</li>`).join("")}
            </ol>`}
          </div>
          <footer class="note-foot">
            <label class="why-select"><i data-lucide="tag"></i>
              <select data-set-error="${w.id}" aria-label="틀린 이유">
                ${Object.entries(ERROR_TYPES).map(([k, v]) => `<option value="${k}" ${w.errorType === k ? "selected" : ""}>${k === "unknown" ? "틀린 이유 고르기" : v}</option>`).join("")}
              </select>
            </label>
            <div class="note-actions">
              <button class="btn-ghost glassy" disabled title="AI 연결 후 사용할 수 있어요"><i data-lucide="sparkles"></i>변형 문제</button>
              <button class="icon-btn glassy" data-del-note="${w.id}" title="삭제" aria-label="삭제"><i data-lucide="trash-2"></i></button>
              <button class="btn-primary" data-retry="${w.id}"><i data-lucide="rotate-ccw"></i>${w.resolvedAt ? "한 번 더 풀기" : "다시 풀기"}</button>
            </div>
          </footer>
        </article>`;
    }).join("") : `
      <div class="empty glass-card"><i data-lucide="party-popper"></i><b>${noteFilter.openOnly ? "남은 오답이 없어요" : "오답이 없어요"}</b>문제를 풀다 틀리면 여기에 모여요</div>`;
    icons();
  }

  function retryModal(noteId) {
    const w = Store.state.wrongNotes.find((n) => n.id === noteId);
    openSheet({
      title: "다시 풀기",
      body: problemHTML(w.problemId),
      onMount(sheet) {
        const ctx = { projectId: w.projectId };
        const redraw = (box, attempt) => {
          redrawCard(box, attempt);
          if (navKey() === "notes") renderNoteList();
        };
        sheet.addEventListener("click", (e) => { if (!handleProblemExtras(e)) handleAnswer(e, ctx, redraw); });
      },
    });
  }

  // ================= 라이브러리 =================
  let libQuery = "";
  let deckIndex = 0;
  let flipped = false;

  function renderLibrary(tab, id) {
    if (tab === "concept") return renderConcept(id);
    const tabs = [["concepts", "book-open", "개념 노트"], ["cards", "layers", "암기 카드"], ["saved", "bookmark", "저장한 문제"]];
    view.innerHTML = `
      <div class="page-head">
        <div><h1><i data-lucide="library"></i>라이브러리</h1><p>개념, 암기 카드, 저장한 문제를 한곳에서</p></div>
      </div>
      <div class="toolbar">
        <nav class="seg">${tabs.map(([k, ic, label]) => `<a href="#/library/${k}" class="${tab === k ? "on" : ""}"><i data-lucide="${ic}"></i>${label}</a>`).join("")}</nav>
        ${tab === "concepts" ? `<label class="lib-search"><i data-lucide="search"></i><input id="lib-q" placeholder="개념 검색 (예: 치환적분, 몰)" value="${esc(libQuery)}" /></label>` : ""}
      </div>
      <div id="lib-body"></div>`;
    if (tab === "concepts") {
      renderTree();
      $("#lib-q").addEventListener("input", (e) => { libQuery = e.target.value; renderTree(); });
    } else if (tab === "cards") {
      deckIndex = 0; flipped = false;
      renderDeck();
    } else renderSaved();
  }

  function renderTree() {
    const qy = libQuery.trim().toLowerCase();
    const hit = (c) => !qy || c.name.toLowerCase().includes(qy);
    const mark = (s) => (qy ? esc(s).replace(new RegExp(qy.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi"), (m) => `<mark>${m}</mark>`) : esc(s));
    const html = DOMAINS.map((d) => {
      const subjects = SUBJECTS.filter((s) => s.domain === d).map((s) => {
        const units = childrenOf(s.id).map((u) => {
          const items = childrenOf(u.id).filter(hit);
          return items.length || (qy && hit(u)) ? `
            <div class="unit"><h4>${mark(u.name)}</h4>
              ${(items.length ? items : childrenOf(u.id)).map((c) => `<a href="#/library/concept/${c.id}">${mark(c.name)}</a>`).join("")}
            </div>` : "";
        }).join("");
        const count = childrenOf(s.id).reduce((n, u) => n + childrenOf(u.id).length, 0);
        return units ? `
          <details ${qy ? "open" : ""}>
            <summary><i data-lucide="chevron-right"></i>${esc(s.name)}${courseMap[s.id]?.exam ? `<small class="course-exam">${esc(courseMap[s.id].exam)}${courseMap[s.id].level ? ` · ${esc(courseMap[s.id].level)}` : ""}</small>` : ""}<span>${count}개 개념</span></summary>
            ${units}
          </details>` : "";
      }).join("");
      return subjects ? `<section class="tree-domain" style="--c:${COLOR[d]}"><h2><span class="sw"></span>${DOMAIN_NAME[d]}</h2>${subjects}</section>` : "";
    }).join("");
    // 아직 받지 않은 공개 코스 (다른 사람이 만든 코스) — 누르면 개념 트리를 받아 온다
    const others = COURSES.filter((c) => !conceptMap[c.id] && (!qy || `${c.title} ${c.exam} ${c.category}`.toLowerCase().includes(qy)));
    const browse = others.length ? `
      <section class="tree-domain other-courses"><h2><i data-lucide="compass"></i>다른 코스 둘러보기 <small>다른 사람들이 출제 범위로 만든 코스예요</small></h2>
        <div class="course-list">${others.slice(0, 30).map((c) => `
          <button type="button" class="course-item" data-load-course="${esc(c.id)}" style="--c:${COLOR[c.domain]}">
            <b><span class="sw"></span>${esc(c.title)}</b><small>${esc([c.exam, c.category, c.level, `${c.units}개 단원`].filter(Boolean).join(" · "))}</small></button>`).join("")}</div>
      </section>` : "";
    $("#lib-body").innerHTML = `<div class="tree">${html || (browse ? "" : `<div class="empty"><i data-lucide="search-x"></i><b>찾는 개념이 없어요</b>다른 단어로 검색해 보세요</div>`)}${browse}</div>`;
    $("#lib-body .tree").onclick = async (e) => {
      const b = e.target.closest("[data-load-course]");
      if (!b) return;
      b.disabled = true;
      try { await Store.loadCourse(b.dataset.loadCourse); loadConcepts(); renderTree(); } catch (err) { toast(err.message); b.disabled = false; }
    };
    icons();
  }

  function renderConcept(id) {
    const c = concept(id);
    if (!c) return go("/library");
    const path = pathOf(id);
    const stats = Store.conceptStats().find((s) => s.conceptId === id);
    const problems = Store.bank.filter((p) => p.conceptIds.includes(id));
    const notes = Store.state.wrongNotes.filter((w) => Store.problem(w.problemId).conceptIds.includes(id));
    const next = CONCEPTS.filter((x) => x.prerequisites.includes(id));
    const cards = Store.state.cards.filter((k) => k.conceptId === id);
    const link = (x) => `<a class="pill" href="#/library/concept/${x.id}" style="--c:${COLOR[x.domain]}">${esc(x.name)}</a>`;

    view.innerHTML = `
      <div class="crumbs"><a href="#/library">라이브러리</a>${path.map((x) => `<span>›</span><span>${esc(x.name)}</span>`).join("")}</div>
      <div class="page-head" style="margin-top:10px">
        <div><h1 style="color:inherit">${esc(c.name)}</h1>
          <p>${stats ? `내 정답률 ${pct(stats.accuracy)} · ${stats.attempts}문제 풀이` : "아직 이 개념의 문제를 풀지 않았어요"}${notes.length ? ` · 오답 ${notes.length}개` : ""}</p></div>
      </div>
      <div id="note-slot"></div>
      <div class="cols">
        <section class="panel"><h3><i data-lucide="corner-left-up"></i>먼저 알아야 할 개념</h3>
          ${c.prerequisites.length ? `<div class="links">${c.prerequisites.map((p) => link(concept(p))).join("")}</div>` : '<p class="mini">선수 개념이 없어요. 여기서 시작하면 돼요</p>'}</section>
        <section class="panel"><h3><i data-lucide="corner-right-down"></i>이어서 배울 개념</h3>
          ${next.length ? `<div class="links">${next.map(link).join("")}</div>` : '<p class="mini">이 개념이 이 단원의 마무리예요</p>'}</section>
      </div>
      ${cards.length ? `<section class="panel" style="margin-top:12px"><h3><i data-lucide="layers"></i>암기 카드 ${cards.length}장</h3>
        <div class="list">${cards.map((k) => `<a href="#/library/cards"><i data-lucide="${k.known ? "check" : "circle-dashed"}"></i><span class="card-front" data-math>${esc(k.front)}</span><span>${k.known ? "외움" : "아직"}</span></a>`).join("")}</div></section>` : ""}
      <section style="margin-top:12px">
        <h3 style="font-size:14.5px;font-weight:600">관련 문제 ${problems.length}개</h3>
        ${problems.length ? problems.map((p) => problemHTML(p.id)).join("") : '<p class="mini">문제 은행에 아직 이 개념의 문제가 없어요. AI 연결 후 바로 만들 수 있어요</p>'}
      </section>`;

    view.onclick = (e) => { if (!handleProblemExtras(e)) handleAnswer(e, {}, redrawCard); };
    renderNote(id);
  }

  // ---------- 내 맞춤 개념 정리 (한 번 더 검토를 통과한 것만) ----------
  const noteCache = {}; // conceptId → note | null
  const noteBusy = new Set(); // 만드는 중인 개념
  async function renderNote(id) {
    const slot = $("#note-slot");
    if (!slot) return;
    const draw = (html) => { if (document.contains(slot)) { slot.innerHTML = html; icons(); } };
    if (concept(id).level !== "concept") return draw("");
    if (Store.mode !== "api") {
      return draw(`<div class="ai-slot"><i data-lucide="sparkles"></i><div><b style="color:var(--ink)">개념 정리 · 필수 암기</b><br />로그인한 계정으로 열면 내 풀이 기록에 맞춘 개념 정리와 암기 카드를 만들 수 있어요.</div></div>`);
    }
    if (noteBusy.has(id)) return draw(NOTE_BUSY);
    if (!(id in noteCache)) {
      draw(`<div class="ai-slot"><i data-lucide="loader-circle" class="spin"></i><div>내 개념 정리를 불러오는 중…</div></div>`);
      try { noteCache[id] = await Store.getNote(id); } catch (err) { return draw(`<div class="ai-slot"><i data-lucide="circle-alert"></i><div>${esc(err.message)}</div></div>`); }
    }
    draw(noteCache[id] ? noteHTML(noteCache[id]) : `
      <div class="ai-slot"><i data-lucide="sparkles"></i><div style="flex:1"><b style="color:var(--ink)">내 맞춤 개념 정리 · 암기 카드</b><br />
        내 풀이·오답 기록에 맞춰 핵심 정리, 꼭 외울 공식, 자주 틀리는 점, 예제를 만들고 암기 카드도 덱에 넣어 드려요.
        한 번 더 검토한 뒤 보여 드려요 (1~2분).
        <div style="margin-top:10px"><button class="btn-primary" data-make-note><i data-lucide="wand-sparkles"></i>만들기</button></div></div></div>`);
    slot.onclick = async (e) => {
      if (!e.target.closest("[data-make-note]") || noteBusy.has(id)) return;
      noteBusy.add(id);
      draw(NOTE_BUSY);
      try {
        const r = await withAIProgress({
          title: "내 맞춤 개념 정리를 만드는 중",
          steps: ["내 풀이·오답 살펴보기", "핵심 정리 쓰기", "한 번 더 검토하기", "암기 카드 넣기"], expectMs: 70000,
          run: () => Store.createNote(id),
        });
        noteCache[id] = r.note;
        toast(r.added_cards.length ? `암기 카드 ${r.added_cards.length}장을 덱에 넣었어요` : "개념 정리를 새로 만들었어요");
      } catch (err) { toast(err.message); }
      noteBusy.delete(id);
      if (location.hash === `#/library/concept/${id}`) renderConcept(id);
    };
  }
  const NOTE_BUSY = `<div class="ai-slot"><i data-lucide="loader-circle" class="spin"></i><div><b style="color:var(--ink)">AI가 정리하고 한 번 더 검토하는 중이에요</b><br />1~2분 걸려요. 다른 화면에 다녀와도 계속 만들어요.</div></div>`;

  function noteHTML(n) {
    const c = n.content;
    const date = new Date(n.created_at).toLocaleDateString("ko-KR", { month: "long", day: "numeric" });
    return `
      <section class="panel concept-note">
        <div class="note-head"><h3><i data-lucide="notebook-pen"></i>내 맞춤 개념 정리</h3>
          <span class="verified"><i data-lucide="shield-check"></i>검증 완료 · ${date}</span>
          <button class="btn-ghost" data-make-note title="내 최근 기록으로 다시 만들기"><i data-lucide="refresh-cw"></i>다시 만들기</button></div>
        ${c.personal_tip ? `<p class="tip" data-math><i data-lucide="target"></i>${esc(c.personal_tip)}</p>` : ""}
        <h4>핵심 정리</h4><div class="prose" data-math>${esc(c.summary)}</div>
        <h4>꼭 외울 것</h4>
        <ul class="memo">${c.must_memorize.map((x) => `<li><b>${esc(x.title)}</b><span data-math>${esc(x.body)}</span></li>`).join("")}</ul>
        ${c.pitfalls.length ? `<h4>자주 틀리는 점</h4><ul class="pitfalls">${c.pitfalls.map((x) => `<li data-math>${esc(x)}</li>`).join("")}</ul>` : ""}
        <h4>예제</h4><div class="prose" data-math>${esc(c.example.question)}</div>
        <details class="example"><summary><i data-lucide="chevron-right"></i>풀이 보기</summary><div class="prose" data-math>${esc(c.example.solution)}</div></details>
      </section>`;
  }

  // 카드 글 길이에 따라 글씨 크기 (수식 기호는 길이에서 뺀다)
  const cardLen = (t = "") => { const n = plainMath(t).length; return n > 120 ? "longer" : n > 60 ? "long" : ""; };

  function renderDeck() {
    const all = Store.state.cards;
    const deck = all.filter((c) => c.known !== true);
    const known = all.length - deck.length;
    const body = $("#lib-body");
    if (!deck.length) {
      body.innerHTML = `
        <div class="empty"><i data-lucide="party-popper"></i><b>${all.length}장을 모두 외웠어요!</b>
          <button class="btn-ghost" id="deck-reset" style="margin:14px auto 0"><i data-lucide="rotate-ccw"></i>처음부터 다시</button></div>`;
      icons();
      $("#deck-reset").onclick = () => { Store.resetCards(); deckIndex = 0; renderDeck(); };
      return;
    }
    deckIndex %= deck.length;
    const card = deck[deckIndex];
    const c = concept(card.conceptId);
    body.innerHTML = `
      <div class="deck">
        <div class="deck-progress"><span>외운 카드 ${known} / ${all.length}</span><div class="bar"><i style="width:${(known / all.length) * 100}%"></i></div></div>
        <div class="flash ${flipped ? "flipped" : ""}" id="flash" style="--c:${COLOR[c.domain]}" tabindex="0" role="button" aria-label="카드 뒤집기">
          <div class="flash-inner">
            <div class="flash-face"><small>${esc(subjectOf(c.id)?.name ?? "")} · ${esc(c.name)}</small><p class="${cardLen(card.front)}" data-math>${esc(card.front)}</p><small>눌러서 정답 보기</small></div>
            <div class="flash-face flash-back"><small>정답</small><p class="${cardLen(card.back)}" data-math>${esc(card.back)}</p></div>
          </div>
        </div>
        <div class="deck-actions">
          <button class="btn-ghost" data-known="false"><i data-lucide="x"></i>모르겠어요</button>
          <button class="btn-primary" data-known="true"><i data-lucide="check"></i>알아요</button>
        </div>
        <p class="deck-hint">스페이스: 뒤집기 · ← 모르겠어요 · → 알아요</p>
      </div>`;
    icons();
    const flip = () => { flipped = !flipped; $("#flash").classList.toggle("flipped", flipped); };
    $("#flash").onclick = flip;
    $$("[data-known]", body).forEach((b) => (b.onclick = () => answerCard(b.dataset.known === "true")));
    function answerCard(isKnown) {
      Store.markCard(card.id, isKnown);
      if (!isKnown) deckIndex++; // 모르는 카드는 뒤로 보내 나중에 다시
      flipped = false;
      renderDeck();
    }
    deckKeys = (e) => {
      if (navKey() !== "library" || !$("#flash")) return;
      if (e.key === " ") { e.preventDefault(); flip(); }
      if (e.key === "ArrowRight") answerCard(true);
      if (e.key === "ArrowLeft") answerCard(false);
    };
  }
  let deckKeys = null;
  document.addEventListener("keydown", (e) => {
    if (document.querySelector(".backdrop, .menu") || e.target.closest?.("input, textarea, select")) return;
    deckKeys?.(e);
  });

  function renderSaved() {
    const ids = Store.state.savedProblemIds;
    $("#lib-body").innerHTML = ids.length ? ids.map((pid) => problemHTML(pid)).join("")
      : '<div class="empty"><i data-lucide="bookmark"></i><b>저장한 문제가 없어요</b>문제 카드의 책갈피를 누르면 여기에 모여요</div>';
    icons();
    view.onclick = (e) => {
      if (e.target.closest("[data-save]")) {
        handleProblemExtras(e);
        return renderSaved();
      }
      if (!handleProblemExtras(e)) handleAnswer(e, {}, redrawCard);
    };

  }


  // ================= 계정 설정 =================
  // 카카오(다음) 우편번호 서비스 — 키 없이 쓰는 주소 검색. 처음 누를 때만 스크립트를 불러온다
  let postcodeReady = null;
  const loadPostcode = () => (postcodeReady ??= new Promise((ok, fail) => {
    const s = Object.assign(document.createElement("script"), { src: "https://t1.daumcdn.net/mapjsapi/bundle/postcode/prod/postcode.v2.js" });
    s.onload = ok;
    s.onerror = () => { postcodeReady = null; s.remove(); fail(new Error("주소 검색을 불러오지 못했어요. 잠시 후 다시 시도해 주세요")); };
    document.head.append(s);
  }));

  // 교재 칸: 제목·ISBN 으로 책 후보 (선택). 고르면 책 카드, 고르지 않고 이름만 적어도 된다
  const bookSub = (b) => [b.authors.slice(0, 2).join(", "), b.publisher, b.year, b.isbn && `ISBN ${b.isbn}`].filter(Boolean).join(" · ");
  function bindBookField(input, list, card, state) {
    const draw = () => {
      card.hidden = !state.book;
      if (!state.book) return;
      const b = state.book;
      card.innerHTML = `${b.thumbnail ? `<img src="${esc(b.thumbnail)}" alt="" referrerpolicy="no-referrer" />` : '<i data-lucide="book"></i>'}
        <span><b>${esc(b.title)}</b><small>${esc(bookSub(b))}</small></span>
        <button type="button" class="icon-btn" data-book-clear aria-label="책 선택 취소"><i data-lucide="x"></i></button>`;
      lucide.createIcons();
    };
    bindSuggest(input, list, async (q) => (await Store.searchBooks(q)).map((b) => ({ label: b.title, sub: bookSub(b), value: b.title, thumb: b.thumbnail, book: b })),
      2, (it) => { state.book = it.book; state.isbn = it.book.isbn ?? null; draw(); });
    input.addEventListener("input", () => { if (state.book && input.value.trim() !== state.book.title) { state.book = null; state.isbn = null; draw(); } });
    card.addEventListener("click", (e) => { if (e.target.closest("[data-book-clear]")) { state.book = null; state.isbn = null; draw(); input.focus(); } });
    draw();
  }

  // 고등학생이 고르는 계열 — 대학 학과는 직접 적는다
  const MAJOR_PRESETS = ["인문계열", "자연계열", "예체능계열", "특성화고", "마이스터고"];

  // 입력하면 아래에 후보 목록을 띄우는 칸 (학교 검색). fetch(q) → [{ label, sub, value }]
  function bindSuggest(input, list, fetch, minLength = 2, onPick = null) {
    let items = [], active = -1, timer = 0, seq = 0;
    const close = () => { list.hidden = true; input.setAttribute("aria-expanded", "false"); active = -1; };
    const draw = () => {
      list.innerHTML = items.map((x, i) => `<li role="option" data-i="${i}" class="${i === active ? "on" : ""} ${x.thumb ? "has-thumb" : ""}" aria-selected="${i === active}">
        ${x.thumb ? `<img src="${esc(x.thumb)}" alt="" loading="lazy" referrerpolicy="no-referrer" />` : ""}<span><b>${esc(x.label)}</b><small>${esc(x.sub)}</small></span></li>`).join("");
      list.hidden = !items.length;
      input.setAttribute("aria-expanded", String(!!items.length));
    };
    const pick = (i) => { input.value = items[i].value; close(); onPick?.(items[i]); input.dispatchEvent(new Event("change", { bubbles: true })); };
    input.addEventListener("input", () => {
      clearTimeout(timer);
      const q = input.value.trim();
      if (q.length < minLength) { items = []; return close(); }
      timer = setTimeout(async () => {
        const mine = ++seq;
        try { const r = await fetch(q); if (mine === seq) { items = r; active = -1; draw(); } }
        catch (err) { if (mine === seq) { items = []; close(); toast(err.message); } }
      }, 250);
    });
    input.addEventListener("keydown", (e) => {
      if (list.hidden) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        active = (active + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
        draw();
      } else if (e.key === "Enter" && active >= 0) { e.preventDefault(); pick(active); }
      else if (e.key === "Escape") close();
    });
    list.addEventListener("mousedown", (e) => { const li = e.target.closest("[data-i]"); if (li) { e.preventDefault(); pick(Number(li.dataset.i)); } });
    input.addEventListener("blur", () => setTimeout(close, 100));
  }

  const PROVIDERS = {
    google: { name: "Google", icon: `<svg viewBox="0 0 48 48" aria-hidden="true"><path fill="#FFC107" d="M43.6 20.1H42V20H24v8h11.3c-1.6 4.7-6.1 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 8 3l5.7-5.7C34 6.1 29.3 4 24 4 13 4 4 13 4 24s9 20 20 20 20-9 20-20c0-1.3-.1-2.6-.4-3.9z"/><path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 8 3l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/><path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2c-2 1.5-4.5 2.4-7.2 2.4-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z"/><path fill="#1976D2" d="M43.6 20.1H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.6-.4-3.9z"/></svg>` },
    kakao: { name: "카카오", icon: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#000" d="M12 3C6.48 3 2 6.58 2 11c0 2.83 1.86 5.32 4.66 6.73l-.95 3.48c-.08.3.26.54.52.37l4.13-2.73c.53.06 1.08.1 1.64.1 5.52 0 10-3.58 10-8s-4.48-8-10-8z"/></svg>` },
  };
  const LINK_ERRORS = {
    taken: (p) => `이 ${p} 계정은 이미 다른 Eureka 계정에 연결돼 있어요`,
    duplicate: (p) => `이미 다른 ${p} 계정이 연결돼 있어요. 먼저 연결을 해제해 주세요`,
    cancelled: (p) => `${p} 연결을 취소했어요`,
    not_configured: (p) => `${p} 로그인은 아직 준비 중이에요`,
    provider: (p) => `${p}와 연결하지 못했어요. 잠시 후 다시 시도해 주세요`,
  };

  // 로그인 방법: 이메일·비밀번호, Google, 카카오. 마지막 남은 방법은 해제할 수 없다
  async function renderLoginMethods() {
    const box = $("#login-methods");
    if (!box) return;
    let c;
    try { c = await Store.connections(); } catch (err) { box.innerHTML = `<p class="mini">${esc(err.message)}</p>`; return; }
    if (!document.body.contains(box)) return; // 그새 다른 화면으로 이동
    const total = c.accounts.length + (c.has_password ? 1 : 0);
    const row = (icon, name, desc, action) => `
      <div class="method-row"><span class="method-icon">${icon}</span>
        <div class="method-text"><b>${name}</b><small>${desc}</small></div>${action}</div>`;
    box.innerHTML = [
      row(`<i data-lucide="mail"></i>`, "이메일 · 비밀번호",
        c.has_password ? `${esc(Store.state.user.email)} 로 로그인할 수 있어요` : "비밀번호를 만들면 이메일로도 로그인할 수 있어요",
        `<button class="btn-ghost glassy" data-pw>${c.has_password ? "비밀번호 바꾸기" : "비밀번호 만들기"}</button>`),
      ...Object.entries(PROVIDERS).map(([key, p]) => {
        const acc = c.accounts.find((a) => a.provider === key);
        const action = acc
          ? `<button class="btn-ghost glassy" data-unlink="${key}" ${total <= 1 ? 'disabled title="로그인 방법이 하나뿐이라 해제할 수 없어요"' : ""}>연결 해제</button>`
          : c.available[key] ? `<button class="btn-primary" data-link="${key}">연결하기</button>`
          : `<button class="btn-ghost glassy" disabled>준비 중</button>`;
        return row(p.icon, p.name, acc ? `${esc(acc.email ?? "연결됨")} · ${relTime(new Date(acc.created_at).getTime())} 연결` : "연결하면 버튼 하나로 로그인할 수 있어요", action)
          .replace('class="method-icon"', `class="method-icon ${key}"`);
      }),
    ].join("") + (total <= 1 ? `<p class="mini">로그인 방법이 하나뿐이에요. 다른 방법을 하나 더 연결해 두면 계정을 잃어버릴 걱정이 줄어요</p>` : "");
    icons();

    box.onclick = async (e) => {
      const link = e.target.closest("[data-link]")?.dataset.link;
      const unlink = e.target.closest("[data-unlink]")?.dataset.unlink;
      if (link) {
        try { location.href = (await Store.startConnection(link)).url; } catch (err) { toast(err.message); }
      } else if (unlink) {
        confirmModal({
          title: `${PROVIDERS[unlink].name} 연결 해제`, action: "해제",
          text: `이제 ${PROVIDERS[unlink].name}로는 로그인할 수 없어요. 언제든 다시 연결할 수 있어요.`,
          run: async () => {
            try { await Store.removeConnection(unlink); toast(`${PROVIDERS[unlink].name} 연결을 해제했어요`); renderLoginMethods(); }
            catch (err) { toast(err.message); }
          },
        });
      } else if (e.target.closest("[data-pw]")) {
        passwordModal(c.has_password);
      }
    };
  }

  function passwordModal(hasPassword) {
    formModal({
      title: hasPassword ? "비밀번호 바꾸기" : "비밀번호 만들기", submit: "저장",
      body: `${hasPassword ? `<div class="field"><label for="f-pw-cur">현재 비밀번호</label><input id="f-pw-cur" type="password" autocomplete="current-password" /></div>` : ""}
        <div class="field"><label for="f-pw-new">새 비밀번호</label><input id="f-pw-new" type="password" placeholder="8자 이상, 영문과 숫자 포함" autocomplete="new-password" /></div>
        <div class="field"><label for="f-pw-new2">새 비밀번호 확인</label><input id="f-pw-new2" type="password" autocomplete="new-password" /></div>`,
      onSubmit: (f) => {
        $$(".invalid", f).forEach((x) => x.classList.remove("invalid"));
        const cur = $("#f-pw-cur", f), pw = $("#f-pw-new", f).value, pw2 = $("#f-pw-new2", f).value;
        if (cur && !cur.value) return invalid(cur, "현재 비밀번호를 입력해 주세요");
        if (pw.length < 8 || !/[a-zA-Z]/.test(pw) || !/\d/.test(pw)) return invalid($("#f-pw-new", f), "8자 이상, 영문과 숫자를 함께 써 주세요");
        if (pw !== pw2) return invalid($("#f-pw-new2", f), "비밀번호가 일치하지 않아요");
        Store.setPassword(cur?.value, pw).then(() => {
          closeOverlays();
          toast(hasPassword ? "비밀번호를 바꿨어요" : "비밀번호를 만들었어요. 이제 이메일로도 로그인할 수 있어요");
          renderLoginMethods();
        }).catch((err) => invalid(cur && /현재/.test(err.message) ? cur : $("#f-pw-new", f), err.message));
        return false; // 서버 응답을 받은 뒤 닫는다
      },
    });
  }

  function renderSettings(params = new URLSearchParams()) {
    // 계정 설정에서 시작한 간편 로그인 연결의 결과 (#/settings?linked=google 또는 ?link_error=…)
    const done = params.get("linked"), failed = params.get("link_error");
    if (done || failed) {
      const name = PROVIDERS[done ?? params.get("provider")]?.name ?? "간편 로그인";
      toast(done ? `${name} 계정을 연결했어요. 이제 ${name}로도 로그인할 수 있어요` : (LINK_ERRORS[failed] ?? LINK_ERRORS.provider)(name));
      history.replaceState(null, "", "#/settings");
    }
    const u = Store.state.user;
    view.innerHTML = `
      <div class="page-head"><div><h1><i data-lucide="user-round-cog"></i>계정 설정</h1><p>프로필 사진과 내 정보를 관리해요</p></div></div>

      <section class="glass-card settings-card" style="--c:var(--accent)">
        <h3><i data-lucide="image"></i>프로필 사진</h3>
        <div class="avatar-current">
          <span class="avatar xl ${u.avatarType && u.avatarType !== "initial" ? "has-image" : ""}" id="avatar-big">${avatarInner(u)}</span>
          <div class="avatar-actions">
            <label class="btn-primary"><i data-lucide="upload"></i>내 사진 올리기<input type="file" id="avatar-file" accept="image/png,image/jpeg,image/webp" hidden /></label>
            <button class="btn-ghost glassy" data-avatar="initial"><i data-lucide="type"></i>이름 첫 글자</button>
            <p class="mini">사진은 정사각형으로 맞춰 저장하고, 사진 속 위치·기기 정보는 지워요</p>
          </div>
        </div>
        <p class="settings-sub">Eureka 캐릭터</p>
        <div class="preset-grid">${Object.entries(PRESETS).map(([k, p]) => `
          <button class="preset ${u.avatarType === "preset" && u.avatarPreset === k ? "on" : ""}" data-avatar="${k}" title="${p.name}">
            <span class="avatar lg has-image">${presetSVG(k)}</span><small>${p.name}</small></button>`).join("")}</div>
      </section>

      <form class="glass-card settings-card" id="profile-form" novalidate style="--c:var(--accent)">
        <h3><i data-lucide="id-card"></i>내 정보</h3>
        <div class="two">
          <div class="field"><label for="s-name">이름</label><input id="s-name" value="${esc(u.name)}" maxlength="40" autocomplete="name" /></div>
          <div class="field"><label for="s-email">이메일</label><input id="s-email" value="${esc(u.email ?? "로컬 모드")}" disabled /></div>
        </div>
        <div class="two">
          <div class="field"><label for="s-birth">생년월일 <small>· 선택</small></label><input id="s-birth" type="date" min="1900-01-01" max="${new Date().toISOString().slice(0, 10)}" value="${u.birthDate ?? ""}" autocomplete="bday" /></div>
          <div class="field"><label for="s-goal">하루 목표</label><input id="s-goal" type="number" min="1" max="200" value="${u.dailyGoal}" /></div>
        </div>
        <div class="two">
          <div class="field suggest"><label for="s-school">학교 <small>· 선택</small></label>
            <input id="s-school" value="${esc(u.school ?? "")}" maxlength="80" placeholder="학교 이름으로 검색 (예: 여의도고)" autocomplete="off"
              role="combobox" aria-autocomplete="list" aria-controls="school-list" aria-expanded="false" />
            <ul class="suggest-list" id="school-list" role="listbox" hidden></ul>
            <p class="mini">전국 초·중·고 (나이스) · 목록에 없으면 그대로 적어도 돼요</p></div>
          <div class="field"><label for="s-major">전공 · 계열 <small>· 선택</small></label>
            <input id="s-major" value="${esc(u.major ?? "")}" maxlength="80" placeholder="예: 자연계열, 컴퓨터공학과" autocomplete="off" />
            <div class="quick">${MAJOR_PRESETS.map((x) => `<button type="button" class="tag" data-major="${x}">${x}</button>`).join("")}</div></div>
        </div>
        <div class="field"><label for="s-address">주소지 <small>· 선택</small></label>
          <div class="addr-row">
            <input id="s-address" value="${esc(u.address ?? "")}" readonly placeholder="주소 검색을 눌러 찾아 주세요" />
            <button type="button" class="btn-ghost glassy" id="addr-search"><i data-lucide="search"></i>주소 검색</button>
            <button type="button" class="btn-ghost glassy" id="addr-clear" ${u.address ? "" : "hidden"} aria-label="주소 지우기"><i data-lucide="x"></i></button>
          </div>
          <input id="s-address-detail" maxlength="60" placeholder="상세 주소 (선택) · 동·호수까지는 적지 않아도 돼요" autocomplete="off" hidden />
          <div class="addr-embed" id="addr-embed" hidden></div></div>
        <div class="settings-foot"><button class="btn-primary" type="submit"><i data-lucide="check"></i>저장</button></div>
      </form>

      ${Store.mode === "api" ? `<section class="glass-card settings-card" style="--c:#22c55e">
        <h3><i data-lucide="key-round"></i>로그인 방법</h3>
        <div id="login-methods"><p class="mini">불러오는 중…</p></div>
      </section>` : ""}

      <section class="glass-card settings-card" style="--c:#94a3b8">
        <h3><i data-lucide="shield"></i>계정</h3>
        <div class="settings-row"><span>${Store.mode === "api" ? `${esc(u.email)}로 로그인했어요` : "로컬 모드 (브라우저에만 저장)"}</span>
          <button class="btn-ghost glassy" id="s-logout"><i data-lucide="log-out"></i>로그아웃</button></div>
        ${Store.mode === "api" ? `<details class="leave">
          <summary>회원 탈퇴</summary>
          <form id="leave-form" novalidate>
            <p>탈퇴하면 학습 기록, 오답노트, 프로젝트, 암기 카드, 올린 기출 파일이 <b>모두 지워지고 되살릴 수 없어요.</b>
              장애 복구용 백업에는 최대 90일 남았다가 자동으로 지워져요. <a href="privacy.html#p4" target="_blank" rel="noopener">자세히</a></p>
            <div class="field"><label for="leave-email">확인을 위해 이메일 <b>${esc(u.email)}</b> 을 입력해 주세요</label>
              <input id="leave-email" type="email" autocomplete="off" placeholder="${esc(u.email)}" /></div>
            <div class="settings-foot"><button class="btn-primary danger" type="submit" id="leave-submit" disabled><i data-lucide="user-x"></i>탈퇴하기</button></div>
          </form>
        </details>` : ""}
      </section>`;

    const refreshAvatar = () => {
      const big = $("#avatar-big");
      big.innerHTML = avatarInner(Store.state.user);
      big.classList.toggle("has-image", Store.state.user.avatarType !== "initial");
      $$(".preset").forEach((b) => b.classList.toggle("on", Store.state.user.avatarType === "preset" && Store.state.user.avatarPreset === b.dataset.avatar));
    };
    view.onclick = async (e) => {
      const major = e.target.closest("[data-major]");
      if (major) { $("#s-major").value = major.dataset.major; return; }
      const pick = e.target.closest("[data-avatar]");
      if (!pick) return;
      try {
        await Store.setAvatar(pick.dataset.avatar);
        refreshAvatar();
        toast(pick.dataset.avatar === "initial" ? "이름 첫 글자로 바꿨어요" : `'${PRESETS[pick.dataset.avatar].name}' 캐릭터로 바꿨어요`);
      } catch (err) { toast(err.message); }
    };
    $("#avatar-file").addEventListener("change", async (e) => {
      const file = e.target.files[0];
      e.target.value = "";
      if (!file) return;
      if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) return toast("PNG·JPG·WEBP 사진만 올릴 수 있어요");
      if (file.size > 5 * 1048576) return toast("사진은 5MB 까지 올릴 수 있어요");
      try {
        await Store.setAvatarPhoto(file);
        refreshAvatar();
        toast("프로필 사진을 바꿨어요");
      } catch (err) { toast(err.message); }
    });
    bindSuggest($("#s-school"), $("#school-list"), async (q) => (await Store.searchSchools(q)).map((s) => ({
      label: s.name, sub: [s.kind, s.address ?? s.region].filter(Boolean).join(" · "), value: s.name })));
    const addr = $("#s-address"), addrDetail = $("#s-address-detail"), addrBox = $("#addr-embed"), addrClear = $("#addr-clear");
    $("#addr-search").addEventListener("click", async () => {
      if (!addrBox.hidden) { addrBox.hidden = true; return; }
      try { await loadPostcode(); } catch (err) { return toast(err.message); }
      addrBox.hidden = false;
      addrBox.innerHTML = "";
      new daum.Postcode({
        width: "100%", height: "100%",
        oncomplete: (d) => {
          // 고른 쪽(도로명 R / 지번 J) 주소, 아파트면 건물 이름을 덧붙인다
          const base = d.userSelectedType === "J" ? d.jibunAddress : d.roadAddress;
          addr.value = d.userSelectedType === "R" && d.apartment === "Y" && d.buildingName ? `${base} (${d.buildingName})` : base;
          addrDetail.value = "";
          addrDetail.hidden = false;
          addrClear.hidden = false;
          addrBox.hidden = true;
          addrDetail.focus();
        },
      }).embed(addrBox);
    });
    addrClear.addEventListener("click", () => {
      addr.value = addrDetail.value = "";
      addrDetail.hidden = addrClear.hidden = addrBox.hidden = true;
    });
    $("#profile-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = e.currentTarget;
      $$(".invalid", f).forEach((x) => x.classList.remove("invalid"));
      const name = $("#s-name").value.trim();
      const goal = Number($("#s-goal").value);
      const birth = $("#s-birth").value;
      if (!name) return invalid($("#s-name"), "이름을 입력해 주세요");
      if (!(goal >= 1 && goal <= 200)) return invalid($("#s-goal"), "1에서 200 사이로 입력해 주세요");
      if (birth && (birth > new Date().toISOString().slice(0, 10) || birth < "1900-01-01")) return invalid($("#s-birth"), "생년월일을 확인해 주세요");
      const address = [addr.value.trim(), addrDetail.value.trim()].filter(Boolean).join(", ");
      if (address.length > 200) return invalid(addrDetail, "상세 주소를 줄여 주세요");
      try {
        await Store.updateUser({ name, dailyGoal: goal, birthDate: birth || null, school: $("#s-school").value.trim(),
          major: $("#s-major").value.trim(), address });
        addr.value = address;
        addrDetail.value = "";
        addrDetail.hidden = true;
        toast("저장했어요");
        renderSidebar();
      } catch (err) { toast(err.message); }
    });
    renderLoginMethods();
    $("#s-logout").addEventListener("click", () => {
      try { localStorage.removeItem("eureka.token"); localStorage.removeItem("eureka.user"); } catch { /* 무시 */ }
      location.href = "login.html";
    });
    const leave = $("#leave-form");
    if (leave) {
      const same = () => $("#leave-email").value.trim().toLowerCase() === u.email.toLowerCase();
      $("#leave-email").addEventListener("input", () => ($("#leave-submit").disabled = !same()));
      leave.addEventListener("submit", async (e) => {
        e.preventDefault();
        if (!same()) return;
        $("#leave-submit").disabled = true;
        try {
          await Store.deleteAccount($("#leave-email").value.trim());
          try { localStorage.removeItem("eureka.token"); localStorage.removeItem("eureka.user"); } catch { /* 무시 */ }
          location.href = "login.html#left";
        } catch (err) { toast(err.message); $("#leave-submit").disabled = false; }
      });
    }
  }

  // ================= 피드백 · 문제 신고 =================
  const FEEDBACK_KINDS = { problem: "문제·정답 오류", solution: "해설 오류", review: "서술형 채점 이상", feature: "기능 제안", bug: "버그", other: "기타" };
  function feedbackModal({ problemId = null, kind = null } = {}) {
    if (Store.mode !== "api") return toast("피드백은 로그인한 서버 화면에서 보낼 수 있어요");
    const p = problemId && Store.problem(problemId);
    const kinds = Object.keys(FEEDBACK_KINDS).filter((k) => p || !["problem", "solution", "review"].includes(k));
    let chosen = kind && kinds.includes(kind) ? kind : kinds[0];
    const page = location.hash || "#/";
    const PAGE_NAME = { chat: "대화", project: "프로젝트", notes: "오답노트", library: "라이브러리", settings: "계정 설정", admin: "피드백 관리" };
    const pageName = PAGE_NAME[route().parts[0]] ?? "새 학습";
    formModal({
      title: p ? "문제 신고" : "의견 보내기", submit: "보내기",
      body: `
        ${p ? `<div class="fb-problem"><small>${esc(conceptLabel(p))}</small><p data-math>${esc(p.stem.length > 140 ? `${p.stem.slice(0, 140)}…` : p.stem)}</p></div>` : ""}
        <div class="field"><label>종류</label>
          <div class="chips fb-kinds">${kinds.map((k) => `<label><input type="radio" name="fb-kind" value="${k}" ${k === chosen ? "checked" : ""} /><span>${FEEDBACK_KINDS[k]}</span></label>`).join("")}</div></div>
        <div class="field"><label for="fb-message">내용</label>
          <textarea id="fb-message" rows="5" maxlength="2000" placeholder="${p ? "어디가 이상한지 알려 주세요 (예: 정답이 3번이 아니라 4번 같아요)" : "불편한 점, 바라는 기능을 자유롭게 적어 주세요"}"></textarea></div>
        <label class="check"><input type="checkbox" id="fb-page" checked /> 지금 보던 화면(${pageName}) 정보 함께 보내기</label>
        <p class="mini">${p ? "같은 문제에 신고가 쌓이면 확인할 때까지 다른 학생에게 나가지 않아요. " : ""}답변은 로그인하신 계정으로 안내드립니다.</p>`,
      onMount: (f) => {
        f.addEventListener("change", (e) => { if (e.target.name === "fb-kind") chosen = e.target.value; });
        setTimeout(() => $("#fb-message", f)?.focus(), 40);
      },
      onSubmit: (f) => {
        const message = $("#fb-message", f).value.trim();
        if (message.length < 2) { invalid($("#fb-message", f), "내용을 적어 주세요"); return false; }
        const btn = $("button[type=submit]", f);
        btn.disabled = true;
        Store.sendFeedback({ kind: chosen, message, problem_id: p ? problemId : null, page: $("#fb-page", f).checked ? page : null })
          .then(() => { closeOverlays(); toast(p ? "신고해 주셔서 고마워요. 확인해서 바로잡을게요" : "의견을 보냈어요. 고마워요"); })
          .catch((err) => { toast(err.message); btn.disabled = false; });
        return false;
      },
    });
  }
  $("#feedback-btn").addEventListener("click", () => feedbackModal());

  // ================= 알림 =================
  // 종 버튼: 안 읽은 알림이 있을 때만 점, 누르면 목록. 화면이 보이는 동안 1분마다 새 알림 확인
  const NOTIFY_ICON = { material: "file-check-2", feedback_reply: "message-square-reply", announcement: "megaphone",
    review_due: "rotate-ccw", exam_dday: "calendar-clock", cards_due: "layers", streak: "flame" };
  const bell = $("#notify-btn");
  let notifyItems = [];
  function setUnread(n) {
    $(".dot", bell).hidden = !n;
    bell.title = n ? `알림 ${n}개` : "알림";
    bell.setAttribute("aria-label", bell.title);
  }
  async function refreshNotifications() {
    if (Store.mode !== "api") return;
    try { const r = await Store.notifications(); notifyItems = r.items; setUnread(r.unread); } catch { /* 다음 차례에 다시 */ }
  }
  setInterval(() => { if (document.visibilityState === "visible") refreshNotifications(); }, 60_000);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") refreshNotifications(); });

  let notifyPanel = null;
  const closeNotify = () => { notifyPanel?.remove(); notifyPanel = null; document.removeEventListener("mousedown", notifyOutside); };
  const notifyOutside = (e) => { if (notifyPanel && !notifyPanel.contains(e.target) && !bell.contains(e.target)) closeNotify(); };
  function drawNotify() {
    const unread = notifyItems.filter((n) => !n.read_at).length;
    notifyPanel.innerHTML = `
      <div class="np-head"><b>알림</b>${unread ? `<button type="button" data-read-all>모두 읽음</button>` : ""}</div>
      <div class="np-list">${notifyItems.length ? notifyItems.map((n) => `
        <button type="button" class="np-item ${n.read_at ? "" : "unread"}" data-nid="${n.id}">
          <span class="np-icon k-${n.kind}"><i data-lucide="${NOTIFY_ICON[n.kind] ?? "bell"}"></i></span>
          <span class="np-text"><b>${esc(n.title)}</b>${n.body ? `<small>${esc(n.body)}</small>` : ""}<em>${relTime(Date.parse(n.created_at))}</em></span>
        </button>`).join("") : '<p class="np-empty">새 알림이 없어요</p>'}</div>`;
    lucide.createIcons();
  }
  async function openNotify() {
    if (notifyPanel) return closeNotify();
    if (Store.mode !== "api") return toast("알림은 로그인한 서버 화면에서 볼 수 있어요");
    closeMenu();
    notifyPanel = document.createElement("div");
    notifyPanel.className = "notify-panel";
    notifyPanel.innerHTML = '<p class="np-empty">불러오는 중…</p>';
    document.body.append(notifyPanel);
    const r = bell.getBoundingClientRect();
    notifyPanel.style.top = `${r.bottom + 8}px`;
    notifyPanel.style.right = `${Math.max(8, innerWidth - r.right)}px`;
    setTimeout(() => document.addEventListener("mousedown", notifyOutside));
    await refreshNotifications();
    if (!notifyPanel) return;
    drawNotify();
    notifyPanel.addEventListener("click", async (e) => {
      if (e.target.closest("[data-read-all]")) {
        notifyItems.forEach((n) => (n.read_at ??= new Date().toISOString()));
        setUnread(0);
        drawNotify();
        Store.readNotifications().catch(() => {});
        return;
      }
      const item = e.target.closest("[data-nid]");
      if (!item) return;
      const n = notifyItems.find((x) => x.id === item.dataset.nid);
      if (!n.read_at) {
        n.read_at = new Date().toISOString();
        setUnread(notifyItems.filter((x) => !x.read_at).length);
        Store.readNotifications([n.id]).catch(() => {});
      }
      closeNotify();
      if (n.link) location.hash = n.link.replace(/^#/, "");
      else openSheet({ title: n.title, body: `<p class="notice-body">${esc(n.body ?? "")}</p>`, onSubmit: () => {},
        footer: '<div class="modal-foot"><button type="submit" class="btn-primary">확인</button></div>' });
    });
  }
  bell.addEventListener("click", openNotify);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && notifyPanel) closeNotify(); });

  // ================= 모달 =================
  function invalid(input, msg) {
    input.classList.add("invalid");
    let err = input.parentElement.querySelector(".err");
    if (!err) { err = document.createElement("p"); err.className = "err"; input.after(err); }
    err.textContent = msg;
    input.focus();
    return false;
  }

  function openSheet({ title, body, wide = false, footer = "", onMount, onSubmit }) {
    closeOverlays();
    const bd = document.createElement("div");
    bd.className = "backdrop";
    bd.innerHTML = `
      <form class="modal ${wide ? "wide" : ""}" novalidate role="dialog" aria-label="${esc(title)}">
        <div class="modal-head"><h2>${esc(title)}</h2><button type="button" class="icon-btn" data-close aria-label="닫기"><i data-lucide="x"></i></button></div>
        <div class="modal-body">${body}</div>
        ${footer}
      </form>`;
    document.body.append(bd);
    const form = $("form", bd);
    bd.addEventListener("mousedown", (e) => { if (e.target === bd) closeOverlays(); });
    $$("[data-close]", bd).forEach((b) => (b.onclick = closeOverlays));
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      if (onSubmit && onSubmit(form) !== false) closeOverlays();
    });
    onMount?.(form);
    icons();
    setTimeout(() => form.querySelector(".modal-body input, .modal-body select")?.focus(), 30);
    return form;
  }

  const formModal = ({ title, body, submit = "확인", danger = false, onSubmit, onMount }) => openSheet({
    title, body, onSubmit, onMount,
    footer: `<div class="modal-foot"><button type="button" class="btn-ghost" data-close>취소</button><button type="submit" class="btn-primary ${danger ? "danger" : ""}">${esc(submit)}</button></div>`,
  });

  const confirmModal = ({ title, text, action = "삭제", run }) =>
    formModal({ title, body: `<p>${text}</p>`, submit: action, danger: true, onSubmit: () => { run(); } });

  function renameModal(s) {
    formModal({
      title: "대화 이름 바꾸기", submit: "저장",
      body: `<div class="field"><label for="f-title">이름</label><input id="f-title" value="${esc(s.title)}" maxlength="40" /></div>`,
      onSubmit: (f) => {
        const v = $("#f-title", f).value.trim();
        if (!v) return invalid($("#f-title", f), "이름을 입력해 주세요");
        Store.updateSession(s.id, { title: v });
        if (navKey() === `chat:${s.id}`) renderChat(s.id, { keepScroll: true });
      },
    });
  }

  function moveModal(s) {
    const opts = [{ id: "", name: "프로젝트 없음", icon: "folder-open" }, ...Store.state.projects.map((p) => ({ id: p.id, name: p.name, icon: "folder", c: COLOR[projectDomain(p)] }))];
    formModal({
      title: "프로젝트로 옮기기", submit: "옮기기",
      body: `<div class="radio-list">${opts.map((o) => `
        <label><input type="radio" name="proj" value="${o.id}" ${(s.projectId ?? "") === o.id ? "checked" : ""} />
          <i data-lucide="${o.icon}" style="color:${o.c ?? "var(--ink-3)"}"></i>${esc(o.name)}</label>`).join("")}</div>`,
      onSubmit: (f) => {
        const v = f.querySelector('input[name="proj"]:checked').value || null;
        Store.updateSession(s.id, { projectId: v });
        toast(v ? `${Store.project(v).name}(으)로 옮겼어요` : "프로젝트에서 뺐어요");
        if (navKey() === `chat:${s.id}`) renderChat(s.id, { keepScroll: true });
      },
    });
  }

  // 새 프로젝트 / 프로젝트 수정
  function projectModal(p = null) {
    const subjectOptions = DOMAINS.map((d) => `
      <optgroup label="${DOMAIN_NAME[d]}">
        ${SUBJECTS.filter((s) => s.domain === d).map((s) => `<option value="${s.id}" ${p?.subjectId === s.id ? "selected" : ""}>${esc(s.name)}</option>`).join("")}
      </optgroup>`).join("");
    // ISBN 이 있으면 책 카드로 (이름만 있으면 칸만)
    const bookState = { isbn: p?.textbookIsbn ?? null,
      book: p?.textbookIsbn ? { title: p.textbook, authors: [], publisher: "", year: "", isbn: p.textbookIsbn } : null };
    formModal({
      title: p ? "프로젝트 수정" : "새 프로젝트", submit: p ? "저장" : "만들기",
      body: `
        <div class="field"><label for="f-pname">이름</label><input id="f-pname" placeholder="예: 2027 수능 미적분" value="${esc(p?.name ?? "")}" maxlength="30" /></div>
        <div class="field"><label for="f-subject">과목</label>
          <select id="f-subject"><option value="" disabled ${p ? "" : "selected"}>과목을 고르세요</option>${subjectOptions}</select></div>
        <div class="field" id="f-units-wrap" hidden><label>학습 범위 <small>· 고르지 않으면 과목 전체</small></label><div class="chips" id="f-units"></div></div>
        <div class="field"><label for="f-qtype">문제 형태</label>
          <select id="f-qtype">${Object.entries(QTYPE).map(([k, v]) => `<option value="${k}" ${(p?.questionType ?? "auto") === k ? "selected" : ""}>${v}</option>`).join("")}</select></div>
        <div class="two">
          <div class="field"><label for="f-goal">목표 <small>· 선택</small></label><input id="f-goal" placeholder="예: 1등급" value="${esc(p?.goal ?? "")}" maxlength="20" /></div>
          <div class="field"><label for="f-date">시험일 <small>· 선택</small></label><input id="f-date" type="date" value="${p?.examDate ?? ""}" /></div>
        </div>
        <div class="field suggest"><label for="f-textbook">시험 교재 <small>· 선택 · 이름이나 ISBN 으로 찾기</small></label>
          <input id="f-textbook" placeholder="교재 이름이나 ISBN" value="${esc(p?.textbook ?? "")}" maxlength="120" autocomplete="off" />
          <ul class="suggest-list" id="f-book-list" role="listbox" hidden></ul>
          <div class="book-card" id="f-book" hidden></div></div>`,
      onMount(f) {
        bindBookField($("#f-textbook", f), $("#f-book-list", f), $("#f-book", f), bookState);
        const sel = $("#f-subject", f);
        const drawUnits = () => {
          const units = childrenOf(sel.value);
          $("#f-units-wrap", f).hidden = !units.length;
          $("#f-units", f).innerHTML = units.map((u) => `
            <label><input type="checkbox" value="${u.id}" ${p?.subjectId === sel.value && p.unitIds.includes(u.id) ? "checked" : ""} /><span>${esc(u.name)}</span></label>`).join("");
        };
        sel.addEventListener("change", () => { sel.classList.remove("invalid"); drawUnits(); });
        if (sel.value) drawUnits();
      },
      onSubmit(f) {
        const name = $("#f-pname", f).value.trim();
        const subjectId = $("#f-subject", f).value;
        if (!name) return invalid($("#f-pname", f), "이름을 입력해 주세요");
        if (!subjectId) return invalid($("#f-subject", f), "과목을 골라 주세요");
        const data = {
          name, subjectId,
          unitIds: $$("#f-units input:checked", f).map((i) => i.value),
          goal: $("#f-goal", f).value.trim(),
          textbook: $("#f-textbook", f).value.trim(),
          textbookIsbn: bookState.isbn,
          examDate: $("#f-date", f).value || null,
          questionType: $("#f-qtype", f).value,
        };
        if (p) {
          Store.updateProject(p.id, data);
          if (navKey() === `project:${p.id}`) { renderProject(p.id); icons(); }
          toast("프로젝트를 저장했어요");
        } else {
          const id = Store.createProject(data);
          go(`/project/${id}`);
          toast("프로젝트를 만들었어요");
        }
      },
    });
  }


  // ================= 새 프로젝트 =================
  const QTYPE = { auto: "시험 형식대로", multiple_choice: "객관식", text: "주관식 (글자)", numeric: "수치형", essay: "서술형",
    short_answer: "단답형 (정수)", mixed: "객관식 + 단답형" };
  const FORMAT_NAME = { multiple_choice: "객관식", short_answer: "단답형", text: "주관식", numeric: "수치형", essay: "서술형" };
  // "코스 형식대로"가 실제로 무엇인지 (예: 객관식 4지선다 · 주관식)
  const courseFormats = (courseId) => {
    const c = courseMap[courseId];
    const fs = c?.formats?.length ? c.formats : ["multiple_choice"];
    return fs.map((f) => (f === "multiple_choice" ? `객관식 ${c?.choice_count ?? 5}지선다` : FORMAT_NAME[f] ?? f)).join(" · ");
  };
  const qtypeLabel = (p) => (p.questionType === "auto" || !p.questionType ? courseFormats(p.subjectId) : QTYPE[p.questionType]);
  const UPLOAD_TYPES = ["application/pdf", "image/png", "image/jpeg", "image/webp"];
  const fmtSize = (n) => (n > 1048576 ? `${(n / 1048576).toFixed(1)}MB` : `${Math.max(1, Math.round(n / 1024))}KB`);
  const isoAfter = (days) => new Date(Date.now() + days * DAY - new Date().getTimezoneOffset() * 6e4).toISOString().slice(0, 10);

  // 파일 고르기 영역 (마법사·업로드 창 공용). onChange(files) 로 바뀐 목록을 알린다
  function dropzoneHTML({ kinds = true, multiple = true } = {}) {
    return `
      ${kinds ? `<div class="chips mat-kind">
        <label><input type="radio" name="mat-kind" value="past_exam" checked /><span>기출·시험지</span></label>
        <label><input type="radio" name="mat-kind" value="textbook" /><span>교재 페이지</span></label>
      </div>` : ""}
      <label class="dropzone" data-drop>
        <input type="file" accept=".pdf,image/png,image/jpeg,image/webp" ${multiple ? "multiple" : ""} hidden />
        <i data-lucide="upload-cloud"></i>
        <b>파일을 끌어다 놓거나 눌러서 고르세요</b>
        <span>PDF(30쪽 이하) 또는 사진 · 파일당 20MB까지 · 여러 개 가능</span>
      </label>
      <ul class="file-list" data-files></ul>
      <label class="check rights"><input type="checkbox" data-rights /> 본인이 학습용으로 쓸 수 있는 자료예요 <small>(올린 자료와 그것으로 만든 문제는 나에게만 보여요)</small></label>`;
  }
  function bindDropzone(root, files, onChange) {
    const zone = $("[data-drop]", root), input = $("input[type=file]", zone);
    const add = (list) => {
      for (const f of list) {
        if (!UPLOAD_TYPES.includes(f.type)) { toast(`${f.name}: PDF나 사진만 올릴 수 있어요`); continue; }
        if (f.size > 20 * 1048576) { toast(`${f.name}: 20MB를 넘어요`); continue; }
        files.push(f);
      }
      draw();
    };
    const draw = () => {
      $("[data-files]", root).innerHTML = files.map((f, i) => `
        <li><i data-lucide="${f.type === "application/pdf" ? "file-text" : "image"}"></i><span>${esc(f.name)}</span><small>${fmtSize(f.size)}</small>
          <button type="button" class="icon-btn" data-remove="${i}" aria-label="빼기"><i data-lucide="x"></i></button></li>`).join("");
      icons();
      onChange(files);
    };
    input.addEventListener("change", () => { add(input.files); input.value = ""; });
    zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("over"));
    zone.addEventListener("drop", (e) => { e.preventDefault(); zone.classList.remove("over"); add(e.dataTransfer.files); });
    $("[data-files]", root).addEventListener("click", (e) => {
      const b = e.target.closest("[data-remove]");
      if (b) { files.splice(Number(b.dataset.remove), 1); draw(); }
    });
    draw();
  }

  async function uploadAll(projectId, files, kind = "past_exam") {
    const made = [];
    for (const f of files) {
      try { made.push(await Store.uploadMaterial(projectId, f, true, kind)); } catch (e) { toast(`${f.name}: ${e.message}`); }
    }
    return made;
  }

  // 글로 적으면 알아듣는 부분 — 과목·목표·시험일·범위
  // 코스 별칭 = 서버 코스의 aliases + 코스 이름 (가장 길게 맞는 것이 이긴다 — 수학II > 수학I)
  const courseKeys = () => COURSES.map((c) => [c.id, [...new Set([...(c.aliases ?? []), norm(c.title)])]]);
  const norm = (s) => s.toLowerCase().replace(/Ⅱ/g, "ii").replace(/Ⅰ/g, "i").replace(/\s+/g, "");
  const nameWords = (s) => s.split(/[\s·,()과와의]+/).filter((x) => x.length >= 2);
  function readExam(text) {
    const t = norm(text);
    // 숫자로 끝나는 별칭은 뒤에 숫자·등급·점·문제가 붙으면 아님 ("수학 10문제", "수학 2등급" 은 수학I·II 가 아니다)
    // (띄어쓰기를 지우면 "물1 3문제" 가 "물13" 이 되므로 이 경우는 띄어쓰기를 남긴 글에서 본다)
    const spaced = text.toLowerCase().replace(/Ⅱ/g, "ii").replace(/Ⅰ/g, "i").replace(/\s+/g, " ");
    const found = (k) => (/\d$/.test(k)
      ? new RegExp(`${[...k].join("\\s*")}(?!\\d|등급|점|문제|문항|개)`).test(spaced) : t.includes(k));
    let best = null; // [코스 id, 맞은 길이, 공식 코스인지]
    for (const [id, keys] of courseKeys()) for (const k of keys) {
      if (!k || !found(k)) continue;
      const cand = [id, k.length, courseMap[id]?.source === "template"];
      if (!best || cand[1] > best[1] || (cand[1] === best[1] && cand[2] && !best[2])) best = cand;
    }
    const subjectId = best?.[0] ?? null;
    const grade = text.match(/([1-9])\s*등급/), score = text.match(/(\d{2,3})\s*점/);
    const goal = grade ? `${grade[1]}등급` : score ? `${score[1]}점` : "";
    let examDate = null;
    const md = text.match(/(\d{1,2})\s*월\s*(\d{1,2})\s*일/);
    if (md) {
      const pad = (n) => String(n).padStart(2, "0"), y = new Date().getFullYear();
      let iso = `${y}-${pad(md[1])}-${pad(md[2])}`;
      if (iso < isoAfter(0)) iso = `${y + 1}-${pad(md[1])}-${pad(md[2])}`;
      if (!Number.isNaN(Date.parse(iso))) examDate = iso;
    }
    return { subjectId, goal, examDate };
  }
  // 과목 칸에 적은 글 → 코스 id. 정확한 이름이 먼저, 아니면 별칭(수1·확통·편입수학 …)
  const subjectFromText = (text) => COURSES.find((c) => norm(c.title) === norm(text))?.id ?? readExam(text).subjectId;
  // 과목 칸 후보: 모든 공개 코스에서 이름·시험·별칭으로 (공식 코스 먼저)
  const matchSubjects = (q) => {
    const t = norm(q);
    return COURSES.filter((c) => norm(c.title).includes(t) || (c.exam && norm(c.exam).includes(t))
      || (c.aliases ?? []).some((k) => k.startsWith(t) || t.startsWith(k)))
      .sort((a, b) => (a.source === "user") - (b.source === "user")).slice(0, 8);
  };
  const courseSub = (c) => [c.exam, c.category, c.level, `${c.units}개 단원`, courseFormats(c.id), c.source === "user" ? "사용자 코스" : "공식"].filter(Boolean).join(" · ");
  // "적분법까지", "수열 빼고", "전 범위" → 단원 id 목록 ([] 이면 과목 전체, null 이면 못 알아들음)
  function readScope(text, subjectId) {
    const units = childrenOf(subjectId), t = norm(text);
    if (!t || /전범위|전체|다나와|모두/.test(t)) return [];
    const hit = (c) => nameWords(c.name).some((x) => t.includes(norm(x)));
    const matched = units.filter((u) => hit(u) || childrenOf(u.id).some(hit));
    if (!matched.length) return null;
    if (/빼고|제외|말고/.test(t)) return units.filter((u) => !matched.includes(u)).map((u) => u.id);
    if (/까지/.test(t)) return units.slice(0, units.indexOf(matched[matched.length - 1]) + 1).map((u) => u.id);
    return matched.map((u) => u.id);
  }

  // 새 프로젝트 — 한 화면에서 글로 적으면 과목·목표·시험일·범위를 알아듣고, 아래 칸은 고쳐 쓸 수 있다
  function projectWizard() {
    const w = { exam: "", subjectId: null, subjectPicked: false, unitIds: [], scope: "",
      examDate: isoAfter(30), dateShown: false, dateTouched: false, goal: "", goalTouched: false, nameTouched: false,
      questionType: "auto", textbook: "", files: [], busy: false, book: null, isbn: null };
    const sheet = openSheet({
      title: "새 프로젝트", wide: true,
      body: `
        <div class="np">
          <label class="np-q" for="np-exam">어떤 시험을 준비하나요?</label>
          <input id="np-exam" class="np-big" autocomplete="off" maxlength="60"
            placeholder="예: 2027 수능 미적분 1등급 · 화학I 중간고사 90점, 4월 25일" />
          <div class="np-read" data-read></div>
          <div class="two np-basic">
            <div class="field suggest"><label for="np-subject">준비 과목</label>
              <input id="np-subject" autocomplete="off" maxlength="30" placeholder="예: 미적분, 수학I, 화학I"
                role="combobox" aria-autocomplete="list" aria-controls="subject-list" aria-expanded="false" />
              <ul class="suggest-list" id="subject-list" role="listbox" hidden></ul>
              <p class="mini" data-subject-hint></p>
              <button type="button" class="link-btn" data-new-course>찾는 코스가 없나요? 출제 범위로 새 코스 만들기</button></div>
            <div class="field suggest"><label for="np-textbook">시험 교재 <small>· 선택</small></label>
              <input id="np-textbook" autocomplete="off" maxlength="120" placeholder="교재 이름이나 ISBN (예: 수능특강 미적분)"
                role="combobox" aria-autocomplete="list" aria-controls="book-list" aria-expanded="false" />
              <ul class="suggest-list" id="book-list" role="listbox" hidden></ul>
              <div class="book-card" data-book hidden></div>
              <p class="mini">목록에서 고르면 책 정보가 함께 저장돼요. 이름만 적어도 괜찮아요</p></div>
          </div>
          <div class="np-newcourse" data-newcourse hidden>
            <h4><i data-lucide="sparkles"></i>새 코스 만들기 <small>출제 범위를 붙여넣으면 AI가 단원·개념으로 정리해요 · 만든 코스는 모두에게 공개돼요</small></h4>
            <div class="two">
              <div class="field"><label for="nc-title">코스 이름</label><input id="nc-title" maxlength="120" placeholder="예: 편입 수학 (미적분학)" /></div>
              <div class="field"><label for="nc-exam">시험 <small>· 선택</small></label><input id="nc-exam" maxlength="120" placeholder="예: 편입, CPA 1차, 토익" /></div>
            </div>
            <div class="field"><label for="nc-level">수준 <small>· 선택</small></label>
              <div class="chips nc-levels">${["중학", "고등", "대학", "자격증", "공무원", "어학"].map((x) => `<label><input type="radio" name="nc-level" value="${x}" /><span>${x}</span></label>`).join("")}</div></div>
            <div class="field"><label for="nc-scope">출제 범위 <small>· 교재 목차나 시험 공고의 범위를 그대로 붙여넣어 주세요</small></label>
              <textarea id="nc-scope" rows="7" maxlength="8000" placeholder="예)&#10;2. Limits and Derivatives&#10;3. Differentiation Rules&#10;7. Techniques of Integration"></textarea></div>
            <p class="mini">교재는 위 '시험 교재' 칸을 함께 써요. 책 내용은 읽지 않고, 범위의 주제로 새 문제를 만들어요.</p>
            <div class="fb-actions"><button type="button" class="btn-ghost" data-newcourse-cancel>닫기</button>
              <button type="button" class="btn-primary" data-newcourse-make><i data-lucide="sparkles"></i>AI로 코스 만들기</button></div>
          </div>
          <div class="np-more" data-more hidden>
            <div class="field"><label for="np-scope">시험 범위</label>
              <input id="np-scope" autocomplete="off" maxlength="60" placeholder="예: 적분법까지 · 수열 빼고 · 전 범위 (비우면 과목 전체)" />
              <div class="chips unit-chips" data-units></div><p class="mini" data-scope-count></p></div>
            <div class="two">
              <div class="field"><label for="w-date">시험일</label>
                <div class="date-row"><input id="w-date" type="date" min="${isoAfter(0)}" />
                  ${[["2주 뒤", 14], ["1개월 뒤", 30], ["3개월 뒤", 90]].map(([t, n]) => `<button type="button" class="tag" data-days="${n}">${t}</button>`).join("")}</div>
                <p class="mini" data-period></p></div>
              <div class="field"><label for="w-goal">목표 <small>· 선택</small></label><input id="w-goal" placeholder="예: 1등급, 90점" maxlength="20" /></div>
            </div>
            <div class="field"><label>문제 형태 <small data-auto-formats></small></label>
              <div class="seg qtype">${Object.entries(QTYPE).map(([k, v]) => `<button type="button" data-qtype="${k}" class="${w.questionType === k ? "on" : ""}">${v}</button>`).join("")}</div></div>
            <div class="field"><label for="w-name">프로젝트 이름</label><input id="w-name" maxlength="30" /></div>
            ${Store.mode === "api" ? `<details class="np-upload">
              <summary><i data-lucide="chevron-right"></i>기출·교재 올리기 <small>선택 · 올리면 그 시험·교재와 비슷한 결의 문제를 만들어 드려요</small></summary>
              ${dropzoneHTML()}</details>` : ""}
          </div>
        </div>`,
      footer: `<div class="modal-foot"><button type="button" class="btn-ghost" data-close>취소</button>
        <button type="submit" class="btn-primary" data-next disabled>만들기</button></div>`,
      onSubmit: () => { submit(); return false; },
    });
    const body = $(".modal-body", sheet);
    const subjectName = () => concept(w.subjectId)?.name ?? "";
    // 이름 기본값: 첫 칸에서 날짜·목표를 빼고 과목을 붙인다 ("2027 수능 1등급, 11월 19일" + 확통 → "2027 수능 확률과 통계")
    const defaultName = () => {
      const exam = courseMap[w.subjectId]?.exam;
      // 날짜·목표·'시험' 같은 말을 빼고, 코스 이름에 이미 있는 시험 이름도 뺀다 ("2027 편입 시험" + 편입 수학 → "2027 편입 수학")
      let base = w.exam.replace(/\d{1,2}\s*월\s*\d{1,2}\s*일|[1-9]\s*등급|\d{2,3}\s*점|[,·]|시험|준비|대비/g, " ");
      if (exam && subjectName().includes(exam)) base = base.replace(exam, " ");
      base = base.replace(/\s+/g, " ").trim();
      const subj = subjectName();
      const name = !base ? `${subj} 시험 준비` : courseKeys().some(([id, keys]) => id === w.subjectId && keys.some((k) => norm(base).includes(k))) || norm(base).includes(norm(subj)) ? base : `${base} ${subj}`;
      return name.slice(0, 30);
    };

    // 알아들은 것 (칩) + 과목 고르기 + 아래 칸 보이기
    function drawRead() {
      const chips = [];
      if (w.goal) chips.push(`<span class="np-chip"><i data-lucide="target"></i>목표 ${esc(w.goal)}</span>`);
      if (w.dateShown && w.examDate) chips.push(`<span class="np-chip"><i data-lucide="calendar"></i>시험일 ${esc(w.examDate)}</span>`);
      $("[data-read]", body).innerHTML = chips.join("");
      // 과목 칸: 첫 칸에서 알아들은 과목을 채우고(직접 적은 게 없을 때), 못 알아들으면 지원 과목을 알려 준다
      const subj = $("#np-subject"), hint = $("[data-subject-hint]", body);
      if (!w.subjectPicked) subj.value = subjectName();
      const typed = subj.value.trim();
      const typing = typed && !w.subjectId && matchSubjects(typed).length; // 아직 적는 중 (후보가 있음)
      const unknown = !w.subjectId && !typing && (typed || w.exam.trim());
      hint.classList.toggle("bad", !!unknown);
      const official = COURSES.filter((c) => c.source === "template").length;
      hint.textContent = typing ? "목록에서 고르거나 코스 이름을 끝까지 적어 주세요"
        : unknown ? (typed ? `'${typed}'에 맞는 코스가 아직 없어요. 아래 '새 코스 만들기'로 만들 수 있어요` : "준비 과목을 적어 주세요")
        : w.subjectId ? courseSub(courseMap[w.subjectId] ?? { category: DOMAIN_NAME[concept(w.subjectId)?.domain], units: childrenOf(w.subjectId).length })
        : `공식 코스 ${official}개 · 사용자 코스 ${COURSES.length - official}개 — 과목·시험·교재 이름으로 찾아보세요`;
      $("[data-more]", body).hidden = !w.subjectId;
      $("[data-next]", sheet).disabled = !w.subjectId;
      icons();
    }
    function drawUnits() {
      $("[data-units]", body).innerHTML = childrenOf(w.subjectId).map((u) => `
        <label><input type="checkbox" value="${u.id}" ${w.unitIds.includes(u.id) ? "checked" : ""} /><span>${esc(u.name)} <small>${childrenOf(u.id).length}</small></span></label>`).join("");
      const units = w.unitIds.length ? w.unitIds : childrenOf(w.subjectId).map((u) => u.id);
      const n = units.reduce((k, u) => k + childrenOf(u).length, 0);
      $("[data-scope-count]", body).textContent = `${w.unitIds.length ? `${w.unitIds.length}개 단원` : "과목 전체"} · 개념 ${n}개`;
    }
    function drawFields() {
      $("#w-date").value = w.examDate ?? "";
      const left = daysLeft(w.examDate);
      $("[data-period]", body).textContent = left != null && left >= 0 ? `준비 기간 ${left}일 · ${ddayLabel(left)}` : "";
      if (!w.goalTouched) $("#w-goal").value = w.goal;
      if (!w.nameTouched) $("#w-name").value = defaultName();
      $("[data-auto-formats]", body).textContent = w.subjectId ? `· 이 시험의 형식: ${courseFormats(w.subjectId)}` : "";
    }
    function setSubject(id) {
      if (id && !concept(id)) {
        Store.loadCourse(id).then(() => { loadConcepts(); setSubject(id); }).catch((err) => toast(err.message));
        return;
      }
      if (id !== w.subjectId) {
        w.subjectId = id;
        w.unitIds = (id && w.scope && readScope(w.scope, id)) || [];
        if (id) drawUnits();
      }
      drawRead();
      if (id) drawFields();
    }

    body.addEventListener("input", (e) => {
      const id = e.target.id;
      if (id === "np-exam") {
        w.exam = e.target.value;
        const r = readExam(w.exam);
        if (!w.goalTouched) w.goal = r.goal;
        if (r.examDate && !w.dateTouched) { w.examDate = r.examDate; w.dateShown = true; }
        setSubject(w.subjectPicked ? w.subjectId : r.subjectId);
      } else if (id === "np-subject") {
        const typed = e.target.value.trim();
        w.subjectPicked = !!typed; // 비우면 다시 첫 칸에서 알아들은 과목을 쓴다
        setSubject(typed ? subjectFromText(typed) : readExam(w.exam).subjectId);
      } else if (id === "np-textbook") {
        w.textbook = e.target.value;
      } else if (id === "np-scope") {
        w.scope = e.target.value;
        const ids = readScope(w.scope, w.subjectId);
        if (ids) { w.unitIds = ids; drawUnits(); }
      } else if (id === "w-goal") {
        w.goal = e.target.value; w.goalTouched = true; drawRead();
      } else if (id === "w-name") {
        w.nameTouched = true;
      }
    });
    const panel = $("[data-newcourse]", body);
    function openNewCourse() {
      panel.hidden = false;
      const typed = $("#np-subject").value.trim();
      if (!$("#nc-title").value) $("#nc-title").value = typed || w.exam.replace(/\d{1,2}\s*월\s*\d{1,2}\s*일|[1-9]\s*등급|\d{2,3}\s*점|[,·]/g, " ").replace(/\s+/g, " ").trim();
      icons();
      panel.scrollIntoView({ block: "nearest", behavior: "smooth" });
      $(typed ? "#nc-scope" : "#nc-title").focus();
    }
    async function makeCourse(btn) {
      const title = $("#nc-title").value.trim(), scope = $("#nc-scope").value.trim();
      if (title.length < 2) return invalid($("#nc-title"), "코스 이름을 적어 주세요");
      if (scope.length < 2) return invalid($("#nc-scope"), "출제 범위를 붙여넣어 주세요");
      btn.disabled = true;
      try {
        const c = await withAIProgress({
          title: "나만의 코스를 만드는 중",
          steps: ["출제 범위 읽기", "단원 나누기", "개념 정리하기"], expectMs: 40000,
          run: () => Store.createCourse({ title, scope_text: scope, exam: $("#nc-exam").value.trim(),
            level: $("input[name=nc-level]:checked", body)?.value ?? "", textbook: w.textbook.trim(), textbook_isbn: w.isbn }),
        });
        loadConcepts();
        panel.hidden = true;
        w.subjectPicked = true;
        $("#np-subject").value = c.title;
        setSubject(c.id);
        toast(`'${c.title}' 코스를 만들었어요 · 단원 ${c.units}개, 개념 ${c.concepts}개`);
      } catch (err) { toast(err.message); }
      btn.disabled = false;
      btn.innerHTML = '<i data-lucide="sparkles"></i>AI로 코스 만들기';
      icons();
    }
    body.addEventListener("click", (e) => {
      if (e.target.closest("[data-new-course]")) return openNewCourse();
      if (e.target.closest("[data-newcourse-cancel]")) { panel.hidden = true; return; }
      const make = e.target.closest("[data-newcourse-make]");
      if (make) return makeCourse(make);
      const days = e.target.closest("[data-days]");
      if (days) { w.examDate = isoAfter(Number(days.dataset.days)); w.dateTouched = w.dateShown = true; drawFields(); drawRead(); }
      const qt = e.target.closest("[data-qtype]");
      if (qt) { w.questionType = qt.dataset.qtype; $$("[data-qtype]", body).forEach((b) => b.classList.toggle("on", b === qt)); }
    });
    bindBookField($("#np-textbook"), $("#book-list"), $("[data-book]", body), w);
    // 과목 칸 후보 목록 (고르면 그 과목으로)
    bindSuggest($("#np-subject"), $("#subject-list"), async (q) => matchSubjects(q).map((c) => ({
      label: c.title, sub: courseSub(c), value: c.title })), 1);
    body.addEventListener("change", (e) => {
      if (e.target.id === "np-subject") {
        const typed = e.target.value.trim();
        w.subjectPicked = !!typed;
        setSubject(typed ? subjectFromText(typed) : readExam(w.exam).subjectId);
        if (typed && !subjectFromText(typed) && !matchSubjects(typed).length && panel.hidden) openNewCourse();
      }
      if (e.target.closest("[data-units]")) { w.unitIds = $$("[data-units] input:checked", body).map((i) => i.value); drawUnits(); }
      if (e.target.id === "w-date") { w.examDate = e.target.value || null; w.dateTouched = w.dateShown = true; drawFields(); drawRead(); }
    });

    const updateSubmit = () => { $("[data-next]", sheet).textContent = w.files.length ? `만들고 ${w.files.length}개 올리기` : "만들기"; };
    if (Store.mode === "api") bindDropzone(body, w.files, updateSubmit);

    function submit() {
      if (w.busy || !w.subjectId) return;
      const name = $("#w-name").value.trim();
      if (!w.examDate) return invalid($("#w-date"), "시험일을 골라 주세요");
      if (daysLeft(w.examDate) < 0) return invalid($("#w-date"), "오늘 이후 날짜를 골라 주세요");
      if (!name) return invalid($("#w-name"), "이름을 입력해 주세요");
      if (w.files.length && !$("[data-rights]", body)?.checked) return toast("학습용으로 쓸 수 있는 자료인지 확인해 주세요");
      finish(name);
    }
    async function finish(name) {
      w.busy = true;
      const btn = $("[data-next]", sheet);
      btn.disabled = true;
      btn.textContent = w.files.length ? "만들고 올리는 중…" : "만드는 중…";
      try {
        const id = await Store.createProject({ name, subjectId: w.subjectId, unitIds: w.unitIds, goal: (w.goal || "").trim(),
          textbook: w.textbook.trim(), textbookIsbn: w.isbn, examDate: w.examDate, questionType: w.questionType });
        const uploaded = w.files.length ? await uploadAll(id, w.files, $("input[name=mat-kind]:checked", body)?.value) : 0;
        closeOverlays();
        go(`/project/${id}`);
        toast(uploaded ? `프로젝트를 만들었어요. 기출 ${uploaded}개를 분석하고 있어요` : "프로젝트를 만들었어요");
      } catch (e) {
        toast(e.message);
        w.busy = false;
        btn.disabled = false;
        updateSubmit();
      }
    }
    drawRead();
  }

  function uploadSheet(projectId, onDone) {
    const files = [];
    openSheet({
      title: "기출·교재 올리기", body: dropzoneHTML(),
      footer: `<div class="modal-foot"><button type="button" class="btn-ghost" data-close>취소</button><button type="submit" class="btn-primary" data-up disabled>올리기</button></div>`,
      onMount(f) { bindDropzone(f, files, () => { $("[data-up]", f).disabled = !files.length; $("[data-up]", f).textContent = files.length ? `${files.length}개 올리기` : "올리기"; }); },
      onSubmit(f) {
        if (!$("[data-rights]", f).checked) { toast("학습용으로 쓸 수 있는 자료인지 확인해 주세요"); return false; }
        const btn = $("[data-up]", f);
        btn.disabled = true;
        btn.textContent = "올리는 중…";
        const kind = $("input[name=mat-kind]:checked", f)?.value;
        closeOverlays();
        withAIProgress({
          title: `${files.length}개 자료를 읽는 중`,
          steps: ["파일 올리기", "AI가 문항 읽기", "개념·난이도 분류"], expectMs: 30000 + files.length * 15000,
          run: async (p) => {
            const mats = await uploadAll(projectId, files, kind);
            if (!mats.length) return [];
            p.step(1);
            const ids = new Set(mats.map((x) => x.id));
            return waitFor(() => Store.listMaterials(projectId).then((l) => l.filter((x) => ids.has(x.id))),
              (l) => l.every((x) => x.status === "ready" || x.status === "failed"),
              { onTick: (l) => p.set(0.1 + 0.85 * (l.filter((x) => x.status === "ready" || x.status === "failed").length / ids.size)) });
          },
        }).then((l) => {
          const ok = l.filter((x) => x.status === "ready");
          if (ok.length) toast(`${ok.length}개 자료에서 문항 ${ok.reduce((a, x) => a + x.problem_count, 0)}개를 읽었어요`);
          l.filter((x) => x.status === "failed").forEach((x) => toast(`${x.filename}: ${x.error ?? "읽지 못했어요"}`));
        }).catch((err) => toast(err.message)).finally(onDone);
        return false;
      },
    });
  }

  // 정답 파일(정답표·해설지) 올리기 — 문제지 하나에 하나, 문항 번호로 1:1 매칭
  function uploadAnswerFile(projectId, materialId, onDone) {
    const files = [];
    openSheet({
      title: "정답 파일 연결", body: `<p class="modal-text">이 문제지의 정답표나 해설지를 올려 주세요. AI가 번호·정답·해설을 읽어 문항과 1:1로 맞춰요. 이미 연결된 정답 파일이 있으면 새 파일로 바뀌어요.</p>${dropzoneHTML({ kinds: false, multiple: false })}`,
      footer: `<div class="modal-foot"><button type="button" class="btn-ghost" data-close>취소</button><button type="submit" class="btn-primary" data-up disabled>연결하기</button></div>`,
      onMount(f) { bindDropzone(f, files, () => { if (files.length > 1) files.splice(0, files.length - 1); $("[data-up]", f).disabled = !files.length; }); },
      onSubmit(f) {
        if (!$("[data-rights]", f).checked) { toast("학습용으로 쓸 수 있는 자료인지 확인해 주세요"); return false; }
        const file = files[0];
        closeOverlays();
        withAIProgress({
          title: "정답 파일을 문항과 맞추는 중",
          steps: ["정답 파일 올리기", "번호·정답·해설 읽기", "문항과 1:1 매칭"], expectMs: 25000,
          run: async (p) => {
            const mat = await Store.uploadMaterial(projectId, file, true, "answer_sheet", materialId);
            p.step(1);
            return waitFor(() => Store.listMaterials(projectId).then((l) => l.find((x) => x.id === mat.id)),
              (x) => !x || x.status === "ready" || x.status === "failed");
          },
        }).then((x) => {
          if (x?.status === "ready") toast(`${x.answer_map.total}문항 중 ${x.answer_map.matched}문항의 정답을 연결했어요`);
          else if (x?.status === "failed") toast(x.error ?? "정답 파일을 읽지 못했어요");
        }).catch((err) => toast(err.message)).finally(onDone);
        return false;
      },
    });
  }

  // ================= 팝업 메뉴 =================
  let menuCleanup = null;
  function openMenu(anchor, items, onClose) {
    closeMenu();
    items = items.filter(Boolean);
    const m = document.createElement("div");
    m.className = "menu";
    m.setAttribute("role", "menu");
    m.innerHTML = items.map((it, i) => it === "-" ? "<hr />"
      : it.header ? `<div class="menu-label">${esc(it.label)}</div>`
      : `<button role="menuitem" data-i="${i}" class="${it.danger ? "danger" : ""} ${it.checked ? "checked" : ""}">${it.icon ? `<i data-lucide="${it.icon}"></i>` : ""}${esc(it.label)}</button>`).join("");
    document.body.append(m);
    icons();
    const r = anchor.getBoundingClientRect();
    const left = Math.min(Math.max(8, r.left), innerWidth - m.offsetWidth - 8);
    const below = r.bottom + 6 + m.offsetHeight < innerHeight;
    m.style.left = `${left}px`;
    m.style.top = `${below ? r.bottom + 6 : Math.max(8, r.top - m.offsetHeight - 6)}px`;
    m.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-i]");
      if (!b) return;
      closeMenu();
      items[b.dataset.i].run();
    });
    const outside = (e) => { if (!m.contains(e.target) && !anchor.contains(e.target)) closeMenu(); };
    setTimeout(() => document.addEventListener("mousedown", outside));
    menuCleanup = () => { m.remove(); document.removeEventListener("mousedown", outside); onClose?.(); };
    m.querySelector("button")?.focus({ preventScroll: true });
  }
  function closeMenu() { menuCleanup?.(); menuCleanup = null; }

  function closeOverlays() {
    closeMenu();
    $$(".backdrop").forEach((b) => b.remove());
  }

  // ================= ⌘K 검색 =================
  function openPalette() {
    closeOverlays();
    const bd = document.createElement("div");
    bd.className = "backdrop palette-wrap";
    bd.innerHTML = `
      <div class="palette" role="dialog" aria-label="검색">
        <label class="palette-input"><i data-lucide="search"></i><input id="pal-q" placeholder="대화, 프로젝트, 오답, 개념 검색" autocomplete="off" /><kbd>esc</kbd></label>
        <div class="palette-results" id="pal-results"></div>
        <div class="palette-foot"><span>↑↓ 이동</span><span>↵ 열기</span><span>esc 닫기</span></div>
      </div>`;
    document.body.append(bd);
    bd.addEventListener("mousedown", (e) => { if (e.target === bd) closeOverlays(); });
    const input = $("#pal-q", bd);
    let items = [];
    let active = 0;

    const draw = () => {
      const q = input.value.trim().toLowerCase();
      const has = (s) => s.toLowerCase().includes(q);
      const groups = [];
      if (!q) {
        groups.push(["바로가기", [
          { icon: "square-pen", t: "새 학습", go: "/" },
          { icon: "circle-x", t: "오답노트", go: "/notes", sub: `${Store.openNotes().length}문제` },
          { icon: "library", t: "라이브러리", go: "/library" },
          { icon: "layers", t: "암기 카드", go: "/library/cards" },
          { icon: "folder-plus", t: "새 프로젝트 만들기", run: projectWizard },
        ]]);
        groups.push(["최근 대화", [...Store.state.sessions].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, 5)
          .map((s) => ({ icon: "message-circle", t: s.title, go: `/chat/${s.id}`, sub: relTime(s.updatedAt) }))]);
      } else {
        groups.push(["프로젝트", Store.state.projects.filter((p) => has(p.name))
          .map((p) => ({ icon: "folder", t: p.name, go: `/project/${p.id}`, sub: ddayLabel(daysLeft(p.examDate)) }))]);
        groups.push(["대화", Store.state.sessions.filter((s) => has(s.title) || s.messages.some((m) => has(m.text)))
          .map((s) => ({ icon: "message-circle", t: s.title, go: `/chat/${s.id}`, sub: relTime(s.updatedAt) }))]);
        groups.push(["오답", Store.state.wrongNotes.filter((w) => has(Store.problem(w.problemId).stem) || has(concept(Store.problem(w.problemId).conceptIds[0]).name))
          .map((w) => ({ icon: "circle-x", t: plainMath(Store.problem(w.problemId).stem), go: "/notes", sub: w.resolvedAt ? "극복" : "안 품" }))]);
        groups.push(["개념", CONCEPTS.filter((c) => c.level === "concept" && has(c.name)).slice(0, 8)
          .map((c) => ({ icon: "book-open", t: c.name, go: `/library/concept/${c.id}`, sub: subjectOf(c.id)?.name ?? "" }))]);
      }
      items = groups.flatMap(([, list]) => list);
      active = Math.min(active, Math.max(0, items.length - 1));
      let i = 0;
      $("#pal-results", bd).innerHTML = items.length ? groups.filter(([, l]) => l.length).map(([title, list]) => `
        <div class="palette-group">${title}</div>
        ${list.map((it) => `<button class="palette-item ${i === active ? "active" : ""}" data-i="${i++}"><i data-lucide="${it.icon}"></i><span class="t">${esc(it.t)}</span>${it.sub ? `<small>${esc(it.sub)}</small>` : ""}</button>`).join("")}`).join("")
        : '<div class="palette-empty">검색 결과가 없어요</div>';
      icons();
    };
    const run = (i) => {
      const it = items[i];
      if (!it) return;
      closeOverlays();
      if (it.go) go(it.go); else it.run();
    };
    input.addEventListener("input", () => { active = 0; draw(); });
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        active = (active + (e.key === "ArrowDown" ? 1 : -1) + items.length) % Math.max(items.length, 1);
        draw();
        $(".palette-item.active", bd)?.scrollIntoView({ block: "nearest" });
      }
      if (e.key === "Enter") { e.preventDefault(); run(active); }
    });
    $("#pal-results", bd).addEventListener("click", (e) => { const b = e.target.closest("[data-i]"); if (b) run(Number(b.dataset.i)); });
    $("#pal-results", bd).addEventListener("mousemove", (e) => {
      const b = e.target.closest("[data-i]");
      if (b && Number(b.dataset.i) !== active) { active = Number(b.dataset.i); $$(".palette-item", bd).forEach((x) => x.classList.toggle("active", x === b)); }
    });
    draw();
    input.focus();
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.matches?.("[data-short] input")) {
      e.preventDefault();
      $("[data-short-submit]", e.target.closest("[data-short]")).click();
    }
  });

  $(".search input").addEventListener("focus", (e) => { e.target.blur(); openPalette(); });
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); }
    if (e.key === "Escape") closeOverlays();
  });

  // ================= 레이아웃 · 배경 =================
  $("#toggle").addEventListener("click", () => {
    const app = $("#app");
    if (matchMedia("(max-width: 760px)").matches) app.classList.toggle("mobile-open");
    else app.classList.toggle("collapsed");
  });
  contentEl.addEventListener("scroll", () => $(".topbar").classList.toggle("scrolled", contentEl.scrollTop > 4), { passive: true });

  $("#actions").innerHTML = [
    ["pencil-line", "문제 풀기", "미적분 3점짜리 3문제 내줘"],
    ["circle-x", "오답노트", ""],
    ["file-text", "시험지 만들기", ""],
    ["book-open", "개념 정리", ""],
  ].map(([icon, label, p]) => `<button class="action" data-prompt="${p}"><span class="tile"><i data-lucide="${icon}"></i></span>${label}</button>`).join("");

  // 첫 화면 표시 — 서버 모드면 내 데이터를 받아 온 뒤에 그린다
  Store.ready.then(() => {
  loadConcepts();
  render();
  setUnread(Store.state.user?.unreadNotifications ?? 0);

  // 접속 상태: 화면이 보이는 동안 1분마다, 다시 보일 때 바로 알린다
  const pingNow = () => { if (document.visibilityState === "visible") Store.ping(route().parts[0] || "home"); };
  pingNow();
  setInterval(pingNow, 60_000);
  document.addEventListener("visibilitychange", pingNow);

  // 홈 요소: 스크롤하면 아래에서 위로 떠오름
  [[".hero h1", ".hero p", ".hero .composer"], [".action"], [".today > .panel"], [".activity"], [".section-head"], ["#cards-recent .card"], [".subject"]]
    .forEach((group) => group.flatMap((s) => $$(s)).forEach((el, i) => { el.classList.add("reveal"); el.style.setProperty("--d", `${i * 70}ms`); }));
  revealer = new IntersectionObserver((entries) => {
    for (const e of entries) if (e.isIntersecting) { e.target.classList.add("in"); revealer.unobserve(e.target); }
  }, { root: contentEl, threshold: 0.12, rootMargin: "0px 0px -6% 0px" });
  $$(".reveal").forEach((el) => revealer.observe(el));
  }).catch((e) => toast(`데이터를 불러오지 못했어요: ${e.message}`));


  // 무지개 도트: 홈에서는 입력창 중심, 다른 화면에서는 화면 위쪽 가운데
  const composerEl = $("#composer");
  const homeText = [".hero h1", ".hero p", ".action"].flatMap((s) => $$(s));
  dotField($("#dots"), {
    gap: 18, baseR: 1, peakR: 2.4, baseAlpha: 0.1, peakAlpha: 0.55, light: 60,
    wavelength: 90, speed: 1.1, hueSpeed: 25, reach: 0.62, introSec: 1.3,
    focus: (W, H) => {
      if (home.hidden) return [W * 0.6, H * 0.12];
      const r = composerEl.getBoundingClientRect();
      return [r.left + r.width / 2, r.top + r.height / 2];
    },
    clear: () => (home.hidden ? [] : homeText.map((el) => el.getBoundingClientRect())),
    scrollY: () => contentEl.scrollTop,
  });
})();

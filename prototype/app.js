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
  };
  // 서술형 풀이 칸 상태 — 문제 id → { open, tab, text, image, drawn, eraser, review, busy } (다시 그려도 유지)
  const workState = {};
  // 검색 결과처럼 짧은 글로 보여 줄 때: LaTeX 명령을 걷어 낸 평문
  const plainMath = (s = "") => s.replace(/\$+([^$]*)\$+/g, (_, m) => m
    .replace(/\\(displaystyle|mathrm|dfrac|frac|left|right|text)\b/g, " ").replace(/\\[,;!]/g, " ")
    .replace(/\\int/g, "∫").replace(/\\log/g, "log").replace(/\\times/g, "×").replace(/\\cap/g, "∩").replace(/\\mid/g, "|")
    .replace(/[{}\\]/g, "").replace(/\s+/g, " ").trim());
  const DAY = 864e5;

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

  function render() {
    if (!Store.state) return; // 서버 데이터를 받기 전
    closeOverlays();
    const { parts, params } = route();
    const [page, a, b] = parts;
    home.hidden = !!page;
    view.hidden = !page;
    view.onclick = null;
    view.onchange = null;
    if (!page) renderHome(params);
    else if (page === "chat") renderChat(a);
    else if (page === "project") renderProject(a);
    else if (page === "notes") renderNotes();
    else if (page === "library") renderLibrary(a ?? "concepts", b);
    else if (page === "settings") renderSettings(params);
    else if (page === "admin") renderAdmin();
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
    $("#profile-sub").textContent = `오늘 ${Store.todayCount()} / ${st.user.dailyGoal}문제 · ${Store.streak()}일 연속`;
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
      Store.state.user.isAdmin && { icon: "inbox", label: "피드백 관리 (운영)", run: () => go("/admin") },
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

    // 이번 주 약점 배너 — 3번 이상 푼 개념 중 정답률이 가장 낮은 것
    const weak = Store.conceptStats().find((s) => s.attempts >= 3);
    if (weak) {
      const c = concept(weak.conceptId);
      $("#banner-eyebrow").textContent = `이번 주 약점 · ${subjectOf(c.id)?.name ?? ""}`;
      $("#banner-title").textContent = c.name;
      $("#banner-desc").textContent = `최근 ${weak.attempts}문제 중 ${weak.attempts - weak.correct}문제 오답 · 정답률 ${pct(weak.accuracy)}`;
      $("#banner-concept").dataset.href = `#/library/concept/${c.id}`;
    }

    const recent = [...Store.state.sessions].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, 4);
    $("#cards-recent").innerHTML = recent.map((s) => {
      const p = s.projectId && Store.project(s.projectId);
      const ids = s.messages.flatMap((m) => m.problemIds ?? []);
      const tried = ids.map((pid) => Store.lastAttempt(s.id, pid)).filter(Boolean);
      const ok = tried.filter((a) => a.correct).length;
      return card({
        href: `#/chat/${s.id}`, c: p ? COLOR[projectDomain(p)] : "var(--ink-3)", kind: p ? p.name : "대화", title: s.title,
        meta: `${ids.length ? `${ok} / ${ids.length} 정답 · ` : ""}${relTime(s.updatedAt)}`, pct: ids.length ? (ok / ids.length) * 100 : 0,
      });
    }).join("") || '<p class="empty">아직 학습 기록이 없어요</p>';

    const unknownCards = Store.state.cards.filter((c) => c.known !== true).length;
    const open = Store.openNotes();
    const recs = [];
    if (weak) recs.push({ href: `#/library/concept/${weak.conceptId}`, c: COLOR[concept(weak.conceptId).domain], kind: "약점 보완", title: `${concept(weak.conceptId).name} 다시 보기`, meta: `정답률 ${pct(weak.accuracy)} · 개념부터 정리해요` });
    if (open.length) recs.push({ href: "#/notes", c: "var(--warn)", kind: "복습 타이밍", title: `안 푼 오답 ${open.length}문제 다시 풀기`, meta: "잊기 전에 다시 풀면 오래 기억해요" });
    if (unknownCards) recs.push({ href: "#/library/cards", c: "var(--accent)", kind: "암기", title: `암기 카드 ${unknownCards}장`, meta: `예상 ${Math.max(1, Math.round(unknownCards / 2))}분` });
    $("#cards-recommend").innerHTML = recs.map(card).join("") || '<p class="empty">추천할 학습이 없어요. 잘하고 있어요!</p>';

    $("#subjects").innerHTML = myDomains().map((d) => {
      const acc = Store.accuracy({ domain: d });
      const w = Store.conceptStats({ domain: d })[0];
      return `
        <a class="card subject" href="#/notes?domain=${d}" style="--c:${COLOR[d]}; text-decoration:none; color:inherit">
          <span class="kind"><span class="sw"></span>${DOMAIN_NAME[d]}</span>
          <div class="pct">${acc == null ? "–" : Math.round(acc * 100)}<small>% 정답률</small></div>
          <div class="bar"><i style="width:${acc == null ? 0 : acc * 100}%"></i></div>
          <div class="weak">${w ? `약점 <b>${esc(concept(w.conceptId).name)}</b>` : "아직 풀이 기록이 없어요"}</div>
        </a>`;
    }).join("");
  }

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

  prompt.addEventListener("input", () => (send.disabled = !prompt.value.trim()));
  $("#composer").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = prompt.value.trim();
    if (!text) return;
    prompt.value = "";
    send.disabled = true;
    ask({ projectId: homeProjectId, text });
  });

  // 아이콘 타일: 메뉴로 이동하거나 예시 요청을 입력창에 채운다
  const TILE_ROUTES = { 오답노트: "/notes", "개념 정리": "/library", "암기 카드": "/library/cards" };
  $("#actions").addEventListener("click", (e) => {
    const tile = e.target.closest(".action");
    if (!tile) return;
    const label = tile.textContent.trim();
    if (TILE_ROUTES[label]) return go(TILE_ROUTES[label]);
    if (!tile.dataset.prompt) return openPalette();
    prompt.value = tile.dataset.prompt;
    send.disabled = false;
    prompt.focus();
  });
  $("#banner-review").addEventListener("click", () => go("/notes"));
  $("#banner-concept").addEventListener("click", (e) => { location.hash = e.currentTarget.dataset.href || "#/library"; });

  // ================= 대화 =================
  // 질문을 보내고 답을 기다린다. 새 대화면 바로 그 대화로 이동하고, 서버가 진짜 id 를 주면 주소를 바꾼다
  function ask({ sessionId = null, projectId = null, text }) {
    const { id, done } = Store.sendMessage({ sessionId, projectId, text });
    if (!sessionId) go(`/chat/${id}`);
    const refresh = (realId = id) => {
      if (navKey() !== `chat:${id}`) return;
      if (realId !== id) location.replace(`#/chat/${realId}`);
      else renderChat(id);
    };
    done.then(refresh, () => refresh());
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
      w.review = await Store.reviewSolution(pid, w.tab === "type" ? { text } : { image });
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
      const r = await Store.answer({ problemId: box.dataset.problem, answer, ...ctx });
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
    const s = Store.session(id);
    if (!s) { toast("대화를 찾을 수 없어요"); return go("/"); }
    const scroll = contentEl.scrollTop;
    const p = s.projectId && Store.project(s.projectId);
    const msgs = s.messages.map((m, mi) => m.role === "user"
      ? `<div class="msg user"><div class="bubble">${esc(m.text)}</div></div>`
      : `<div class="msg ai"><span class="ai-avatar"></span><div class="ai-body"><p>${esc(m.text)}</p>
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
          ${Store.isPending(id) ? `<div class="msg ai"><span class="ai-avatar"></span><div class="ai-body"><div class="typing"><i></i><i></i><i></i></div>${Store.mode === "api" ? '<p class="mini">문제를 만들고 다른 AI가 검증하고 있어요. 1분 정도 걸릴 수 있어요</p>' : ""}</div></div>` : ""}
        </div>
        <form class="composer glass chat-composer" id="chat-form">
          <input id="chat-input" placeholder="이어서 물어보세요" autocomplete="off" />
          <button type="submit" class="send" disabled aria-label="보내기"><i data-lucide="arrow-up"></i></button>
        </form>
      </div>`;
    icons();

    const input = $("#chat-input"), btn = $("#chat-form .send");
    input.addEventListener("input", () => (btn.disabled = !input.value.trim()));
    $("#chat-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      ask({ sessionId: id, text });
      renderChat(id);
      $("#chat-input").focus();
    });
    $("#chat-more").addEventListener("click", (e) => chatMenu(e.currentTarget, id));

    const ctx = { projectId: s.projectId, sessionId: s.id };
    const redraw = () => renderChat(id, { keepScroll: true });
    view.onclick = (e) => { if (!handleProblemSet(e, redraw) && !handleProblemExtras(e)) handleAnswer(e, ctx, redraw); };

    contentEl.scrollTop = keepScroll ? scroll : contentEl.scrollHeight;
  }

  // ================= 프로젝트 =================
  function renderProject(id) {
    const p = Store.project(id);
    if (!p) { toast("프로젝트를 찾을 수 없어요"); return go("/"); }
    const d = projectDomain(p);
    const n = daysLeft(p.examDate);
    const acc = Store.accuracy({ projectId: id });
    const tries = Store.state.attempts.filter((a) => a.projectId === id).length;
    const open = Store.openNotes().filter((w) => w.projectId === id).length;
    const weak = Store.conceptStats({ projectId: id }).slice(0, 3);
    const sessions = Store.state.sessions.filter((s) => s.projectId === id).sort((a, b) => b.updatedAt - a.updatedAt);
    const units = p.unitIds.length ? p.unitIds : childrenOf(p.subjectId).map((u) => u.id);

    view.innerHTML = `
      <div class="page-head">
        <div>
          <h1><i data-lucide="folder" style="color:${COLOR[d]}"></i>${esc(p.name)}</h1>
          <p>${esc(concept(p.subjectId).name)} · ${esc(qtypeLabel(p))}${p.goal ? ` · 목표 ${esc(p.goal)}` : ""}${p.examDate ? ` · 시험일 ${p.examDate}` : ""}${p.textbook ? ` · 교재 ${esc(p.textbook)}` : ""}</p>
        </div>
        <div class="page-actions">
          <a class="btn-primary" href="#/?project=${id}" style="text-decoration:none"><i data-lucide="square-pen"></i>이 프로젝트에서 새 학습</a>
          <button class="icon-btn soft" id="project-more" aria-label="프로젝트 메뉴"><i data-lucide="ellipsis"></i></button>
        </div>
      </div>

      <div class="stats">
        <div class="stat"><b>${n == null ? "–" : ddayLabel(n)}</b><span>시험까지</span></div>
        <div class="stat"><b>${tries}</b><span>푼 문제</span></div>
        <div class="stat"><b>${pct(acc)}</b><span>정답률</span></div>
        <a class="stat" href="#/notes?project=${id}" style="text-decoration:none;color:inherit"><b style="color:${open ? "var(--warn)" : "inherit"}">${open}</b><span>남은 오답 →</span></a>
      </div>

      <section class="glass-card past-panel" style="--c:${COLOR[d]}">
        <div class="past-head">
          <h3><i data-lucide="file-stack"></i>기출 기반 문제 만들기</h3>
          ${Store.mode === "api" ? '<button class="btn-ghost glassy" id="add-material"><i data-lucide="upload"></i>기출 올리기</button>' : ""}
        </div>
        ${Store.mode === "api" ? `
          <div id="materials" class="materials"><p class="mini">불러오는 중…</p></div>
          <div class="gen-row">
            <span>기출보다</span>
            <div class="seg" id="gen-level">${[["easier", "쉽게"], ["same", "비슷하게"], ["harder", "어렵게"]].map(([k, v]) => `<button type="button" data-level="${k}" class="${k === "same" ? "on" : ""}">${v}</button>`).join("")}</div>
            <select class="select" id="gen-count" aria-label="문항 수">${[1, 2, 3, 4, 5].map((n) => `<option value="${n}" ${n === 3 ? "selected" : ""}>${n}문제</option>`).join("")}</select>
            <button class="btn-primary" id="gen-go"><i data-lucide="sparkles"></i>문제 만들기</button>
          </div>
          <p class="mini" id="gen-status">기출이 없으면 프로젝트 범위와 약점을 바탕으로 만들어요. 만든 문제는 다른 AI가 다시 풀어 검증해요</p>
          <div id="past-list"></div>`
          : '<div class="ai-slot"><i data-lucide="info"></i><div>기출 업로드와 AI 문제 생성은 로그인해서 서버 화면(localhost:8000/app)으로 열었을 때 쓸 수 있어요.</div></div>'}
      </section>

      <div class="cols">
        <section class="panel">
          <h3><i data-lucide="target"></i>약점 TOP 3</h3>
          ${weak.length ? `<ul class="weak-list">${weak.map((w) => `
            <li style="--c:${COLOR[d]}">
              <div class="row"><a href="#/library/concept/${w.conceptId}" style="color:inherit;text-decoration:none">${esc(concept(w.conceptId).name)}</a><span>${pct(w.accuracy)} · ${w.attempts}문제</span></div>
              <div class="bar"><i style="width:${w.accuracy * 100}%"></i></div>
            </li>`).join("")}</ul>` : '<p class="mini">문제를 풀면 약점이 여기에 나타나요</p>'}
        </section>
        <section class="panel">
          <h3><i data-lucide="list-tree"></i>학습 범위</h3>
          <div class="unit-list">${units.map((u) => `<span class="pill" style="--c:${COLOR[d]}">${esc(concept(u).name)}</span>`).join("")}</div>
        </section>
      </div>

      <section class="panel" style="margin-top:12px">
        <h3><i data-lucide="messages-square"></i>대화 ${sessions.length}개</h3>
        ${sessions.length ? `<div class="list">${sessions.map((s) => `
          <a href="#/chat/${s.id}"><i data-lucide="message-circle"></i>${esc(s.title)}<span>${relTime(s.updatedAt)}</span></a>`).join("")}</div>`
          : '<p class="mini">아직 대화가 없어요. "이 프로젝트에서 새 학습"으로 시작해 보세요</p>'}
      </section>`;
    $("#project-more").addEventListener("click", (e) => projectMenu(e.currentTarget, id));
    if (Store.mode === "api") bindPastPanel(id);
  }

  // 기출 자료 목록 (분석이 끝날 때까지 몇 초마다 새로고침) + 기출 기반 생성
  const MATERIAL_STATUS = { uploaded: ["분석 대기", "clock"], extracting: ["AI가 읽는 중", "loader"], ready: ["완료", "circle-check"], failed: ["실패", "circle-alert"] };
  function bindPastPanel(id) {
    const here = () => navKey() === `project:${id}`;
    async function loadMaterials() {
      if (!here()) return;
      let list;
      try { list = await Store.listMaterials(id); } catch (e) { $("#materials").innerHTML = `<p class="mini">${esc(e.message)}</p>`; return; }
      if (!here()) return;
      $("#materials").innerHTML = list.length ? list.map((m) => {
        const [label, icon] = MATERIAL_STATUS[m.status];
        return `
          <div class="material ${m.status}">
            <i data-lucide="${m.content_type === "application/pdf" ? "file-text" : "image"}"></i>
            <div class="material-name"><b>${esc(m.filename)}</b><small>${m.kind === "textbook" ? "교재 페이지" : "기출·시험지"} · ${fmtSize(m.size_bytes)} · ${relTime(Date.parse(m.created_at))}</small></div>
            <span class="status-pill ${m.status}"><i data-lucide="${icon}"></i>${label}${m.status === "ready" ? ` · ${m.problem_count}문제` : ""}</span>
            <button class="icon-btn" data-del-material="${m.id}" aria-label="삭제" title="삭제"><i data-lucide="trash-2"></i></button>
            ${m.error ? `<p class="material-error">${esc(m.error)}</p>` : ""}
          </div>`;
      }).join("") : '<p class="mini">아직 올린 기출이 없어요. 기출을 올리면 그 시험의 결을 따라 문제를 만들어요</p>';
      icons();
      if (list.some((m) => m.status === "uploaded" || m.status === "extracting")) setTimeout(loadMaterials, 4000);
      else loadPast();
    }
    async function loadPast() {
      const past = await Store.pastProblems(id).catch(() => []);
      if (!here() || !past.length) { if (here()) $("#past-list").innerHTML = ""; return; }
      $("#past-list").innerHTML = `
        <details class="past-preview"><summary><i data-lucide="chevron-right"></i>AI가 읽은 기출 문제 ${past.length}개</summary>
          ${past.map((q) => `
            <div class="past-item">
              <div class="past-meta">${q.number ? `<b>${q.number}번</b>` : ""}<span>${esc(conceptLabel(q.concept_ids ? { ...q, conceptIds: q.concept_ids } : q))}</span>
                ${q.has_answer ? '<span class="pill" style="--c:var(--ok)">정답 있음</span>' : '<span class="pill">정답 없음</span>'}
                ${q.needs_figure ? '<span class="pill" style="--c:var(--warn)">그림 필요</span>' : ""}</div>
              <p class="stem" data-math>${esc(q.stem)}</p>
              ${q.choices ? `<ol class="past-choices">${q.choices.map((c) => `<li data-math>${esc(c)}</li>`).join("")}</ol>` : ""}
            </div>`).join("")}
        </details>`;
      icons();
    }
    $("#add-material").addEventListener("click", () => uploadSheet(id, loadMaterials));
    $("#gen-level").addEventListener("click", (e) => {
      const b = e.target.closest("[data-level]");
      if (b) $$("#gen-level [data-level]").forEach((x) => x.classList.toggle("on", x === b));
    });
    $("#materials").addEventListener("click", (e) => {
      const del = e.target.closest("[data-del-material]");
      if (del) confirmModal({
        title: "올린 기출을 삭제할까요?", text: "원본 파일과 AI가 읽어 둔 기출 문제가 삭제돼요. 그것으로 만든 문제와 풀이 기록은 남아요.",
        run: async () => { try { await Store.deleteMaterial(del.dataset.delMaterial); toast("삭제했어요"); } catch (err) { toast(err.message); } loadMaterials(); },
      });
    });
    $("#gen-go").addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      const level = $("#gen-level .on").dataset.level;
      const count = Number($("#gen-count").value);
      btn.disabled = true;
      btn.innerHTML = '<i data-lucide="loader" class="spin"></i>만드는 중…';
      $("#gen-status").textContent = `문제 ${count}개를 만들고 다른 AI가 검증하고 있어요. 1~2분 정도 걸려요`;
      icons();
      try {
        const sid = await Store.generateFromPast(id, { level, count });
        toast("새 문제를 만들었어요");
        go(`/chat/${sid}`);
      } catch (err) {
        toast(err.message);
        if (here()) { btn.disabled = false; btn.innerHTML = '<i data-lucide="sparkles"></i>문제 만들기'; $("#gen-status").textContent = err.message; icons(); }
      }
    });
    loadMaterials();
  }

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

  // ---------- 내 맞춤 개념 정리 (검증 에이전트를 통과한 것만) ----------
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
        검증 에이전트가 내용을 확인한 뒤 보여줘요 (1~2분).
        <div style="margin-top:10px"><button class="btn-primary" data-make-note><i data-lucide="wand-sparkles"></i>만들기</button></div></div></div>`);
    slot.onclick = async (e) => {
      if (!e.target.closest("[data-make-note]") || noteBusy.has(id)) return;
      noteBusy.add(id);
      draw(NOTE_BUSY);
      try {
        const r = await Store.createNote(id);
        noteCache[id] = r.note;
        toast(r.added_cards.length ? `암기 카드 ${r.added_cards.length}장을 덱에 넣었어요` : "개념 정리를 새로 만들었어요");
      } catch (err) { toast(err.message); }
      noteBusy.delete(id);
      if (location.hash === `#/library/concept/${id}`) renderConcept(id);
    };
  }
  const NOTE_BUSY = `<div class="ai-slot"><i data-lucide="loader-circle" class="spin"></i><div><b style="color:var(--ink)">AI가 정리하고, 검증 에이전트가 확인하는 중이에요</b><br />1~2분 걸려요. 다른 화면에 다녀와도 계속 만들어요.</div></div>`;

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

  // ================= 운영: 피드백 관리 (운영자 계정만) =================
  const FB_STATUS = { open: "접수", reviewing: "확인 중", resolved: "해결" };
  let adminFilter = "open";
  async function renderAdmin() {
    if (!Store.state.user.isAdmin) return go("/");
    view.innerHTML = `
      <div class="page-head"><div><h1><i data-lucide="inbox"></i>피드백 관리</h1><p>문제 신고와 의견을 확인하고 답변해요</p></div>
        <div class="seg">${[["open", "처리할 것"], ["resolved", "해결됨"], ["all", "전체"]].map(([k, t]) => `<button data-afilter="${k}" class="${adminFilter === k ? "on" : ""}">${t}</button>`).join("")}</div></div>
      <details class="panel announce">
        <summary><i data-lucide="megaphone"></i>모든 사용자에게 공지 보내기</summary>
        <div class="field"><label for="an-title">제목</label><input id="an-title" maxlength="120" placeholder="예: 11월 5일 밤 10시 점검 안내" /></div>
        <div class="field"><label for="an-body">내용 <small>· 선택</small></label><textarea id="an-body" rows="3" maxlength="2000"></textarea></div>
        <div class="field"><label for="an-link">누르면 갈 화면 <small>· 선택 (예: #/library)</small></label><input id="an-link" maxlength="200" /></div>
        <div class="fb-actions"><button class="btn-primary" data-announce>공지 보내기</button></div>
      </details>
      <div id="admin-list"><p class="mini">불러오는 중…</p></div>`;
    icons();
    view.onclick = async (e) => {
      const f = e.target.closest("[data-afilter]");
      if (f) { adminFilter = f.dataset.afilter; return renderAdmin(); }
      if (e.target.closest("[data-announce]")) {
        const title = $("#an-title").value.trim();
        if (title.length < 2) return invalid($("#an-title"), "제목을 적어 주세요");
        try {
          const r = await Store.adminAnnounce({ title, body: $("#an-body").value.trim() || null, link: $("#an-link").value.trim() || null });
          toast(`${r.sent}명에게 공지를 보냈어요`);
          ["#an-title", "#an-body", "#an-link"].forEach((s) => ($(s).value = ""));
          refreshNotifications();
        } catch (err) { toast(err.message); }
        return;
      }
      const card = e.target.closest("[data-fb]");
      if (!card) return;
      const id = card.dataset.fb;
      try {
        const st = e.target.closest("[data-fstatus]");
        if (st) { await Store.adminUpdateFeedback(id, { status: st.dataset.fstatus }); toast(`'${FB_STATUS[st.dataset.fstatus]}'(으)로 바꿨어요`); return renderAdmin(); }
        if (e.target.closest("[data-freply]")) {
          const reply = $("textarea", card).value.trim();
          if (!reply) return toast("답변을 적어 주세요");
          await Store.adminUpdateFeedback(id, { reply, status: "resolved" });
          toast("답변을 저장하고 해결로 바꿨어요");
          return renderAdmin();
        }
        const restore = e.target.closest("[data-frestore]");
        if (restore) { await Store.adminRestoreProblem(restore.dataset.frestore); toast("문제를 다시 보이게 했어요"); return renderAdmin(); }
      } catch (err) { toast(err.message); }
    };
    let items;
    try { items = await Store.adminFeedback(adminFilter); } catch (err) { $("#admin-list").innerHTML = `<p class="mini">${esc(err.message)}</p>`; return; }
    const list = $("#admin-list");
    if (!list) return;
    list.innerHTML = items.length ? items.map((f) => `
      <section class="panel fb-item" data-fb="${f.id}">
        <div class="fb-meta"><span class="tag on">${FEEDBACK_KINDS[f.kind]}</span><span class="fb-status ${f.status}">${FB_STATUS[f.status]}</span>
          <span>${esc(f.user_email)}</span><span>${new Date(f.created_at).toLocaleString("ko-KR")}</span>
          ${f.page ? `<a href="${esc(f.page)}">${esc(f.page)}</a>` : ""}</div>
        <p class="fb-msg">${esc(f.message)}</p>
        ${f.problem_id ? `<div class="fb-problem"><small>${esc(f.problem_id)}${f.problem_hidden ? ' · <b class="bad">신고로 숨겨짐</b>' : ""}</small>
          <p data-math>${esc(f.problem_stem ?? "")}</p>
          ${f.problem_hidden ? `<button class="btn-ghost" data-frestore="${esc(f.problem_id)}"><i data-lucide="undo-2"></i>문제가 맞아요, 다시 보이게</button>` : ""}</div>` : ""}
        <textarea rows="2" maxlength="2000" placeholder="답변 (저장하면 '해결'로 바뀌고, 보낸 사람에게 알림으로 전달돼요)">${esc(f.reply ?? "")}</textarea>
        <div class="fb-actions">
          ${Object.entries(FB_STATUS).filter(([k]) => k !== f.status).map(([k, t]) => `<button class="btn-ghost" data-fstatus="${k}">${t}(으)로</button>`).join("")}
          <button class="btn-primary" data-freply>답변 저장</button></div>
      </section>`).join("") : '<div class="empty"><i data-lucide="inbox"></i><b>처리할 피드백이 없어요</b></div>';
    icons();
  }

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
  const QTYPE = { auto: "코스 형식대로", multiple_choice: "객관식", text: "주관식 (글자)", numeric: "수치형", essay: "서술형",
    short_answer: "단답형 (정수)", mixed: "객관식 + 단답형" };
  const FORMAT_NAME = { multiple_choice: "객관식", short_answer: "단답형", text: "주관식", numeric: "수치형", essay: "서술형" };
  // "코스 형식대로"가 실제로 무엇인지 (예: 객관식 4지선다 · 주관식)
  const courseFormats = (courseId) => {
    const c = courseMap[courseId];
    const fs = c?.formats?.length ? c.formats : ["multiple_choice"];
    return fs.map((f) => (f === "multiple_choice" ? `객관식 ${c?.choice_count ?? 5}지선다` : FORMAT_NAME[f] ?? f)).join(" · ");
  };
  const qtypeLabel = (p) => (p.questionType === "auto" || !p.questionType ? `코스 형식대로 (${courseFormats(p.subjectId)})` : QTYPE[p.questionType]);
  const UPLOAD_TYPES = ["application/pdf", "image/png", "image/jpeg", "image/webp"];
  const fmtSize = (n) => (n > 1048576 ? `${(n / 1048576).toFixed(1)}MB` : `${Math.max(1, Math.round(n / 1024))}KB`);
  const isoAfter = (days) => new Date(Date.now() + days * DAY - new Date().getTimezoneOffset() * 6e4).toISOString().slice(0, 10);

  // 파일 고르기 영역 (마법사·업로드 창 공용). onChange(files) 로 바뀐 목록을 알린다
  function dropzoneHTML() {
    return `
      <div class="chips mat-kind">
        <label><input type="radio" name="mat-kind" value="past_exam" checked /><span>기출·시험지</span></label>
        <label><input type="radio" name="mat-kind" value="textbook" /><span>교재 페이지</span></label>
      </div>
      <label class="dropzone" data-drop>
        <input type="file" accept=".pdf,image/png,image/jpeg,image/webp" multiple hidden />
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
    let ok = 0;
    for (const f of files) {
      try { await Store.uploadMaterial(projectId, f, true, kind); ok++; } catch (e) { toast(`${f.name}: ${e.message}`); }
    }
    return ok;
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
      $("[data-auto-formats]", body).textContent = w.subjectId ? `· 코스 형식대로 = ${courseFormats(w.subjectId)}` : "";
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
      btn.innerHTML = '<i data-lucide="loader-circle" class="spin"></i>AI가 단원·개념을 정리하는 중… (30초~1분)';
      icons();
      try {
        const c = await Store.createCourse({ title, scope_text: scope, exam: $("#nc-exam").value.trim(),
          level: $("input[name=nc-level]:checked", body)?.value ?? "", textbook: w.textbook.trim(), textbook_isbn: w.isbn });
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
        uploadAll(projectId, files, $("input[name=mat-kind]:checked", f)?.value).then((n) => { closeOverlays(); if (n) toast(`${n}개를 올렸어요. AI가 문제를 읽는 중이에요`); onDone(); });
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
    ["chart-no-axes-column", "약점 분석", "이번 주 내 약점 분석해줘"],
    ["book-open", "개념 정리", ""],
    ["layers", "암기 카드", ""],
    ["scroll-text", "기출 스타일", "6월 모평 스타일로 화학 2문제"],
    ["timer", "모의고사", "수학 모의고사 3문항 시작"],
    ["ellipsis", "더보기", ""],
  ].map(([icon, label, p]) => `<button class="action" data-prompt="${p}"><span class="tile"><i data-lucide="${icon}"></i></span>${label}</button>`).join("");

  // 첫 화면 표시 — 서버 모드면 내 데이터를 받아 온 뒤에 그린다
  Store.ready.then(() => {
  loadConcepts();
  render();
  setUnread(Store.state.user?.unreadNotifications ?? 0);

  // 홈 요소: 스크롤하면 아래에서 위로 떠오름
  [[".hero h1", ".hero p", ".hero .composer"], [".action"], [".banner"], [".tabs"], ["#cards-recent .card"], ["#cards-recommend .card"], [".section-head"], [".subject"]]
    .forEach((group) => group.flatMap((s) => $$(s)).forEach((el, i) => { el.classList.add("reveal"); el.style.setProperty("--d", `${i * 70}ms`); }));
  const revealer = new IntersectionObserver((entries) => {
    for (const e of entries) if (e.isIntersecting) { e.target.classList.add("in"); revealer.unobserve(e.target); }
  }, { root: contentEl, threshold: 0.12, rootMargin: "0px 0px -6% 0px" });
  $$(".reveal").forEach((el) => revealer.observe(el));
  }).catch((e) => toast(`데이터를 불러오지 못했어요: ${e.message}`));

  $$("[data-tab]").forEach((t) => t.addEventListener("click", () => {
    $$("[data-tab]").forEach((x) => x.classList.toggle("active", x === t));
    $("#cards-recent").classList.toggle("hidden", t.dataset.tab !== "recent");
    $("#cards-recommend").classList.toggle("hidden", t.dataset.tab !== "recommend");
  }));

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
  dotField($("#banner-dots"), {
    gap: 12, baseR: 0.8, peakR: 2, baseAlpha: 0.12, peakAlpha: 0.75, light: 58,
    wavelength: 60, speed: 1.4, hueSpeed: 40, introSec: 1.8, edges: true,
    focus: (W, H) => [W / 2, H / 2],
  });
})();

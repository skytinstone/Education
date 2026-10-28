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

  const DOMAINS = ["math", "physics", "chemistry", "biology", "earth_science"];
  const COLOR = { math: "var(--math)", physics: "var(--physics)", chemistry: "var(--chemistry)", biology: "var(--biology)", earth_science: "var(--earth)" };
  const DOMAIN_NAME = { math: "수학", physics: "물리", chemistry: "화학", biology: "생명과학", earth_science: "지구과학" };

  const conceptMap = Object.fromEntries(CONCEPTS.map((c) => [c.id, c]));
  const concept = (id) => conceptMap[id];
  const childrenOf = (id) => CONCEPTS.filter((c) => c.parent_id === id);
  const pathOf = (id) => { const out = []; for (let c = concept(id); c; c = concept(c.parent_id)) out.unshift(c); return out; };
  const subjectOf = (id) => pathOf(id)[0];
  const SUBJECTS = CONCEPTS.filter((c) => c.level === "subject").sort((a, b) => DOMAINS.indexOf(a.domain) - DOMAINS.indexOf(b.domain));
  const projectDomain = (p) => concept(p?.subjectId)?.domain;

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
    else if (page === "settings") renderSettings();
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
      $("#banner-eyebrow").textContent = `이번 주 약점 · ${subjectOf(c.id).name}`;
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

    $("#subjects").innerHTML = DOMAINS.map((d) => {
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

  const isShort = (p) => p.problemType === "short_answer" || !p.choices;
  const conceptLabel = (p) => {
    const c = concept(p.conceptIds?.[0]);
    return c ? `${subjectOf(c.id).name} · ${c.name}` : DOMAIN_NAME[p.domain] ?? "";
  };

  function problemHTML(pid, { attempt = null, index = null } = {}) {
    const p = Store.problem(pid);
    if (!p) return "";
    const saved = Store.state.savedProblemIds.includes(pid);
    let answerArea;
    if (isShort(p)) {
      answerArea = attempt
        ? `<div class="short-result ${attempt.correct ? "ok" : "bad"}"><span>내 답 <b>${esc(attempt.answer)}</b></span>${p.answer ? `<span>정답 <b>${esc(p.answer)}</b></span>` : ""}</div>`
        : `<div class="short-form" data-short><input name="answer" inputmode="numeric" placeholder="답을 정수로 입력하세요" autocomplete="off" maxlength="10" aria-label="답" /><button class="btn-primary" type="button" data-short-submit>제출</button></div>`;
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
            <span class="kind"><span class="sw"></span>${esc(conceptLabel(p))}${isShort(p) ? " · 단답형" : ""}</span>
            <span class="stars" title="난이도 ${p.difficulty}">${"★".repeat(p.difficulty)}${"☆".repeat(5 - p.difficulty)}</span>
            <button class="work-btn ${work ? "on" : ""}" data-work="${pid}" title="풀이를 쓰면 AI가 어디서 틀렸는지 알려줘요"><i data-lucide="pencil-line"></i>서술형 풀이</button>
            <button class="icon-btn save ${saved ? "on" : ""}" data-save="${pid}" title="${saved ? "저장 취소" : "저장"}"><i data-lucide="bookmark"></i></button>
          </div>
          <p class="stem" data-math>${index ? `<b>${index}.</b> ` : ""}${esc(p.stem)}</p>
          ${answerArea}
          ${result}
        </div>
        ${work ? workHTML(pid) : ""}
      </article>`;
  }

  // ---------- 서술형 풀이: 타이핑(수식 미리보기) 또는 손글씨 → AI 가 단계별로 확인 ----------
  const workPreview = (text) => esc(text || "").trim() || '<span class="mini">수식은 $x^2+1$ 처럼 $ 로 감싸면 여기에 보기 좋게 보여요</span>';
  function workHTML(pid) {
    const w = workState[pid];
    const attempted = Store.state.attempts.some((a) => a.problemId === pid);
    return `
      <div class="work" data-work-panel="${pid}">
        <div class="work-head"><b><i data-lucide="pencil-line"></i>서술형 풀이</b>
          <div class="seg">${[["type", "타이핑"], ["draw", "손글씨"]].map(([k, t]) => `<button type="button" data-work-tab="${k}" class="${w.tab === k ? "on" : ""}">${t}</button>`).join("")}</div>
          <button type="button" class="icon-btn" data-work-close aria-label="풀이 칸 닫기"><i data-lucide="x"></i></button></div>
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
        <div data-work-review>${w.review ? reviewHTML(w.review, w.tab) : ""}</div>
      </div>`;
  }
  const VERDICT = {
    correct: ["circle-check", "풀이가 맞아요", "ok"], partial: ["circle-alert", "거의 맞았어요. 중간에 고칠 곳이 있어요", "warn"],
    wrong: ["circle-x", "접근 방법을 다시 생각해 봐요", "bad"], unreadable: ["scan-eye", "풀이를 읽지 못했어요. 조금 더 크고 또렷하게 써 주세요", "warn"],
  };
  function reviewHTML(r, tab) {
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
      </div>`;
  }
  // 손글씨 캔버스: 흰 바탕 PNG 로 저장 (지우개는 흰색으로 덧칠)
  function mountWorkCanvases() {
    $$("canvas[data-work-canvas]:not([data-ready])").forEach((cv) => {
      const w = workState[cv.closest("[data-work-panel]").dataset.workPanel];
      const ctx = cv.getContext("2d");
      const width = cv.clientWidth;
      if (!width) return; // 숨겨진 탭이면 보일 때 다시
      const dpr = Math.min(devicePixelRatio || 1, 2);
      cv.width = width * dpr;
      cv.height = 320 * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = "#fff";
      ctx.fillRect(0, 0, width, 320);
      if (w.image) { const img = new Image(); img.onload = () => ctx.drawImage(img, 0, 0, width, 320); img.src = w.image; }
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
      const end = () => { if (!drawing) return; drawing = false; w.image = cv.toDataURL("image/png"); w.drawn = true; };
      cv.addEventListener("pointerup", end);
      cv.addEventListener("pointercancel", end);
    });
  }
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
    if (e.target.closest("[data-work-close]")) {
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
      if (box) { box.innerHTML = reviewHTML(w.review, w.tab); icons(); }
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
      if (!/^-?\d[\d,]*$/.test(answer)) { toast("답을 정수로 입력해 주세요"); return true; }
    } else return false;
    if (box.classList.contains("busy")) return true;
    box.classList.add("busy");
    try {
      const r = await Store.answer({ problemId: box.dataset.problem, answer, ...ctx });
      redraw(box, { answer, correct: r.correct });
      if (r.resolved) toast("오답을 극복했어요");
    } catch (err) {
      toast(err.message);
      box.classList.remove("busy");
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
          <p>${esc(concept(p.subjectId).name)} · ${QTYPE[p.questionType ?? "multiple_choice"]}${p.goal ? ` · 목표 ${esc(p.goal)}` : ""}${p.examDate ? ` · 시험일 ${p.examDate}` : ""}</p>
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
            <div class="material-name"><b>${esc(m.filename)}</b><small>${fmtSize(m.size_bytes)} · ${relTime(Date.parse(m.created_at))}</small></div>
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
          ${DOMAINS.map((d) => `<button data-domain="${d}" style="--c:${COLOR[d]}"><span class="sw"></span>${DOMAIN_NAME[d]}</button>`).join("")}
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
            ${isShort(p) ? `<div class="note-short"><span class="pill">단답형</span>내 답 <b>${esc(w.answer || "–")}</b></div>` : `
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
            <summary><i data-lucide="chevron-right"></i>${esc(s.name)}<span>${count}개 개념</span></summary>
            ${units}
          </details>` : "";
      }).join("");
      return subjects ? `<section class="tree-domain" style="--c:${COLOR[d]}"><h2><span class="sw"></span>${DOMAIN_NAME[d]}</h2>${subjects}</section>` : "";
    }).join("");
    $("#lib-body").innerHTML = `<div class="tree">${html || `<div class="empty"><i data-lucide="search-x"></i><b>찾는 개념이 없어요</b>다른 단어로 검색해 보세요</div>`}</div>`;
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
        <div class="list">${cards.map((k) => `<a href="#/library/cards"><i data-lucide="${k.known ? "check" : "circle-dashed"}"></i>${esc(k.front)}<span>${k.known ? "외움" : "아직"}</span></a>`).join("")}</div></section>` : ""}
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
            <div class="flash-face"><small>${esc(subjectOf(c.id).name)} · ${esc(c.name)}</small><p>${esc(card.front)}</p><small>눌러서 정답 보기</small></div>
            <div class="flash-face flash-back"><small>정답</small><p>${esc(card.back)}</p></div>
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

  // 고등학생이 고르는 계열 — 대학 학과는 직접 적는다
  const MAJOR_PRESETS = ["인문계열", "자연계열", "예체능계열", "특성화고", "마이스터고"];

  // 입력하면 아래에 후보 목록을 띄우는 칸 (학교 검색). fetch(q) → [{ label, sub, value }]
  function bindSuggest(input, list, fetch) {
    let items = [], active = -1, timer = 0, seq = 0;
    const close = () => { list.hidden = true; input.setAttribute("aria-expanded", "false"); active = -1; };
    const draw = () => {
      list.innerHTML = items.map((x, i) => `<li role="option" data-i="${i}" class="${i === active ? "on" : ""}" aria-selected="${i === active}">
        <b>${esc(x.label)}</b><small>${esc(x.sub)}</small></li>`).join("");
      list.hidden = !items.length;
      input.setAttribute("aria-expanded", String(!!items.length));
    };
    const pick = (i) => { input.value = items[i].value; close(); input.dispatchEvent(new Event("change", { bubbles: true })); };
    input.addEventListener("input", () => {
      clearTimeout(timer);
      const q = input.value.trim();
      if (q.length < 2) { items = []; return close(); }
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

  function renderSettings() {
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
    formModal({
      title: p ? "프로젝트 수정" : "새 프로젝트", submit: p ? "저장" : "만들기",
      body: `
        <div class="field"><label for="f-pname">이름</label><input id="f-pname" placeholder="예: 2027 수능 미적분" value="${esc(p?.name ?? "")}" maxlength="30" /></div>
        <div class="field"><label for="f-subject">과목</label>
          <select id="f-subject"><option value="" disabled ${p ? "" : "selected"}>과목을 고르세요</option>${subjectOptions}</select></div>
        <div class="field" id="f-units-wrap" hidden><label>학습 범위 <small>· 고르지 않으면 과목 전체</small></label><div class="chips" id="f-units"></div></div>
        <div class="field"><label for="f-qtype">문제 형태</label>
          <select id="f-qtype">${Object.entries(QTYPE).map(([k, v]) => `<option value="${k}" ${(p?.questionType ?? "multiple_choice") === k ? "selected" : ""}>${v}</option>`).join("")}</select></div>
        <div class="two">
          <div class="field"><label for="f-goal">목표 <small>· 선택</small></label><input id="f-goal" placeholder="예: 1등급" value="${esc(p?.goal ?? "")}" maxlength="20" /></div>
          <div class="field"><label for="f-date">시험일 <small>· 선택</small></label><input id="f-date" type="date" value="${p?.examDate ?? ""}" /></div>
        </div>`,
      onMount(f) {
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
  const QTYPE = { multiple_choice: "객관식 (5지선다)", short_answer: "주관식 (단답형)", mixed: "객관식 + 주관식" };
  const UPLOAD_TYPES = ["application/pdf", "image/png", "image/jpeg", "image/webp"];
  const fmtSize = (n) => (n > 1048576 ? `${(n / 1048576).toFixed(1)}MB` : `${Math.max(1, Math.round(n / 1024))}KB`);
  const isoAfter = (days) => new Date(Date.now() + days * DAY - new Date().getTimezoneOffset() * 6e4).toISOString().slice(0, 10);

  // 파일 고르기 영역 (마법사·업로드 창 공용). onChange(files) 로 바뀐 목록을 알린다
  function dropzoneHTML() {
    return `
      <label class="dropzone" data-drop>
        <input type="file" accept=".pdf,image/png,image/jpeg,image/webp" multiple hidden />
        <i data-lucide="upload-cloud"></i>
        <b>기출·시험지 파일을 끌어다 놓거나 눌러서 고르세요</b>
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

  async function uploadAll(projectId, files) {
    let ok = 0;
    for (const f of files) {
      try { await Store.uploadMaterial(projectId, f, true); ok++; } catch (e) { toast(`${f.name}: ${e.message}`); }
    }
    return ok;
  }

  // 글로 적으면 알아듣는 부분 — 과목·목표·시험일·범위
  const SUBJECT_ALIASES = [ // II 를 먼저 (수학II 가 수학I 로 잡히지 않게)
    ["math.math2", ["수학ii", "수학2", "수2"]], ["math.math1", ["수학i", "수학1", "수1"]],
    ["math.prob_stat", ["확률과통계", "확통", "확률", "통계"]], ["math.calculus", ["미적분", "미적"]], ["math.geometry", ["기하"]],
    ["physics.physics1", ["물리학", "물리", "물1"]], ["chemistry.chemistry1", ["화학", "화1"]],
    ["biology.biology1", ["생명과학", "생명", "생물", "생1", "생과"]], ["earth_science.earth1", ["지구과학", "지구", "지학", "지1"]],
  ];
  const norm = (s) => s.toLowerCase().replace(/Ⅱ/g, "ii").replace(/Ⅰ/g, "i").replace(/\s+/g, "");
  const nameWords = (s) => s.split(/[\s·,()과와의]+/).filter((x) => x.length >= 2);
  function readExam(text) {
    const t = norm(text);
    // 숫자로 끝나는 별칭은 뒤에 숫자·등급·점·문제가 붙으면 아님 ("수학 10문제", "수학 2등급" 은 수학I·II 가 아니다)
    // (띄어쓰기를 지우면 "물1 3문제" 가 "물13" 이 되므로 이 경우는 띄어쓰기를 남긴 글에서 본다)
    const spaced = text.toLowerCase().replace(/Ⅱ/g, "ii").replace(/Ⅰ/g, "i").replace(/\s+/g, " ");
    const found = (k) => (/\d$/.test(k)
      ? new RegExp(`${[...k].join("\\s*")}(?!\\d|등급|점|문제|문항|개)`).test(spaced) : t.includes(k));
    const subjectId = SUBJECT_ALIASES.find(([, keys]) => keys.some(found))?.[0] ?? null;
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
    const w = { exam: "", subjectId: null, subjectPicked: false, picking: false, unitIds: [], scope: "",
      examDate: isoAfter(30), dateShown: false, dateTouched: false, goal: "", goalTouched: false, nameTouched: false,
      questionType: "multiple_choice", files: [], busy: false };
    const sheet = openSheet({
      title: "새 프로젝트", wide: true,
      body: `
        <div class="np">
          <label class="np-q" for="np-exam">어떤 시험을 준비하나요?</label>
          <input id="np-exam" class="np-big" autocomplete="off" maxlength="60"
            placeholder="예: 2027 수능 미적분 1등급 · 화학I 중간고사 90점, 4월 25일" />
          <div class="np-read" data-read></div>
          <div class="np-subjects" data-subjects>${SUBJECTS.map((x) => `
            <button type="button" class="tag" data-subject="${x.id}" style="--c:${COLOR[x.domain]}"><span class="sw"></span>${esc(x.name)}</button>`).join("")}</div>
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
            <div class="field"><label>문제 형태</label>
              <div class="seg qtype">${Object.entries(QTYPE).map(([k, v]) => `<button type="button" data-qtype="${k}" class="${w.questionType === k ? "on" : ""}">${v}</button>`).join("")}</div></div>
            <div class="field"><label for="w-name">프로젝트 이름</label><input id="w-name" maxlength="30" /></div>
            ${Store.mode === "api" ? `<details class="np-upload">
              <summary><i data-lucide="chevron-right"></i>기출·시험지 올리기 <small>선택 · 올리면 그 시험과 비슷한 결의 문제를 만들어 드려요</small></summary>
              ${dropzoneHTML()}</details>` : ""}
          </div>
        </div>`,
      footer: `<div class="modal-foot"><button type="button" class="btn-ghost" data-close>취소</button>
        <button type="submit" class="btn-primary" data-next disabled>만들기</button></div>`,
      onSubmit: () => { submit(); return false; },
    });
    const body = $(".modal-body", sheet);
    const subjectName = () => concept(w.subjectId)?.name ?? "";

    // 알아들은 것 (칩) + 과목 고르기 + 아래 칸 보이기
    function drawRead() {
      const chips = [];
      if (w.subjectId) chips.push(`<span class="np-chip" style="--c:${COLOR[concept(w.subjectId).domain]}"><span class="sw"></span>${esc(subjectName())}
        <button type="button" data-change-subject>바꾸기</button></span>`);
      if (w.goal) chips.push(`<span class="np-chip"><i data-lucide="target"></i>목표 ${esc(w.goal)}</span>`);
      if (w.dateShown && w.examDate) chips.push(`<span class="np-chip"><i data-lucide="calendar"></i>시험일 ${esc(w.examDate)}</span>`);
      const unknown = w.exam.trim() && !w.subjectId;
      $("[data-read]", body).innerHTML = unknown ? `<span class="mini">어떤 과목인지 알아듣지 못했어요. 아래에서 골라 주세요</span>` : chips.join("");
      $("[data-subjects]", body).hidden = !!w.subjectId && !w.picking;
      $$("[data-subject]", body).forEach((b) => b.classList.toggle("on", b.dataset.subject === w.subjectId));
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
      if (!w.nameTouched) $("#w-name").value = (w.exam.trim() || `${subjectName()} 시험 준비`).slice(0, 30);
    }
    function setSubject(id) {
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
    body.addEventListener("click", (e) => {
      const subj = e.target.closest("[data-subject]");
      if (subj) { w.subjectPicked = true; w.picking = false; return setSubject(subj.dataset.subject); }
      if (e.target.closest("[data-change-subject]")) { w.picking = true; return drawRead(); }
      const days = e.target.closest("[data-days]");
      if (days) { w.examDate = isoAfter(Number(days.dataset.days)); w.dateTouched = w.dateShown = true; drawFields(); drawRead(); }
      const qt = e.target.closest("[data-qtype]");
      if (qt) { w.questionType = qt.dataset.qtype; $$("[data-qtype]", body).forEach((b) => b.classList.toggle("on", b === qt)); }
    });
    body.addEventListener("change", (e) => {
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
          examDate: w.examDate, questionType: w.questionType });
        const uploaded = w.files.length ? await uploadAll(id, w.files) : 0;
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
      title: "기출·시험지 올리기", body: dropzoneHTML(),
      footer: `<div class="modal-foot"><button type="button" class="btn-ghost" data-close>취소</button><button type="submit" class="btn-primary" data-up disabled>올리기</button></div>`,
      onMount(f) { bindDropzone(f, files, () => { $("[data-up]", f).disabled = !files.length; $("[data-up]", f).textContent = files.length ? `${files.length}개 올리기` : "올리기"; }); },
      onSubmit(f) {
        if (!$("[data-rights]", f).checked) { toast("학습용으로 쓸 수 있는 자료인지 확인해 주세요"); return false; }
        const btn = $("[data-up]", f);
        btn.disabled = true;
        btn.textContent = "올리는 중…";
        uploadAll(projectId, files).then((n) => { closeOverlays(); if (n) toast(`${n}개를 올렸어요. AI가 문제를 읽는 중이에요`); onDone(); });
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
          .map((c) => ({ icon: "book-open", t: c.name, go: `/library/concept/${c.id}`, sub: subjectOf(c.id).name }))]);
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
  render();

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

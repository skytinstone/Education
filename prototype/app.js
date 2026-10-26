// Eureka 프로토타입 앱 — 해시 라우팅, 사이드바, 메뉴별 화면(새 학습·대화·프로젝트·오답노트·라이브러리),
// 모달·메뉴·⌘K 검색. 데이터는 store.js 의 Store, 개념 트리는 concepts.js 의 CONCEPTS 를 쓴다.
(() => {
  // ================= 유틸 =================
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s = "") => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const icons = () => lucide.createIcons();
  const DAY = 864e5;

  const DOMAINS = ["math", "physics", "chemistry", "biology", "earth_science"];
  const COLOR = { math: "var(--math)", physics: "var(--physics)", chemistry: "var(--chemistry)", biology: "var(--biology)", earth_science: "var(--earth)" };
  const DOMAIN_NAME = { math: "수학", physics: "물리", chemistry: "화학", biology: "생명과학", earth_science: "지구과학" };

  const conceptMap = Object.fromEntries(CONCEPTS.map((c) => [c.id, c]));
  const concept = (id) => conceptMap[id];
  const childrenOf = (id) => CONCEPTS.filter((c) => c.parent_id === id);
  const pathOf = (id) => { const out = []; for (let c = concept(id); c; c = concept(c.parent_id)) out.unshift(c); return out; };
  const subjectOf = (id) => pathOf(id)[0];
  const SUBJECTS = CONCEPTS.filter((c) => c.level === "subject");
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
    else return go("/");
    renderSidebar();
    if (page !== "chat") contentEl.scrollTop = 0;
    icons();
    $("#app").classList.remove("mobile-open");
  }
  window.addEventListener("hashchange", render);
  Store.subscribe(() => {
    // 보고 있던 대화·프로젝트가 삭제되면 홈으로
    const [page, id] = route().parts;
    if ((page === "chat" && !Store.session(id)) || (page === "project" && !Store.project(id))) return go("/");
    renderSidebar();
  });

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
    $("#profile-avatar").textContent = st.user.name.slice(0, 1);
    $("#profile-sub").textContent = `오늘 ${Store.todayCount()} / ${st.user.dailyGoal}문제 · 🔥 ${Store.streak()}일 연속`;
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
  $("#new-project").addEventListener("click", () => projectModal());
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
      { icon: "user", label: "이름 바꾸기", run: () => formModal({
        title: "이름 바꾸기", submit: "저장",
        body: `<div class="field"><label for="f-name">이름</label><input id="f-name" value="${esc(Store.state.user.name)}" maxlength="20" /></div>`,
        onSubmit: (f) => { const v = $("#f-name", f).value.trim(); if (!v) return invalid($("#f-name", f), "이름을 입력해 주세요"); Store.updateUser({ name: v }); },
      }) },
      { icon: "target", label: `하루 목표 (${Store.state.user.dailyGoal}문제)`, run: () => formModal({
        title: "하루 목표", submit: "저장",
        body: `<div class="field"><label for="f-goal">하루에 풀 문제 수</label><input id="f-goal" type="number" min="1" max="200" value="${Store.state.user.dailyGoal}" /></div>`,
        onSubmit: (f) => { const v = Number($("#f-goal", f).value); if (!(v >= 1 && v <= 200)) return invalid($("#f-goal", f), "1에서 200 사이로 입력해 주세요"); Store.updateUser({ dailyGoal: v }); },
      }) },
      { icon: "rotate-ccw", label: "데모 데이터 초기화", run: () => confirmModal({
        title: "데모 데이터를 초기화할까요?", text: "직접 만든 프로젝트, 대화, 풀이 기록이 모두 지워지고 처음 샘플 데이터로 돌아가요.", action: "초기화",
        run: () => { Store.reset(); go("/"); render(); toast("처음 상태로 되돌렸어요"); },
      }) },
      "-",
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
    const sid = Store.createSession({ projectId: homeProjectId, text });
    prompt.value = "";
    send.disabled = true;
    replyLater(sid);
    go(`/chat/${sid}`);
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
  const pending = new Set(); // 답변 대기 중인 대화

  // AI 연결 전: 요청 문장에서 과목·문항 수를 읽어 문제 은행에서 샘플 문제를 고른다
  const KEYWORDS = [
    ["math", /수학|미적|적분|미분|로그|수열|확률|함수|모의고사/],
    ["physics", /물리|운동|역학|가속|운동량|속력/],
    ["chemistry", /화학|몰|중화|산화|염기|분자/],
    ["biology", /생명|생물|염색체|유전|세포/],
    ["earth_science", /지구|별|H-R|반감기|지층|은하/],
  ];
  function pickProblems(text, projectId) {
    let domain = projectDomain(Store.project(projectId));
    for (const [d, re] of KEYWORDS) if (re.test(text)) { domain = d; break; }
    const pool = Store.bank.filter((p) => !domain || p.domain === domain);
    const n = Math.min(Number(text.match(/(\d+)\s*(문제|문항|개)/)?.[1]) || 2, 3, pool.length);
    return [...pool].sort(() => Math.random() - 0.5).slice(0, n).map((p) => p.id);
  }

  function replyLater(sid) {
    pending.add(sid);
    setTimeout(() => {
      const s = Store.session(sid);
      pending.delete(sid);
      if (!s) return;
      const ask = s.messages.filter((m) => m.role === "user").at(-1).text;
      const ids = pickProblems(ask, s.projectId);
      Store.addMessage(sid, {
        role: "ai",
        text: `AI 연결 전이라 문제 은행의 샘플 문제 ${ids.length}개를 보여드려요. 틀린 문제는 오답노트에 자동으로 저장돼요.`,
        problemIds: ids,
      });
      if (navKey() === `chat:${sid}`) renderChat(sid, { keepScroll: false });
    }, 800);
  }

  function problemHTML(pid, { attempt = null, index = null } = {}) {
    const p = Store.problem(pid);
    const c = concept(p.conceptIds[0]);
    const saved = Store.state.savedProblemIds.includes(pid);
    const choices = p.choices.map((ch, i) => {
      const n = String(i + 1);
      const cls = !attempt ? "" : n === p.answer ? "correct" : n === attempt.answer ? "wrong" : "dim";
      return `<button class="choice ${cls}" data-choice="${n}" ${attempt ? "disabled" : ""}><span class="n">${n}</span>${esc(ch)}</button>`;
    }).join("");
    let result = "";
    if (attempt) {
      const note = !attempt.correct && Store.state.wrongNotes.find((w) => w.problemId === pid && !w.resolvedAt);
      result = `
        <div class="result ${attempt.correct ? "ok" : "bad"}">
          <i data-lucide="${attempt.correct ? "circle-check" : "circle-x"}"></i>${attempt.correct ? "정답이에요!" : "아쉬워요. 오답노트에 저장했어요"}
        </div>
        <div class="solution"><b>해설</b>${esc(p.solution)}</div>
        ${note ? whyHTML(note) : ""}`;
    }
    return `
      <article class="problem" data-problem="${pid}" style="--c:${COLOR[p.domain]}">
        <div class="problem-meta">
          <span class="kind"><span class="sw"></span>${esc(subjectOf(c.id).name)} · ${esc(c.name)}</span>
          <span class="stars" title="난이도 ${p.difficulty}">${"★".repeat(p.difficulty)}${"☆".repeat(5 - p.difficulty)}</span>
          <button class="icon-btn save ${saved ? "on" : ""}" data-save="${pid}" title="${saved ? "저장 취소" : "저장"}"><i data-lucide="bookmark"></i></button>
        </div>
        <p class="stem">${index ? `<b>${index}.</b> ` : ""}${esc(p.stem)}</p>
        <div class="choices">${choices}</div>
        ${result}
      </article>`;
  }

  const whyHTML = (note) => `
    <div class="why">왜 틀렸나요?
      ${Object.entries(ERROR_TYPES).filter(([k]) => k !== "unknown").map(([k, v]) =>
        `<button class="tag ${note.errorType === k ? "on" : ""}" data-error="${k}" data-note="${note.id}">${v}</button>`).join("")}
    </div>`;

  // 문제 카드 공통 동작: 저장, 틀린 이유 표시
  function handleProblemExtras(e) {
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

  function renderChat(id, { keepScroll = false } = {}) {
    const s = Store.session(id);
    if (!s) { toast("대화를 찾을 수 없어요"); return go("/"); }
    const scroll = contentEl.scrollTop;
    const p = s.projectId && Store.project(s.projectId);
    const msgs = s.messages.map((m) => m.role === "user"
      ? `<div class="msg user"><div class="bubble">${esc(m.text)}</div></div>`
      : `<div class="msg ai"><span class="ai-avatar"></span><div class="ai-body"><p>${esc(m.text)}</p>
          ${(m.problemIds ?? []).map((pid, i) => problemHTML(pid, { attempt: Store.lastAttempt(s.id, pid), index: i + 1 })).join("")}
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
          ${pending.has(id) ? '<div class="msg ai"><span class="ai-avatar"></span><div class="typing"><i></i><i></i><i></i></div></div>' : ""}
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
      Store.addMessage(id, { role: "user", text });
      replyLater(id);
      renderChat(id);
      $("#chat-input").focus();
    });
    $("#chat-more").addEventListener("click", (e) => chatMenu(e.currentTarget, id));

    view.onclick = (e) => {
      if (handleProblemExtras(e)) return;
      const choice = e.target.closest("[data-choice]");
      if (!choice) return;
      const pid = choice.closest("[data-problem]").dataset.problem;
      const { correct } = Store.answer({ problemId: pid, answer: choice.dataset.choice, projectId: s.projectId, sessionId: s.id });
      renderChat(id, { keepScroll: true });
      if (correct && Store.state.wrongNotes.some((w) => w.problemId === pid && w.resolvedAt > Date.now() - 1000)) toast("오답을 극복했어요! 🎉");
    };

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
          <p>${esc(concept(p.subjectId).name)}${p.goal ? ` · 목표 ${esc(p.goal)}` : ""}${p.examDate ? ` · 시험일 ${p.examDate}` : ""}</p>
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
      <div class="toolbar">
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
      if (e.target.dataset.setError) Store.setErrorType(e.target.dataset.setError, e.target.value);
    };
  }

  function renderNoteList() {
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
      const c = concept(p.conceptIds[0]);
      return `
        <article class="note ${w.resolvedAt ? "resolved" : ""}" style="--c:${COLOR[p.domain]}">
          <div class="note-top">
            <span class="kind"><span class="sw"></span>${esc(subjectOf(c.id).name)} · ${esc(c.name)}</span>
            ${w.resolvedAt ? '<span class="pill done-pill"><i data-lucide="check"></i>극복</span>' : ""}
            <time>${relTime(w.createdAt)}</time>
          </div>
          <p class="stem">${esc(p.stem)}</p>
          <p class="mine">내 답 ${w.answer || "–"}번 · 정답은 다시 풀어서 확인해요</p>
          <div class="note-actions">
            <button class="btn-primary" data-retry="${w.id}"><i data-lucide="rotate-ccw"></i>${w.resolvedAt ? "한 번 더 풀기" : "다시 풀기"}</button>
            <a class="btn-ghost" href="#/library/concept/${c.id}" style="text-decoration:none;color:inherit"><i data-lucide="book-open"></i>개념 보기</a>
            <button class="btn-ghost" disabled title="AI 연결 후 사용할 수 있어요" style="opacity:.5;cursor:default"><i data-lucide="sparkles"></i>변형 문제</button>
            <select class="select" data-set-error="${w.id}" aria-label="틀린 이유">
              ${Object.entries(ERROR_TYPES).map(([k, v]) => `<option value="${k}" ${w.errorType === k ? "selected" : ""}>${k === "unknown" ? "틀린 이유 선택" : v}</option>`).join("")}
            </select>
            <button class="icon-btn" data-del-note="${w.id}" title="삭제" style="margin-left:auto"><i data-lucide="trash-2"></i></button>
          </div>
        </article>`;
    }).join("") : `
      <div class="empty"><i data-lucide="party-popper"></i><b>${noteFilter.openOnly ? "남은 오답이 없어요" : "오답이 없어요"}</b>문제를 풀다 틀리면 여기에 모여요</div>`;
    icons();
  }

  function retryModal(noteId) {
    const w = Store.state.wrongNotes.find((n) => n.id === noteId);
    openSheet({
      title: "다시 풀기",
      body: problemHTML(w.problemId),
      onMount(sheet) {
        sheet.addEventListener("click", (e) => {
          if (handleProblemExtras(e)) return;
          const choice = e.target.closest("[data-choice]");
          if (!choice) return;
          const { correct } = Store.answer({ problemId: w.problemId, answer: choice.dataset.choice, projectId: w.projectId });
          const attempt = { answer: choice.dataset.choice, correct };
          $(".modal-body", sheet).innerHTML = problemHTML(w.problemId, { attempt });
          icons();
          if (correct) toast("오답을 극복했어요! 🎉");
          if (navKey() === "notes") renderNoteList();
        });
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
      <div class="ai-slot"><i data-lucide="sparkles"></i><div><b style="color:var(--ink)">개념 정리 · 필수 암기</b><br />AI 연결 후 이 개념의 핵심 정리와 꼭 외워야 할 내용이 여기에 만들어져요.</div></div>
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

    view.onclick = (e) => {
      if (handleProblemExtras(e)) return;
      const choice = e.target.closest("[data-choice]");
      if (!choice) return;
      const box = choice.closest("[data-problem]");
      const pid = box.dataset.problem;
      const { correct } = Store.answer({ problemId: pid, answer: choice.dataset.choice });
      box.outerHTML = problemHTML(pid, { attempt: { answer: choice.dataset.choice, correct } });
      icons();
    };
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
      if (handleProblemExtras(e)) return;
      const choice = e.target.closest("[data-choice]");
      if (!choice) return;
      const box = choice.closest("[data-problem]");
      const { correct } = Store.answer({ problemId: box.dataset.problem, answer: choice.dataset.choice });
      box.outerHTML = problemHTML(box.dataset.problem, { attempt: { answer: choice.dataset.choice, correct } });
      icons();
    };
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

  // ================= 팝업 메뉴 =================
  let menuCleanup = null;
  function openMenu(anchor, items, onClose) {
    closeMenu();
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
          { icon: "folder-plus", t: "새 프로젝트 만들기", run: projectModal },
        ]]);
        groups.push(["최근 대화", [...Store.state.sessions].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, 5)
          .map((s) => ({ icon: "message-circle", t: s.title, go: `/chat/${s.id}`, sub: relTime(s.updatedAt) }))]);
      } else {
        groups.push(["프로젝트", Store.state.projects.filter((p) => has(p.name))
          .map((p) => ({ icon: "folder", t: p.name, go: `/project/${p.id}`, sub: ddayLabel(daysLeft(p.examDate)) }))]);
        groups.push(["대화", Store.state.sessions.filter((s) => has(s.title) || s.messages.some((m) => has(m.text)))
          .map((s) => ({ icon: "message-circle", t: s.title, go: `/chat/${s.id}`, sub: relTime(s.updatedAt) }))]);
        groups.push(["오답", Store.state.wrongNotes.filter((w) => has(Store.problem(w.problemId).stem) || has(concept(Store.problem(w.problemId).conceptIds[0]).name))
          .map((w) => ({ icon: "circle-x", t: Store.problem(w.problemId).stem, go: "/notes", sub: w.resolvedAt ? "극복" : "안 품" }))]);
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

  // 첫 화면 표시
  render();

  // 홈 요소: 스크롤하면 아래에서 위로 떠오름
  [[".hero h1", ".hero p", ".hero .composer"], [".action"], [".banner"], [".tabs"], ["#cards-recent .card"], ["#cards-recommend .card"], [".section-head"], [".subject"]]
    .forEach((group) => group.flatMap((s) => $$(s)).forEach((el, i) => { el.classList.add("reveal"); el.style.setProperty("--d", `${i * 70}ms`); }));
  const revealer = new IntersectionObserver((entries) => {
    for (const e of entries) if (e.isIntersecting) { e.target.classList.add("in"); revealer.unobserve(e.target); }
  }, { root: contentEl, threshold: 0.12, rootMargin: "0px 0px -6% 0px" });
  $$(".reveal").forEach((el) => revealer.observe(el));

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

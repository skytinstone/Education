// 오늘 방문자 — 페이지가 열리면 방문을 한 번 기록하고(같은 브라우저는 하루 한 번만 센다),
// [data-visitors] 요소가 있으면 오늘 방문자 수를 실시간으로 보여 준다 (20초마다 새로 받음).
(() => {
  if (!location.protocol.startsWith("http")) return; // 파일로 연 미리보기에서는 하지 않음
  const KEY = "eureka.vid";
  const newId = () => (crypto.randomUUID ? crypto.randomUUID()
    : "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) => (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16)));
  let vid;
  try {
    vid = localStorage.getItem(KEY);
    if (!vid) localStorage.setItem(KEY, (vid = newId()));
  } catch { vid = newId(); }

  const targets = () => [...document.querySelectorAll("[data-visitors]")];
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let shown = null;

  // 숫자가 바뀌면 올라가는 효과
  function show(n) {
    if (typeof n !== "number") return;
    const from = shown ?? n;
    shown = n;
    targets().forEach((el) => {
      el.closest("[data-visitors-box]")?.removeAttribute("hidden");
      if (reduce || from === n) { el.textContent = n.toLocaleString("ko-KR"); return; }
      const t0 = performance.now(), dur = 700;
      const step = (t) => {
        const k = Math.min(1, (t - t0) / dur), e = 1 - (1 - k) ** 3;
        el.textContent = Math.round(from + (n - from) * e).toLocaleString("ko-KR");
        if (k < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
      if (n > from) {
        const box = el.closest("[data-visitors-box]");
        box?.classList.remove("bump");
        void box?.offsetWidth;
        box?.classList.add("bump");
      }
    });
  }

  const get = (url, opts) => fetch(url, opts).then((r) => (r.ok ? r.json() : null)).then((d) => show(d?.today)).catch(() => {});
  get("/api/visits", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ visitor_id: vid, path: location.pathname.slice(0, 100) }) });

  if (targets().length) {
    setInterval(() => { if (document.visibilityState === "visible") get("/api/visits/today"); }, 20000);
    document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") get("/api/visits/today"); });
  }
})();

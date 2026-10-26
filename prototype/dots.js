// 무지개 도트 필드 — 메인 화면과 로그인 화면이 함께 사용
// 격자 점 위로 대각선 물결이 지나가며 점이 커지고 무지개색으로 빛난다.
// 시작할 때는 왼쪽 → 오른쪽으로 "촤라락" 쓸려 나타난다.
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

function dotField(canvas, o) {
  const ctx = canvas.getContext("2d");
  let W = 0, H = 0;
  // ?t=4 처럼 주면 해당 시점부터 시작 (스크린샷 확인용)
  const t0 = performance.now() - (Number(new URLSearchParams(location.search).get("t")) || 0) * 1000;

  function resize() {
    const r = canvas.getBoundingClientRect();
    const dpr = Math.min(devicePixelRatio || 1, 2);
    W = r.width; H = r.height;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  new ResizeObserver(resize).observe(canvas);
  resize();

  // 글자 영역(clear 요소) 주변은 점이 부드럽게 사라지도록
  function clearMask(x, y, rects) {
    let k = 1;
    for (const r of rects) {
      const dx = Math.max(r.left - x, 0, x - r.right);
      const dy = Math.max(r.top - y, 0, y - r.bottom);
      k = Math.min(k, Math.min(1, Math.hypot(dx, dy) / 26));
    }
    return k;
  }

  function draw(t) {
    ctx.clearRect(0, 0, W, H);
    const [fx, fy] = o.focus(W, H);
    const reach = Math.hypot(W, H) * o.reach;
    const intro = Math.min(1, t / o.introSec);
    const front = intro * (W + 240) - 120;
    const rects = (o.clear?.() ?? []).map((r) => ({ left: r.left - 6, right: r.right + 6, top: r.top - 4, bottom: r.bottom + 4 }));

    // 비슷한 색(색상 15° × 투명도 8단계)끼리 묶어 한 번에 칠한다 → fill 호출 수천 → 수십
    const buckets = new Map();
    // 스크롤 시차: 도트 무늬가 콘텐츠보다 느리게 위로 흘러감
    const sy = (o.scrollY?.() ?? 0) * 0.35;
    for (let y = o.gap / 2 - (sy % o.gap); y < H; y += o.gap) {
      for (let x = o.gap / 2; x < W; x += o.gap) {
        if (x > front) continue;
        let m = o.edges
          ? Math.min(1, Math.max(0, (Math.abs(x - fx) / (W / 2) - 0.3) / 0.6)) // 가운데 비우고 양옆으로
          : 1 - Math.hypot(x - fx, y - fy) / reach;
        if (o.floor) m = Math.max(m, o.floor); // 화면 전체에 최소 진하기 보장
        if (rects.length) m *= clearMask(x, y, rects);
        if (m <= 0) continue;
        m = m * m * (3 - 2 * m);

        let w = (Math.sin((x + (y + sy) * 0.5) / o.wavelength - t * o.speed) + 1) / 2;
        w = w * w * w;
        if (intro < 1) w = Math.max(w, Math.exp(-(((front - x) / 70) ** 2)));

        const alpha = (o.baseAlpha + w * o.peakAlpha) * m;
        if (alpha < 0.02) continue;
        const hue = Math.round((((x / W) * 330 + t * o.hueSpeed) % 360) / 15) * 15;
        const key = `${hue},${Math.round(alpha * 8)}`;
        let list = buckets.get(key);
        if (!list) buckets.set(key, (list = []));
        list.push(x, y, o.baseR + w * o.peakR * m);
      }
    }

    for (const [key, list] of buckets) {
      const [hue, a8] = key.split(",");
      ctx.fillStyle = `hsla(${hue},92%,${o.light}%,${a8 / 8})`;
      ctx.beginPath();
      for (let i = 0; i < list.length; i += 3) {
        ctx.moveTo(list[i] + list[i + 2], list[i + 1]);
        ctx.arc(list[i], list[i + 1], list[i + 2], 0, 6.2832);
      }
      ctx.fill();
    }
  }

  function frame(now) {
    draw((now - t0) / 1000);
    requestAnimationFrame(frame);
  }
  if (reduceMotion) { draw(o.introSec + 2); new ResizeObserver(() => draw(o.introSec + 2)).observe(canvas); }
  else requestAnimationFrame(frame);
}

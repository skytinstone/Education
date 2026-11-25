// 헤드라인의 '바뀌는 한 단어' — 단어 길이에 맞춰 칸 너비도 같이 바뀌게 한다.
// CSS 애니메이션만 쓰면 칸이 가장 긴 단어 폭으로 고정돼 짧은 단어 뒤에 빈칸이 생긴다.
// 마크업: <span class="slot"><span class="reel"><span>단어</span>…<span>첫 단어 반복</span></span></span>
(() => {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const EASE = "cubic-bezier(.7,0,.2,1)";

  function start(slot) {
    const reel = slot.querySelector(".reel");
    const items = [...reel.children];
    if (items.length < 2) return;
    reel.style.animation = "none";
    items.forEach((s) => (s.style.alignSelf = "flex-start"));
    let i = 0;
    const fit = () => (slot.style.width = items[i].getBoundingClientRect().width + "px");
    fit();
    addEventListener("resize", fit);
    if (reduce) return;
    slot.style.transition = `width .7s ${EASE}`;
    setInterval(() => {
      i += 1;
      reel.style.transition = `transform .7s ${EASE}`;
      reel.style.transform = `translateY(${-i * 1.2}em)`;
      fit();
      // 마지막은 첫 단어의 복사본: 다 넘어가면 몰래 처음으로 되돌린다
      if (i === items.length - 1) {
        setTimeout(() => {
          reel.style.transition = "none";
          reel.style.transform = "none";
          i = 0;
        }, 750);
      }
    }, 2000);
  }

  const run = () => document.querySelectorAll(".slot").forEach(start);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(run);
  else addEventListener("load", run);
})();

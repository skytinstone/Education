"""개념 트리(data/concepts/*.yaml)를 프로토타입 화면용 prototype/concepts.js 로 내보낸다.

file:// 로 연 페이지에서는 fetch 로 JSON 을 읽을 수 없어서, 전역 변수로 담은 JS 파일을 만든다.
    uv run python scripts/export_concepts.py
"""

import json
from pathlib import Path

from education.concepts import load_template_courses

OUT = Path(__file__).resolve().parents[1] / "prototype" / "concepts.js"


def main() -> None:
    courses, tree = load_template_courses()
    concepts = [c.model_dump(mode="json") for c in tree]  # YAML 순서 = 교육과정 순서 (단원 "~까지" 범위에 쓰임)
    meta = [c.model_dump(mode="json") | {"source": "template", "units": len(tree.children(c.id)),
                                         "concepts": sum(len(tree.children(u.id)) for u in tree.children(c.id))} for c in courses]
    dump = lambda x: json.dumps(x, ensure_ascii=False, indent=None, separators=(",", ":"))  # noqa: E731
    OUT.write_text(
        "// 자동 생성 파일 — scripts/export_concepts.py 로 다시 만들 것 (직접 수정 금지)\n"
        "// 로그인 없이 파일로 열었을 때(로컬 모드)만 쓴다. 서버 모드에서는 /api/sync 의 코스·개념을 쓴다\n"
        f"window.CONCEPTS = {dump(concepts)};\nwindow.COURSES = {dump(meta)};\n",
        encoding="utf-8",
    )
    print(f"{len(concepts)}개 개념 → {OUT}")


if __name__ == "__main__":
    main()

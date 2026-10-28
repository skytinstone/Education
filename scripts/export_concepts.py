"""개념 트리(data/concepts/*.yaml)를 프로토타입 화면용 prototype/concepts.js 로 내보낸다.

file:// 로 연 페이지에서는 fetch 로 JSON 을 읽을 수 없어서, 전역 변수로 담은 JS 파일을 만든다.
    uv run python scripts/export_concepts.py
"""

import json
from pathlib import Path

from education.concepts import load_concept_tree

OUT = Path(__file__).resolve().parents[1] / "prototype" / "concepts.js"


def main() -> None:
    tree = load_concept_tree()
    concepts = [c.model_dump(mode="json") for c in tree]  # YAML 순서 = 교육과정 순서 (단원 "~까지" 범위에 쓰임)
    body = json.dumps(concepts, ensure_ascii=False, indent=None, separators=(",", ":"))
    OUT.write_text(
        "// 자동 생성 파일 — scripts/export_concepts.py 로 다시 만들 것 (직접 수정 금지)\n"
        f"window.CONCEPTS = {body};\n",
        encoding="utf-8",
    )
    print(f"{len(concepts)}개 개념 → {OUT}")


if __name__ == "__main__":
    main()

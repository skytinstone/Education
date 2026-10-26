"""data/concepts/*.yaml 에서 개념 트리를 읽어 Concept 목록으로 펼친다.

YAML 은 사람이 편집하기 쉽도록 중첩 구조로 쓰고, 여기서 점 표기 id 를 만든다.
    subjects:
      - key: math1
        name: 수학I
        units:
          - key: exp_log
            name: 지수함수와 로그함수
            concepts:
              - key: log_properties
                name: 로그의 성질
                prerequisites: [math.math1.exp_log.exponent_rules]
"""

from __future__ import annotations

from pathlib import Path

import yaml

from education.schemas import Concept, ConceptLevel, Domain

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data" / "concepts"


class ConceptTree:
    def __init__(self, concepts: list[Concept]):
        self._by_id: dict[str, Concept] = {}
        for c in concepts:
            if c.id in self._by_id:
                raise ValueError(f"중복된 개념 id: {c.id}")
            self._by_id[c.id] = c
        self._validate_refs()

    def _validate_refs(self) -> None:
        for c in self._by_id.values():
            refs = ([c.parent_id] if c.parent_id else []) + c.prerequisites
            for ref in refs:
                if ref not in self._by_id:
                    raise ValueError(f"{c.id} 가 존재하지 않는 개념을 참조함: {ref}")

    def __len__(self) -> int:
        return len(self._by_id)

    def __contains__(self, concept_id: str) -> bool:
        return concept_id in self._by_id

    def __iter__(self):
        return iter(self._by_id.values())

    def get(self, concept_id: str) -> Concept:
        return self._by_id[concept_id]

    def children(self, concept_id: str) -> list[Concept]:
        return [c for c in self._by_id.values() if c.parent_id == concept_id]

    def by_level(self, level: ConceptLevel, domain: Domain | None = None) -> list[Concept]:
        return [
            c
            for c in self._by_id.values()
            if c.level is level and (domain is None or c.domain is domain)
        ]

    def path(self, concept_id: str) -> list[Concept]:
        """루트(과목)부터 해당 개념까지의 경로."""
        node = self.get(concept_id)
        chain = [node]
        while node.parent_id:
            node = self.get(node.parent_id)
            chain.append(node)
        return chain[::-1]


def _parse_file(path: Path) -> list[Concept]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    domain = Domain(data["domain"])
    out: list[Concept] = []
    for subject in data["subjects"]:
        sid = f"{domain}.{subject['key']}"
        out.append(Concept(id=sid, name=subject["name"], domain=domain, level=ConceptLevel.SUBJECT))
        for unit in subject["units"]:
            uid = f"{sid}.{unit['key']}"
            out.append(
                Concept(id=uid, name=unit["name"], domain=domain, level=ConceptLevel.UNIT, parent_id=sid)
            )
            for concept in unit.get("concepts", []):
                out.append(
                    Concept(
                        id=f"{uid}.{concept['key']}",
                        name=concept["name"],
                        domain=domain,
                        level=ConceptLevel.CONCEPT,
                        parent_id=uid,
                        prerequisites=concept.get("prerequisites", []),
                    )
                )
    return out


def load_concept_tree(directory: Path = DEFAULT_DIR) -> ConceptTree:
    concepts: list[Concept] = []
    for path in sorted(directory.glob("*.yaml")):
        concepts.extend(_parse_file(path))
    return ConceptTree(concepts)

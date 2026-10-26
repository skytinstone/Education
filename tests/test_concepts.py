import pytest

from education.concepts import load_concept_tree
from education.schemas import ConceptLevel, Domain, Problem, ProblemSource, ProblemType


@pytest.fixture(scope="module")
def tree():
    return load_concept_tree()


def test_all_domains_loaded(tree):
    subjects = tree.by_level(ConceptLevel.SUBJECT)
    assert {s.domain for s in subjects} == set(Domain)


def test_path_from_subject_to_concept(tree):
    path = tree.path("math.math1.exp_log.log_properties")
    assert [c.level for c in path] == [ConceptLevel.SUBJECT, ConceptLevel.UNIT, ConceptLevel.CONCEPT]
    assert path[0].name == "수학I"


def test_prerequisites_resolve(tree):
    concept = tree.get("chemistry.chemistry1.dynamic_reactions.neutralization")
    assert all(p in tree for p in concept.prerequisites)


def test_multiple_choice_requires_five_choices():
    base = dict(
        id="p1",
        domain=Domain.MATH,
        concept_ids=["math.math1.exp_log.log_properties"],
        difficulty=2,
        problem_type=ProblemType.MULTIPLE_CHOICE,
        stem=r"$\log_2 8$ 의 값은?",
        answer="3",
        solution=r"$2^3 = 8$ 이므로 3",
        source=ProblemSource.GENERATED,
    )
    Problem(**base, choices=["1", "2", "3", "4", "5"])
    with pytest.raises(ValueError):
        Problem(**base, choices=["1", "2", "3"])

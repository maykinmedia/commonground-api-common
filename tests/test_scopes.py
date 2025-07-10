from vng_api_common.scopes import Scope

SCOPE_A = Scope("A", "scope a")
SCOPE_B = Scope("B", "scope b")


def test_scope_or_operator():
    a_or_b = SCOPE_A | SCOPE_B

    assert a_or_b.label == "A | B"
    assert a_or_b.children == [SCOPE_A, SCOPE_B]

    assert a_or_b.is_contained_in(["A"])
    assert a_or_b.is_contained_in(["A", "B"])


def test_scope_and_operator():
    a_and_b = SCOPE_A & SCOPE_B

    assert a_and_b.label == "A & B"
    assert a_and_b.children == [SCOPE_A, SCOPE_B]

    assert not a_and_b.is_contained_in(["A"])
    assert a_and_b.is_contained_in(["A", "B"])

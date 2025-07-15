from vng_api_common.scopes import Scope

SCOPE_A = Scope("A", "scope a")
SCOPE_B = Scope("B", "scope b")
SCOPE_C = Scope("C", "scope b")


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


def test_scope_and_or_operator():
    a_and_b_or_c = SCOPE_A & SCOPE_B | SCOPE_C

    assert a_and_b_or_c.label == "A & B | C"

    assert not a_and_b_or_c.is_contained_in(["A"])
    assert a_and_b_or_c.is_contained_in(["A", "B"])
    assert a_and_b_or_c.is_contained_in(["C"])


def test_scope_and_or_operator_brackets():
    a_and_b_or_c = SCOPE_A & (SCOPE_B | SCOPE_C)

    assert a_and_b_or_c.label == "A & (B | C)"

    assert not a_and_b_or_c.is_contained_in(["A"])
    assert a_and_b_or_c.is_contained_in(["A", "B"])
    assert not a_and_b_or_c.is_contained_in(["C"])
    assert a_and_b_or_c.is_contained_in(["A", "C"])


def test_scope_and_or_operator_brackets_swapped():
    a_and_b_or_c = (SCOPE_B | SCOPE_C) & SCOPE_A

    assert a_and_b_or_c.label == "(B | C) & A"

    assert not a_and_b_or_c.is_contained_in(["A"])
    assert a_and_b_or_c.is_contained_in(["A", "B"])
    assert not a_and_b_or_c.is_contained_in(["C"])
    assert a_and_b_or_c.is_contained_in(["A", "C"])


def test_multi_or():
    a_or_b_or_c = SCOPE_A | SCOPE_B | SCOPE_C

    assert a_or_b_or_c.label == "A | B | C"

    assert a_or_b_or_c.is_contained_in(["A"])
    assert a_or_b_or_c.is_contained_in(["A", "B"])
    assert a_or_b_or_c.is_contained_in(["C"])
    assert a_or_b_or_c.is_contained_in(["A", "C"])
    assert a_or_b_or_c.is_contained_in(["A", "B", "C"])


def test_multi_and():
    a_and_b_and_c = SCOPE_A & SCOPE_B & SCOPE_C

    assert a_and_b_and_c.label == "A & B & C"

    assert not a_and_b_and_c.is_contained_in(["A"])
    assert not a_and_b_and_c.is_contained_in(["A", "B"])
    assert not a_and_b_and_c.is_contained_in(["C"])
    assert not a_and_b_and_c.is_contained_in(["A", "C"])
    assert a_and_b_and_c.is_contained_in(["A", "B", "C"])

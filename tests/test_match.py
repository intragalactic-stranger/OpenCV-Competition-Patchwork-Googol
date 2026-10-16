"""Cross-pass matcher v2 (register/match.py): gates and one-to-one assignment."""

from patchwork.register.match import LINK_D_M, LINK_S_M, Candidate, assign, cost


def c(key, s, d=0.0, a=0.5, seg="seg001"):
    return Candidate(key, seg, s, d, a)


def test_gates():
    assert cost(c("a", 100), c("b", 100 + LINK_S_M - 0.1)) is not None
    assert cost(c("a", 100), c("b", 100 + LINK_S_M + 0.1)) is None
    assert cost(c("a", 100, d=0.0), c("b", 100, d=LINK_D_M + 0.1)) is None
    assert cost(c("a", 100), c("b", 100, seg="seg002")) is None
    assert cost(c("a", 100, a=0.1), c("b", 100, a=0.5)) is None  # 5x larger: not the same defect
    assert cost(c("a", 100, a=None), c("b", 100, a=0.5)) is not None  # unmeasured: area gate skipped


def test_one_to_one_cheapest_first():
    known = [c("k1", 100.0), c("k2", 104.0)]
    new = [c("n1", 101.0), c("n2", 103.5), c("n3", 102.0)]
    links = assign(known, new)
    assert links == {"n1": "k1", "n2": "k2"}  # n3 loses both: each known defect absorbs one detection
    assert len(set(links.values())) == len(links)


def test_lateral_offset_separates_neighbours():
    # two potholes side by side at the same chainage: offset decides
    known = [c("left", 200, d=-1.5), c("right", 200, d=1.5)]
    new = [c("n_right", 203, d=1.3), c("n_left", 198, d=-1.7)]
    assert assign(known, new) == {"n_right": "right", "n_left": "left"}

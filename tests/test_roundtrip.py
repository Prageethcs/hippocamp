from hippocamp import Memory
from hippocamp.embedders import HashEmbedder


def _mem() -> Memory:
    """Memory with the deterministic stub embedder, for fast unit tests."""
    return Memory(path=":memory:", embedder=HashEmbedder())


def test_observe_then_recall():
    mem = _mem()
    ep_id = mem.observe("the user is asking about deploying to GCP")

    hits = mem.recall("deploy to gcp", limit=5)

    assert hits, "expected at least one recalled memory"
    assert any(h.id == ep_id for h in hits), "round-trip failed: episode not retrieved"
    top = hits[0]
    assert top.kind == "episode"
    assert top.score == top.why.total
    assert top.why.note


def test_recall_with_no_query_returns_empty():
    mem = _mem()
    assert mem.recall(None) == []


def test_inspect_counts_by_kind():
    mem = _mem()
    mem.observe("first")
    mem.observe("second")
    mem.assert_fact("the moon is round")
    mem.assert_preference("prefers terse replies")

    inv = mem.inspect()
    assert inv.episodes == 2
    assert inv.facts == 1
    assert inv.preferences == 1
    assert inv.reflections == 0


def test_kind_filter_excludes_other_kinds():
    mem = _mem()
    mem.observe("an episode")
    fact_id = mem.assert_fact("a fact about the world")

    hits = mem.recall("anything", kinds=["fact"], limit=10)

    assert all(h.kind == "fact" for h in hits)
    assert any(h.id == fact_id for h in hits)


def test_supersedes_marks_old_fact_inactive():
    mem = _mem()
    old = mem.assert_fact("project uses Python 3.12")
    mem.assert_fact("project uses Python 3.13", supersedes=[old])

    hits = mem.recall("python version", kinds=["fact"], limit=10)
    ids = {h.id for h in hits}
    assert old not in ids, "superseded fact should not be retrievable"

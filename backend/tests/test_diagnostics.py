from app.diagnostics import compute_diagnostics, filter_fresh
from app.lang import parse_document


def declared_of(*texts: str) -> set[str]:
    names: set[str] = set()
    for t in texts:
        names |= {s.name for s in parse_document(t).decls}
    return names


def test_undefined_use_position_after_emoji_comment():
    text = "# 🎉🎉 中文\ndef foo\nuse missing # 注释🎉"
    diags = compute_diagnostics(parse_document(text), declared_of(text))
    undef = [d for d in diags if d["severity"] == "warning"]
    assert len(undef) == 1
    assert (undef[0]["line"], undef[0]["start"], undef[0]["end"]) == (2, 4, 11)
    assert "missing" in undef[0]["message"]


def test_use_defined_in_other_document_is_not_flagged():
    diags = compute_diagnostics(parse_document("use foo"), declared_of("def foo"))
    assert diags == []


def test_duplicate_declaration():
    diags = compute_diagnostics(parse_document("def a\ndef a\nuse a"), {"a"})
    errs = [d for d in diags if "重复" in d["message"]]
    assert len(errs) == 1
    assert (errs[0]["line"], errs[0]["start"], errs[0]["end"]) == (1, 4, 5)


def test_unknown_statement_with_emoji_span():
    diags = compute_diagnostics(parse_document("🎉🎉\ndef ok"), {"ok"})
    assert diags[0]["severity"] == "error"
    # 两个 emoji 共 4 个 UTF-16 单元
    assert (diags[0]["line"], diags[0]["start"], diags[0]["end"]) == (0, 0, 4)


def test_filter_fresh_drops_stale_entries():
    entries = [
        {"doc_id": "a", "revision": 3, "diagnostics": []},
        {"doc_id": "b", "revision": 2, "diagnostics": []},
    ]
    fresh = filter_fresh(entries, {"a": 3, "b": 4})
    assert [e["doc_id"] for e in fresh] == ["a"]


def test_collect_binds_current_revision(client):
    from conftest import make_doc

    make_doc(client, "a", "def foo\nuse missing")
    entries = client.app.state.diag.collect()
    assert len(entries) == 1
    assert entries[0]["doc_id"] == "a"
    assert entries[0]["revision"] == 1
    assert any("missing" in d["message"] for d in entries[0]["diagnostics"])

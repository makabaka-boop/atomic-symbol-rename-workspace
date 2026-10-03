import pytest

from app.lang import (
    apply_ranges,
    parse_document,
    utf16_col_to_index,
    utf16_len,
)


def test_utf16_len():
    assert utf16_len("abc") == 3
    assert utf16_len("中文") == 2          # BMP 字符：1 个 UTF-16 单元
    assert utf16_len("🎉") == 2            # astral 字符：2 个 UTF-16 单元
    assert utf16_len("a🎉中b") == 5


def test_utf16_col_to_index():
    s = "ab🎉cd"
    assert utf16_col_to_index(s, 0) == 0
    assert utf16_col_to_index(s, 2) == 2
    assert utf16_col_to_index(s, 4) == 3   # 🎉 占两个 UTF-16 单元
    assert utf16_col_to_index(s, 6) == 5
    with pytest.raises(ValueError):
        utf16_col_to_index(s, 3)           # 代理对中间
    with pytest.raises(ValueError):
        utf16_col_to_index(s, 99)


def test_positions_after_chinese_and_emoji_comments():
    text = (
        "# 中文注释 🎉🎉\n"
        "def alpha\n"
        "use alpha # 尾巴🎉\n"
        "   # 整行 注释🎉\n"
        "use beta"
    )
    doc = parse_document(text)
    assert [(d.name, d.line, d.start, d.end) for d in doc.decls] == [
        ("alpha", 1, 4, 9)
    ]
    assert [(r.name, r.line, r.start, r.end) for r in doc.refs] == [
        ("alpha", 2, 4, 9),
        ("beta", 4, 4, 8),
    ]
    # 注释起始列同样按 UTF-16 计算
    assert (doc.comments[0].line, doc.comments[0].start) == (0, 0)
    assert (doc.comments[1].line, doc.comments[1].start) == (2, 10)
    assert (doc.comments[2].line, doc.comments[2].start) == (3, 3)
    assert "🎉" in doc.comments[0].text
    assert doc.comments[2].text == " 整行 注释🎉"


def test_comment_content_is_not_parsed_as_code():
    doc = parse_document("# def fake\n# use fake2 🎉\ndef real")
    assert [(s.kind, s.name) for s in doc.symbols] == [("def", "real")]


def test_symbol_at():
    doc = parse_document("def foo\nuse foo")
    assert doc.symbol_at(0, 4).name == "foo"
    assert doc.symbol_at(0, 7).name == "foo"   # 光标在符号末尾也算
    assert doc.symbol_at(0, 0) is None
    assert doc.symbol_at(1, 5).kind == "use"


def test_apply_ranges_keeps_emoji_comment_untouched():
    text = "use foo # foo 不应被改 🎉🎉 中文"
    out = apply_ranges(text, [(0, 4, 7)], "bar", expect="foo")
    assert out == "use bar # foo 不应被改 🎉🎉 中文"


def test_apply_ranges_across_lines_with_unicode_comments():
    text = "# 🎉🎉🎉 头部注释\ndef foo\nuse foo # 注释🎉 中文"
    out = apply_ranges(text, [(1, 4, 7), (2, 4, 7)], "baz", expect="foo")
    assert out == "# 🎉🎉🎉 头部注释\ndef baz\nuse baz # 注释🎉 中文"


def test_apply_ranges_expect_mismatch_raises():
    with pytest.raises(ValueError):
        apply_ranges("use foo", [(0, 4, 7)], "bar", expect="nope")

"""小语言解析器。

语言规则（按行解析）：
  - ``def 名字``  声明符号
  - ``use 名字``  引用符号
  - 第一个 ``#`` 到行尾为注释，可含任意 Unicode
  - 符号名为 ASCII：[A-Za-z_][A-Za-z0-9_]*

协议中所有位置均为 0 起始行号 + UTF-16 代码单元列（与 Monaco / LSP 一致），
end 列不含在内。Python 字符串按码点索引，而 JS/Monaco 按 UTF-16 代码单元索引，
emoji 等 astral 字符占 2 个 UTF-16 单元，因此这里集中做换算。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_STMT_RE = re.compile(
    r"^\s*(?P<kw>def|use)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*$"
)
KEYWORDS = {"def", "use"}


def utf16_len(s: str) -> int:
    """字符串的 UTF-16 代码单元长度。"""
    n = 0
    for ch in s:
        n += 2 if ord(ch) > 0xFFFF else 1
    return n


def utf16_col_to_index(s: str, col: int) -> int:
    """把 UTF-16 列换算成 Python 字符下标；列不允许落在代理对中间。"""
    if col < 0:
        raise ValueError("列不能为负")
    units = 0
    for i, ch in enumerate(s):
        if units == col:
            return i
        units += 2 if ord(ch) > 0xFFFF else 1
        if units > col:
            raise ValueError(f"列 {col} 落在代理对中间")
    if units == col:
        return len(s)
    raise ValueError(f"列 {col} 超出范围（行 UTF-16 长度 {units}）")


@dataclass
class Symbol:
    kind: str  # "def" | "use"
    name: str
    line: int
    start: int  # UTF-16 列，含
    end: int    # UTF-16 列，不含


@dataclass
class Comment:
    line: int
    start: int  # “#” 的 UTF-16 列
    text: str   # “#” 之后到行尾的内容


@dataclass
class ParseError:
    line: int
    start: int
    end: int
    message: str


@dataclass
class ParsedDoc:
    symbols: list[Symbol] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)
    errors: list[ParseError] = field(default_factory=list)

    @property
    def decls(self) -> list[Symbol]:
        return [s for s in self.symbols if s.kind == "def"]

    @property
    def refs(self) -> list[Symbol]:
        return [s for s in self.symbols if s.kind == "use"]

    def symbol_at(self, line: int, col: int) -> Symbol | None:
        for s in self.symbols:
            if s.line == line and s.start <= col <= s.end:
                return s
        return None


def parse_document(text: str) -> ParsedDoc:
    doc = ParsedDoc()
    for lineno, line in enumerate(text.split("\n")):
        code, sep, comment = line.partition("#")
        if sep:
            doc.comments.append(Comment(line=lineno, start=utf16_len(code), text=comment))
        if not code.strip():
            continue
        m = _STMT_RE.match(code)
        if m:
            name = m.group("name")
            start = utf16_len(code[: m.start("name")])
            doc.symbols.append(
                Symbol(kind=m.group("kw"), name=name, line=lineno,
                       start=start, end=start + utf16_len(name))
            )
        else:
            lead = len(code) - len(code.lstrip())
            doc.errors.append(
                ParseError(line=lineno,
                           start=utf16_len(code[:lead]),
                           end=utf16_len(code.rstrip()),
                           message="无法识别的语句")
            )
    return doc


def apply_ranges(
    text: str,
    ranges: list[tuple[int, int, int]],
    replacement: str,
    expect: str | None = None,
) -> str:
    """把若干 (line, start_utf16, end_utf16) 范围替换为 replacement。

    同一行内按起点倒序替换，避免前面的替换使后面的列失效。
    expect 不为 None 时校验被替换的原文，不匹配则抛 ValueError。
    """
    lines = text.split("\n")
    by_line: dict[int, list[tuple[int, int]]] = {}
    for line, s, e in ranges:
        if line < 0 or line >= len(lines):
            raise ValueError(f"行 {line} 超出范围")
        by_line.setdefault(line, []).append((s, e))
    for lineno, spans in by_line.items():
        line = lines[lineno]
        for s, e in sorted(spans, reverse=True):
            i = utf16_col_to_index(line, s)
            j = utf16_col_to_index(line, e)
            if expect is not None and line[i:j] != expect:
                raise ValueError(
                    f"第 {lineno} 行 {s}-{e} 处内容为 {line[i:j]!r}，期望 {expect!r}"
                )
            line = line[:i] + replacement + line[j:]
        lines[lineno] = line
    return "\n".join(lines)

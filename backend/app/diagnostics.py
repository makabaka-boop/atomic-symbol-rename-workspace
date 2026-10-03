"""诊断计算与异步分发。

每条诊断都绑定计算时的文档修订；从快照到真正发送之间文档可能又变了，
因此发送前用 filter_fresh 再校验一次，过期结果直接丢弃——
异步旧诊断不能覆盖新文本。
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from .lang import ParsedDoc, parse_document

ERROR = "error"
WARNING = "warning"


def compute_diagnostics(parsed: ParsedDoc, declared: set[str]) -> list[dict]:
    """单文档诊断：语法错误、文档内重复声明、引用了工作区未声明的符号。"""
    out: list[dict] = []
    for e in parsed.errors:
        out.append({"line": e.line, "start": e.start, "end": e.end,
                    "severity": ERROR, "message": e.message})
    seen: set[str] = set()
    for d in parsed.decls:
        if d.name in seen:
            out.append({"line": d.line, "start": d.start, "end": d.end,
                        "severity": ERROR, "message": f"重复声明 '{d.name}'"})
        else:
            seen.add(d.name)
    for r in parsed.refs:
        if r.name not in declared:
            out.append({"line": r.line, "start": r.start, "end": r.end,
                        "severity": WARNING, "message": f"未定义的符号 '{r.name}'"})
    out.sort(key=lambda d: (d["line"], d["start"]))
    return out


def filter_fresh(entries: list[dict], current_revisions: dict[str, int]) -> list[dict]:
    """丢弃计算期间已经发生变化的文档条目。"""
    return [e for e in entries if current_revisions.get(e["doc_id"]) == e["revision"]]


class DiagnosticsService:
    def __init__(
        self,
        db,
        broadcast: Callable[[dict], Awaitable[None]],
        debounce: float = 0.05,
    ):
        self.db = db
        self._broadcast = broadcast
        self.debounce = debounce
        self._task: asyncio.Task | None = None

    def collect(self) -> list[dict]:
        """对工作区快照计算诊断，并丢弃发送前已过期的条目。"""
        docs = self.db.all_documents()
        parsed = {d["id"]: parse_document(d["content"]) for d in docs}
        declared = {s.name for p in parsed.values() for s in p.decls}
        entries = [
            {"doc_id": d["id"], "revision": d["revision"],
             "diagnostics": compute_diagnostics(parsed[d["id"]], declared)}
            for d in docs
        ]
        current = {d["id"]: d["revision"] for d in self.db.all_documents()}
        return filter_fresh(entries, current)

    def schedule(self) -> None:
        """在一次提交的变更后调用；短时间内的多次变更合并为一次计算。"""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        await asyncio.sleep(self.debounce)
        await self._broadcast({"type": "diagnostics", "docs": self.collect()})

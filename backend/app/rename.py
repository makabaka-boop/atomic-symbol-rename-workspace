"""跨文件重命名。

两阶段：
1. preview：定位符号，收集所有文档中的声明与引用范围，生成预览计划，
   记录每个相关文档的基准修订和工作区索引版本。
2. apply：在 SQLite 一次事务中校验并提交——任一相关文档已变化、
   出现了同名声明、或索引已失效，都整批拒绝（回滚），不能改到一半。
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

from .lang import KEYWORDS, NAME_RE, apply_ranges, parse_document

PLAN_TTL_SECONDS = 300


class RenameError(Exception):
    def __init__(self, reason: str, message: str, status: int = 409):
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.status = status


@dataclass
class RenamePlan:
    id: str
    old_name: str
    new_name: str
    index_version: int
    edits: dict  # doc_id -> {"base_revision": int, "ranges": [{line, start, end}]}
    created_at: float = field(default_factory=time.time)
    applied: bool = False

    def expired(self) -> bool:
        return time.time() - self.created_at > PLAN_TTL_SECONDS

    def to_dict(self) -> dict:
        return {
            "plan_id": self.id,
            "old_name": self.old_name,
            "new_name": self.new_name,
            "index_version": self.index_version,
            "edits": [
                {"doc_id": doc_id, "base_revision": e["base_revision"],
                 "ranges": e["ranges"]}
                for doc_id, e in sorted(self.edits.items())
            ],
        }


class RenameService:
    def __init__(self, db):
        self.db = db
        self._plans: dict[str, RenamePlan] = {}
        self._lock = threading.Lock()

    # ---- 阶段一：预览 ----

    def preview(self, doc_id: str, line: int, col: int, new_name: str) -> RenamePlan:
        doc = self.db.get_document(doc_id)
        if doc is None:
            raise RenameError("DOC_NOT_FOUND", f"文档 {doc_id} 不存在", 404)
        sym = parse_document(doc["content"]).symbol_at(line, col)
        if sym is None:
            raise RenameError("NO_SYMBOL", "该位置没有可重命名的符号", 400)
        old_name = sym.name
        if not NAME_RE.fullmatch(new_name) or new_name in KEYWORDS:
            raise RenameError("BAD_NAME", "新名字必须是 ASCII 标识符且不能是关键字", 400)
        if new_name == old_name:
            raise RenameError("BAD_NAME", "新名字与原名字相同", 400)

        docs = self.db.all_documents()
        edits: dict[str, dict] = {}
        for d in docs:
            parsed = parse_document(d["content"])
            if any(s.kind == "def" and s.name == new_name for s in parsed.symbols):
                raise RenameError("NAME_CONFLICT", f"已存在同名声明 '{new_name}'")
            ranges = [
                {"line": s.line, "start": s.start, "end": s.end}
                for s in parsed.symbols
                if s.name == old_name
            ]
            if ranges:
                edits[d["id"]] = {"base_revision": d["revision"], "ranges": ranges}

        plan = RenamePlan(
            id=uuid.uuid4().hex,
            old_name=old_name,
            new_name=new_name,
            index_version=self.db.workspace_revision(),
            edits=edits,
        )
        with self._lock:
            self._plans[plan.id] = plan
        return plan

    # ---- 阶段二：确认应用（单事务，全有或全无）----

    def apply(self, plan_id: str) -> dict:
        with self._lock:
            plan = self._plans.get(plan_id)
        if plan is None:
            raise RenameError("PLAN_NOT_FOUND", "预览计划不存在", 404)
        if plan.applied:
            raise RenameError("PLAN_USED", "该预览计划已被应用")
        if plan.expired():
            raise RenameError("PLAN_EXPIRED", "预览计划已过期")

        with self.db.transaction():
            docs = {d["id"]: d for d in self.db.all_documents()}

            # 1) 任一相关文档在预览期间被修改
            for doc_id, edit in plan.edits.items():
                row = docs.get(doc_id)
                if row is None or row["revision"] != edit["base_revision"]:
                    raise RenameError(
                        "DOC_CHANGED", f"文档 {doc_id} 已变化，整批未应用"
                    )

            # 2) 预览之后出现了同名声明（按当前内容重新检查）
            for d in docs.values():
                parsed = parse_document(d["content"])
                if any(s.kind == "def" and s.name == plan.new_name
                       for s in parsed.symbols):
                    raise RenameError(
                        "NAME_CONFLICT",
                        f"已存在同名声明 '{plan.new_name}'，整批未应用",
                    )

            # 3) 索引已失效：预览后工作区有任何其它变化
            if self.db.workspace_revision() != plan.index_version:
                raise RenameError("INDEX_STALE", "工作区索引已失效，整批未应用")

            # 4) 全部校验通过，应用所有编辑
            changes = []
            for doc_id, edit in sorted(plan.edits.items()):
                row = docs[doc_id]
                ranges = [(r["line"], r["start"], r["end"]) for r in edit["ranges"]]
                try:
                    new_content = apply_ranges(
                        row["content"], ranges, plan.new_name, expect=plan.old_name
                    )
                except ValueError as exc:
                    raise RenameError(
                        "TEXT_MISMATCH", f"文档 {doc_id} 内容不匹配：{exc}，整批未应用"
                    )
                new_rev = self.db._update_document(doc_id, new_content)
                changes.append({"doc_id": doc_id, "revision": new_rev})
            ws_rev = self.db._bump_workspace()

        with self._lock:
            plan.applied = True
        return {"workspace_revision": ws_rev, "changes": changes}

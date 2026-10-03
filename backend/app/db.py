"""SQLite 存储层。

单连接 + 可重入锁；所有多步写操作都包在 transaction() 里，
要么整批提交，要么整批回滚，绝不改到一半。

文档 revision 随每次提交递增；workspace revision 在任何文档
增删改时递增，同时充当“索引版本”——预览计划记录它，应用时
不一致即视为索引已失效。
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
  id TEXT PRIMARY KEY,
  content TEXT NOT NULL,
  revision INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace(
  id INTEGER PRIMARY KEY CHECK(id = 1),
  revision INTEGER NOT NULL
);
INSERT OR IGNORE INTO workspace(id, revision) VALUES(1, 0);
"""

MAX_DOCUMENTS = 20


class RevisionMismatch(Exception):
    def __init__(self, current: int):
        super().__init__(f"当前修订为 {current}")
        self.current = current


class TooManyDocuments(Exception):
    pass


class Database:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA)

    @contextmanager
    def transaction(self):
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            self.conn.execute("COMMIT")

    # ---- 查询 ----

    def list_documents(self) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT id, revision FROM documents ORDER BY id"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_document(self, doc_id: str) -> dict | None:
        with self.lock:
            r = self.conn.execute(
                "SELECT id, content, revision FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()
            return dict(r) if r else None

    def all_documents(self) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT id, content, revision FROM documents ORDER BY id"
            ).fetchall()
            return [dict(r) for r in rows]

    def workspace_revision(self) -> int:
        with self.lock:
            return self.conn.execute(
                "SELECT revision FROM workspace WHERE id = 1"
            ).fetchone()[0]

    # ---- 原始写操作（必须在 transaction() 内调用）----

    def _bump_workspace(self) -> int:
        self.conn.execute("UPDATE workspace SET revision = revision + 1 WHERE id = 1")
        return self.workspace_revision()

    def _update_document(self, doc_id: str, content: str) -> int:
        self.conn.execute(
            "UPDATE documents SET content = ?, revision = revision + 1 WHERE id = ?",
            (content, doc_id),
        )
        return self.conn.execute(
            "SELECT revision FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()[0]

    # ---- 高层写操作（各自一个事务）----

    def create_document(self, doc_id: str, content: str) -> tuple[int, int]:
        with self.transaction():
            count = self.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            if count >= MAX_DOCUMENTS:
                raise TooManyDocuments()
            self.conn.execute(
                "INSERT INTO documents(id, content, revision) VALUES(?, ?, 1)",
                (doc_id, content),
            )
            ws = self._bump_workspace()
            return 1, ws

    def update_document(
        self, doc_id: str, content: str, base_revision: int
    ) -> tuple[int, int]:
        with self.transaction():
            row = self.get_document(doc_id)
            if row is None:
                raise KeyError(doc_id)
            if row["revision"] != base_revision:
                raise RevisionMismatch(row["revision"])
            rev = self._update_document(doc_id, content)
            ws = self._bump_workspace()
            return rev, ws

    def delete_document(self, doc_id: str) -> int:
        with self.transaction():
            cur = self.conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
            if cur.rowcount == 0:
                raise KeyError(doc_id)
            return self._bump_workspace()

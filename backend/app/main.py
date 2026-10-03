"""FastAPI 入口：文档 CRUD、重命名预览/应用、WebSocket 工作区通知。

协议约定：
  - 位置为 0 起始行号 + UTF-16 代码单元列（前端转成 Monaco 的 1 起始）。
  - 诊断消息绑定文档修订，客户端只在修订一致且无本地未提交修改时应用。
  - 任何提交都会递增工作区修订并广播 workspace_revision。
"""
from __future__ import annotations

import sqlite3

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .db import Database, RevisionMismatch, TooManyDocuments
from .diagnostics import DiagnosticsService
from .rename import RenameError, RenameService


class ConnectionManager:
    def __init__(self) -> None:
        self._sockets: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._sockets.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._sockets.discard(ws)

    async def broadcast(self, message: dict) -> None:
        dead = []
        for ws in list(self._sockets):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._sockets.discard(ws)


def err(status: int, reason: str, message: str, **extra) -> HTTPException:
    detail = {"reason": reason, "message": message}
    detail.update(extra)
    return HTTPException(status_code=status, detail=detail)


class CreateDoc(BaseModel):
    id: str
    content: str = ""


class SaveDoc(BaseModel):
    content: str
    base_revision: int


class PreviewReq(BaseModel):
    doc_id: str
    line: int
    col: int
    new_name: str


class ApplyReq(BaseModel):
    plan_id: str


def create_app(db_path: str = ":memory:", diag_debounce: float = 0.05) -> FastAPI:
    app = FastAPI(title="mini-lang workspace")
    db = Database(db_path)
    manager = ConnectionManager()
    diag = DiagnosticsService(db, manager.broadcast, debounce=diag_debounce)
    renames = RenameService(db)
    app.state.db = db
    app.state.diag = diag
    app.state.renames = renames

    async def after_change(changes: list[dict]) -> None:
        await manager.broadcast({
            "type": "workspace_revision",
            "revision": db.workspace_revision(),
            "changes": changes,
        })
        diag.schedule()

    @app.get("/api/documents")
    def list_documents() -> dict:
        return {"documents": db.list_documents(),
                "workspace_revision": db.workspace_revision()}

    @app.post("/api/documents", status_code=201)
    async def create_document(req: CreateDoc) -> dict:
        if not req.id or len(req.id) > 64 or "/" in req.id:
            raise err(400, "BAD_ID", "文档 id 非法")
        try:
            rev, _ = db.create_document(req.id, req.content)
        except TooManyDocuments:
            raise err(400, "TOO_MANY_DOCS", "工作区最多 20 个文档")
        except sqlite3.IntegrityError:
            raise err(409, "DOC_EXISTS", f"文档 {req.id} 已存在")
        await after_change([{"doc_id": req.id, "revision": rev}])
        return {"id": req.id, "revision": rev}

    @app.get("/api/documents/{doc_id}")
    def get_document(doc_id: str) -> dict:
        doc = db.get_document(doc_id)
        if doc is None:
            raise err(404, "DOC_NOT_FOUND", f"文档 {doc_id} 不存在")
        return doc

    @app.put("/api/documents/{doc_id}")
    async def save_document(doc_id: str, req: SaveDoc) -> dict:
        try:
            rev, _ = db.update_document(doc_id, req.content, req.base_revision)
        except KeyError:
            raise err(404, "DOC_NOT_FOUND", f"文档 {doc_id} 不存在")
        except RevisionMismatch as m:
            raise err(409, "DOC_CHANGED", "文档已被他人修改",
                      current_revision=m.current)
        await after_change([{"doc_id": doc_id, "revision": rev}])
        return {"id": doc_id, "revision": rev}

    @app.delete("/api/documents/{doc_id}")
    async def delete_document(doc_id: str) -> dict:
        try:
            db.delete_document(doc_id)
        except KeyError:
            raise err(404, "DOC_NOT_FOUND", f"文档 {doc_id} 不存在")
        await after_change([{"doc_id": doc_id, "deleted": True}])
        return {"id": doc_id}

    @app.post("/api/rename/preview")
    def rename_preview(req: PreviewReq) -> dict:
        try:
            plan = renames.preview(req.doc_id, req.line, req.col, req.new_name)
        except RenameError as e:
            raise err(e.status, e.reason, e.message)
        return plan.to_dict()

    @app.post("/api/rename/apply")
    async def rename_apply(req: ApplyReq) -> dict:
        try:
            result = renames.apply(req.plan_id)
        except RenameError as e:
            raise err(e.status, e.reason, e.message)
        await after_change(result["changes"])
        return result

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        await manager.connect(websocket)
        await websocket.send_json({
            "type": "hello",
            "workspace_revision": db.workspace_revision(),
            "documents": db.list_documents(),
        })
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(websocket)

    return app


app = create_app()

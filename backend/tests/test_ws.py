from fastapi.testclient import TestClient

from app.main import create_app
from conftest import make_doc


def test_two_sessions_receive_workspace_revision_notifications(client):
    make_doc(client, "a", "def foo")
    with client.websocket_connect("/ws") as ws1, \
            client.websocket_connect("/ws") as ws2:
        h1, h2 = ws1.receive_json(), ws2.receive_json()
        assert h1["type"] == h2["type"] == "hello"
        assert h1["workspace_revision"] == 1

        r = client.put("/api/documents/a",
                       json={"content": "def foo\nuse foo", "base_revision": 1})
        assert r.status_code == 200

        m1, m2 = ws1.receive_json(), ws2.receive_json()
        assert m1["type"] == m2["type"] == "workspace_revision"
        assert m1["revision"] == m2["revision"] == 2
        assert m1["changes"] == [{"doc_id": "a", "revision": 2}]

        # 两个会话随后都收到绑定新修订的诊断
        d1, d2 = ws1.receive_json(), ws2.receive_json()
        assert d1["type"] == d2["type"] == "diagnostics"
        entry = {d["doc_id"]: d for d in d1["docs"]}["a"]
        assert entry["revision"] == 2


def test_diagnostics_never_overwrite_newer_text():
    # 较大的防抖窗口 + 连续两次提交：只应收到一条诊断，且绑定最新修订。
    app = create_app(":memory:", diag_debounce=0.05)
    with TestClient(app) as client:
        make_doc(client, "a", "def foo")
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "hello"
            client.put("/api/documents/a",
                       json={"content": "def foo\nuse foo", "base_revision": 1})
            client.put("/api/documents/a",
                       json={"content": "def foo\nuse foo\nuse bar",
                             "base_revision": 2})
            messages = [ws.receive_json() for _ in range(3)]

        revisions = [m["revision"] for m in messages
                     if m["type"] == "workspace_revision"]
        assert revisions == [2, 3]
        diags = [m for m in messages if m["type"] == "diagnostics"]
        assert len(diags) == 1
        entry = {d["doc_id"]: d for d in diags[0]["docs"]}["a"]
        assert entry["revision"] == 3
        assert any("bar" in d["message"] for d in entry["diagnostics"])


def test_hello_contains_documents_and_revision(client):
    make_doc(client, "a", "def foo")
    make_doc(client, "b", "use foo")
    with client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        assert hello["workspace_revision"] == 2
        assert hello["documents"] == [
            {"id": "a", "revision": 1},
            {"id": "b", "revision": 1},
        ]


def test_rename_apply_broadcasts_to_all_sessions(client):
    from conftest import preview

    make_doc(client, "a", "def foo")
    make_doc(client, "b", "use foo")
    with client.websocket_connect("/ws") as ws1, \
            client.websocket_connect("/ws") as ws2:
        ws1.receive_json()
        ws2.receive_json()
        plan = preview(client, "a", 0, 5, "bar")
        r = client.post("/api/rename/apply", json={"plan_id": plan["plan_id"]})
        assert r.status_code == 200

        m1, m2 = ws1.receive_json(), ws2.receive_json()
        assert m1["type"] == m2["type"] == "workspace_revision"
        assert m1["changes"] == [
            {"doc_id": "a", "revision": 2},
            {"doc_id": "b", "revision": 2},
        ]

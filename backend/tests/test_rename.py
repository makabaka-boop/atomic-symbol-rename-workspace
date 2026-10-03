from conftest import make_doc, preview


def test_preview_contains_ranges_base_revisions_and_index_version(client):
    make_doc(client, "a", "def foo\nuse foo # 注释🎉")
    make_doc(client, "b", "# 🎉 中文\nuse foo")
    plan = preview(client, "a", 0, 5, "bar")

    assert plan["old_name"] == "foo"
    assert plan["new_name"] == "bar"
    assert plan["index_version"] == 2          # 两次创建 → 工作区修订 2
    edits = {e["doc_id"]: e for e in plan["edits"]}
    assert edits["a"]["base_revision"] == 1
    assert edits["a"]["ranges"] == [
        {"line": 0, "start": 4, "end": 7},
        {"line": 1, "start": 4, "end": 7},
    ]
    assert edits["b"]["base_revision"] == 1
    assert edits["b"]["ranges"] == [{"line": 1, "start": 4, "end": 7}]


def test_apply_success_commits_all_docs_and_keeps_comments(client):
    make_doc(client, "a", "def foo\nuse foo # foo 在注释里 🎉中文")
    make_doc(client, "b", "# 🎉\nuse foo")
    plan = preview(client, "a", 0, 5, "bar")

    r = client.post("/api/rename/apply", json={"plan_id": plan["plan_id"]})
    assert r.status_code == 200, r.text

    a = client.get("/api/documents/a").json()
    b = client.get("/api/documents/b").json()
    # 代码里的 foo 全部改名，注释里的 foo 与 emoji/中文原样保留
    assert a["content"] == "def bar\nuse bar # foo 在注释里 🎉中文"
    assert b["content"] == "# 🎉\nuse bar"
    assert a["revision"] == 2 and b["revision"] == 2

    # 计划只能应用一次
    r2 = client.post("/api/rename/apply", json={"plan_id": plan["plan_id"]})
    assert r2.status_code == 409
    assert r2.json()["detail"]["reason"] == "PLAN_USED"


def test_concurrent_edit_during_preview_rejects_whole_batch(client):
    make_doc(client, "a", "def foo")
    make_doc(client, "b", "use foo")
    make_doc(client, "c", "use foo # 🎉")
    plan = preview(client, "a", 0, 5, "bar")

    # 预览期间，另一个会话并发修改了相关文档 b
    r = client.put("/api/documents/b",
                   json={"content": "use foo\nuse other", "base_revision": 1})
    assert r.status_code == 200

    r = client.post("/api/rename/apply", json={"plan_id": plan["plan_id"]})
    assert r.status_code == 409
    assert r.json()["detail"]["reason"] == "DOC_CHANGED"

    # 全批不变：a、c 保持原内容与原修订，b 只保留并发编辑的结果
    a = client.get("/api/documents/a").json()
    b = client.get("/api/documents/b").json()
    c = client.get("/api/documents/c").json()
    assert (a["content"], a["revision"]) == ("def foo", 1)
    assert (b["content"], b["revision"]) == ("use foo\nuse other", 2)
    assert (c["content"], c["revision"]) == ("use foo # 🎉", 1)


def test_same_name_declaration_appearing_after_preview_rejects(client):
    make_doc(client, "a", "def foo\nuse foo")
    plan = preview(client, "a", 0, 4, "bar")
    make_doc(client, "b", "def bar")   # 预览后出现同名声明

    r = client.post("/api/rename/apply", json={"plan_id": plan["plan_id"]})
    assert r.status_code == 409
    assert r.json()["detail"]["reason"] == "NAME_CONFLICT"
    assert client.get("/api/documents/a").json()["content"] == "def foo\nuse foo"


def test_stale_index_rejects_and_leaves_everything_unchanged(client):
    make_doc(client, "a", "def foo")
    make_doc(client, "u", "use unrelated")
    plan = preview(client, "a", 0, 4, "bar")

    # 与计划无关的文档变化也会让索引失效
    client.put("/api/documents/u",
               json={"content": "use unrelated\nuse more", "base_revision": 1})

    r = client.post("/api/rename/apply", json={"plan_id": plan["plan_id"]})
    assert r.status_code == 409
    assert r.json()["detail"]["reason"] == "INDEX_STALE"
    a = client.get("/api/documents/a").json()
    assert (a["content"], a["revision"]) == ("def foo", 1)


def test_preview_rejects_existing_declaration(client):
    make_doc(client, "a", "def foo")
    make_doc(client, "b", "def bar")
    r = client.post("/api/rename/preview",
                    json={"doc_id": "a", "line": 0, "col": 4, "new_name": "bar"})
    assert r.status_code == 409
    assert r.json()["detail"]["reason"] == "NAME_CONFLICT"


def test_preview_validation(client):
    make_doc(client, "a", "def foo")
    for bad in ("中文", "def", "foo", "has space", ""):
        r = client.post("/api/rename/preview",
                        json={"doc_id": "a", "line": 0, "col": 4, "new_name": bad})
        assert r.status_code == 400, bad
    # 光标不在符号上
    r = client.post("/api/rename/preview",
                    json={"doc_id": "a", "line": 0, "col": 0, "new_name": "x"})
    assert r.status_code == 400
    assert r.json()["detail"]["reason"] == "NO_SYMBOL"


def test_rename_does_not_touch_name_inside_comment(client):
    make_doc(client, "a", "use foo # use foo 也是注释 🎉")
    plan = preview(client, "a", 0, 5, "bar")
    assert plan["edits"][0]["ranges"] == [{"line": 0, "start": 4, "end": 7}]
    client.post("/api/rename/apply", json={"plan_id": plan["plan_id"]})
    assert client.get("/api/documents/a").json()["content"] == \
        "use bar # use foo 也是注释 🎉"


def test_save_with_stale_base_revision_conflicts(client):
    make_doc(client, "a", "def foo")
    r = client.put("/api/documents/a",
                   json={"content": "def x", "base_revision": 99})
    assert r.status_code == 409
    assert r.json()["detail"]["reason"] == "DOC_CHANGED"
    assert r.json()["detail"]["current_revision"] == 1


def test_document_limit_20(client):
    for i in range(20):
        make_doc(client, f"doc{i:02d}", "def a")
    r = client.post("/api/documents", json={"id": "one-too-many", "content": ""})
    assert r.status_code == 400
    assert r.json()["detail"]["reason"] == "TOO_MANY_DOCS"

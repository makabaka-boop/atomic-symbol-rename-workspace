import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture()
def client():
    app = create_app(":memory:", diag_debounce=0.01)
    with TestClient(app) as c:
        yield c


def make_doc(client: TestClient, doc_id: str, content: str) -> int:
    r = client.post("/api/documents", json={"id": doc_id, "content": content})
    assert r.status_code == 201, r.text
    return r.json()["revision"]


def preview(client: TestClient, doc_id: str, line: int, col: int, new_name: str) -> dict:
    r = client.post("/api/rename/preview",
                    json={"doc_id": doc_id, "line": line, "col": col,
                          "new_name": new_name})
    assert r.status_code == 200, r.text
    return r.json()

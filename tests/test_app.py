import pytest
import requests

from minman import __version__
from minman.app import app
from minman.storage import configure


@pytest.fixture
def client(tmp_path):
    configure(tmp_path)
    return app.test_client()


class FakeResponse:
    status_code, reason, content, text = 200, "OK", b'{"ok": true}', '{"ok": true}'
    headers = {"Content-Type": "application/json"}

    def json(self):
        return {"ok": True}

    def iter_content(self, chunk_size):
        yield self.content

    def close(self):
        pass


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr(requests, "request", fake_request)
    return calls


def test_rejects_foreign_host(client):
    assert client.get("/api/tree", headers={"Host": "evil.example"}).status_code == 403


def test_rejects_foreign_origin(client, sent):
    response = client.post("/api/send", json={"url": "https://example.com"}, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert client.delete("/api/folders/x", headers={"Origin": "http://localhost:3326"}).status_code == 403
    assert not sent


def test_allows_same_origin(client, sent):
    origin = "http://localhost"
    response = client.post("/api/send", json={"url": "https://example.com"}, headers={"Origin": origin})
    assert response.status_code == 200


def test_rejects_large_request(client):
    response = client.post("/api/send", data=b"x" * (50 * 1024 * 1024 + 1), content_type="application/json")
    assert response.status_code == 413
    assert "too large" in response.get_json()["error"]


def test_rejects_large_response(client, monkeypatch):
    from minman import http_client
    monkeypatch.setattr(http_client, "MAX_RESPONSE_BYTES", 5)
    monkeypatch.setattr(requests, "request", lambda *args, **kwargs: FakeResponse())
    response = client.post("/api/send", json={"url": "https://example.com"})
    assert response.status_code == 400
    assert "larger than" in response.get_json()["error"]


def test_serves_ui(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"<html" in response.data.lower()
    response.close()


def test_about(client):
    assert client.get("/api/about").get_json() == {"version": __version__}


def test_rejects_unsafe_names(client):
    assert client.post("/api/folders", json={"name": ".."}).status_code == 400
    assert client.get("/api/requests/../secret").status_code == 400


def test_request_lifecycle(client):
    assert client.post("/api/folders", json={"name": "Users"}).status_code == 201
    assert client.post("/api/folders", json={"name": "Admin", "parent": "Users"}).status_code == 201
    saved = client.put("/api/requests/Users/List", json={
        "method": "GET", "url": "{{base_url}}/users",
        "form": [{"key": "f", "type": "file", "filename": "a.txt", "content": "c2VjcmV0"}],
    }).get_json()
    assert saved["name"] == "List"
    assert saved["form"] == [{"key": "f", "type": "file", "filename": "a.txt"}]
    assert client.get("/api/tree").get_json() == {
        "Users": [{"name": "List", "method": "GET"}], "Users/Admin": [],
    }

    assert client.post("/api/responses/Users/List", json={"status": 200, "body": "x"}).get_json()["version"] == 1
    assert client.post("/api/responses/Users/List", json={"status": 201}).get_json()["version"] == 2
    assert client.get("/api/responses/Users/List?version=2").get_json()["response"]["status"] == 201

    assert client.post("/api/rename", json={"kind": "request", "folder": "Users", "name": "List", "new_name": "All"}).get_json() == {"folder": "Users", "name": "All"}
    assert [item["version"] for item in client.get("/api/responses/Users/All").get_json()] == [1, 2]
    assert client.post("/api/duplicate", json={"kind": "request", "folder": "Users", "name": "All"}).get_json()["name"] == "All copy"
    assert client.post("/api/move", json={"folder": "Users", "name": "All", "target": "Users/Admin"}).status_code == 200
    assert len(client.get("/api/responses/Users/Admin/All").get_json()) == 2

    assert client.post("/api/rename", json={"kind": "folder", "folder": "Users", "new_name": "People"}).get_json() == {"folder": "People"}
    assert client.delete("/api/requests/People/Admin/All").status_code == 200
    assert client.get("/api/responses/People/Admin/All").get_json() == []
    assert client.delete("/api/folders/People").status_code == 200
    assert client.get("/api/tree").get_json() == {}


def test_variables(client, tmp_path):
    assert client.get("/api/variables").get_json() == {"active": "Default", "environments": {"Default": {}}}
    saved = client.put("/api/variables", json={"active": "Dev", "environments": {"Dev": {"{{base_url}}": "http://dev"}}}).get_json()
    assert saved == {"active": "Dev", "environments": {"Dev": {"base_url": "http://dev"}}}
    assert client.put("/api/variables", json={"active": "Missing", "environments": {"Dev": {}}}).status_code == 400

    (tmp_path / "variables.json").write_text('{"base_url": "http://old"}', encoding="utf-8")
    assert client.get("/api/variables").get_json() == {"active": "Default", "environments": {"Default": {"base_url": "http://old"}}}


def test_parse_curl(client):
    data = client.post("/api/parse-curl", json={
        "curl": "curl -X put https://api.example.com/x -H 'Authorization_token: abc' -H 'Accept: application/json' -d '{\"a\": 1}'",
    }).get_json()
    assert data == {
        "method": "PUT", "url": "https://api.example.com/x",
        "headers": [{"key": "Accept", "value": "application/json"}], "params": [],
        "body": '{"a": 1}', "body_type": "json", "token": "abc",
    }
    assert client.post("/api/parse-curl", json={"curl": "curl -H 'A: b'"}).status_code == 400


def test_send(client, sent):
    client.put("/api/variables", json={"active": "Dev", "environments": {"Dev": {"base_url": "https://api.example.com", "id": 7}}})
    response = client.post("/api/send", json={
        "method": "post", "url": "{{base_url}}/items",
        "params": [{"key": "id", "value": "{{id}}"}, {"key": "off", "value": "1", "enabled": False}],
        "headers": [{"key": "Authorization", "value": "old"}],
        "auth": {"type": "bearer", "token": "Bearer secret"},
        "body_type": "json", "body": '{"name": "x"}',
    })
    assert response.status_code == 200
    assert response.get_json()["body"] == '{\n  "ok": true\n}'
    call = sent[0]
    assert (call["method"], call["url"], call["params"]) == ("POST", "https://api.example.com/items", [("id", "7")])
    assert call["headers"] == {"Authorization": "Bearer secret", "Content-Type": "application/json"}
    assert call["data"] == b'{"name": "x"}'


def test_send_auth_and_forms(client, sent):
    client.post("/api/send", json={"url": "https://a.test", "token": "Bearer jwt"})
    assert sent[-1]["headers"] == {"Authorization_token": "jwt"}
    client.post("/api/send", json={"url": "https://a.test", "auth": {"type": "basic", "username": "u", "password": "p"}})
    assert sent[-1]["headers"] == {"Authorization": "Basic dTpw"}
    client.post("/api/send", json={"url": "https://a.test", "auth": {"type": "apikey", "key": "k", "value": "v", "in": "query"}})
    assert sent[-1]["params"] == [("k", "v")]
    client.post("/api/send", json={"method": "POST", "url": "https://a.test", "body_type": "formdata", "form": [
        {"key": "a", "value": "1"}, {"key": "f", "type": "file", "filename": "x.txt", "content": "aGk="},
    ]})
    assert sent[-1]["data"] == [("a", "1")]
    assert sent[-1]["files"] == [("f", ("x.txt", b"hi"))]


@pytest.mark.parametrize("payload, message", [
    ({"method": "TRACE", "url": "https://a.test"}, "Unsupported method."),
    ({"url": "{{missing}}/x"}, "The URL contains an unknown variable: missing. Add it in Environment variables."),
    ({"url": "ftp://a.test"}, "Enter a valid http or https URL."),
    ({"url": "https://a.test", "headers": [{"key": "X", "value": "{{nope}}"}]},
     "Unknown variable in headers, params or auth: nope. Add it in Environment variables or untick that row."),
    ({"url": "https://a.test", "body_type": "formdata", "form": [{"key": "f", "type": "file"}]},
     'Choose the file again for form field "f".'),
])
def test_send_validation(client, sent, payload, message):
    response = client.post("/api/send", json=payload)
    assert (response.status_code, response.get_json()) == (400, {"error": message})
    assert sent == []


def test_send_invalid_file_content(client, sent):
    response = client.post("/api/send", json={"url": "https://a.test", "body_type": "formdata", "form": [
        {"key": "f", "type": "file", "content": "a"},
    ]})
    assert response.status_code == 400
    assert response.get_json()["error"].startswith("Invalid request data:")


def test_send_network_errors(client, monkeypatch):
    def fail(*args, **kwargs):
        raise requests.exceptions.SSLError("bad cert")

    monkeypatch.setattr(requests, "request", fail)
    response = client.post("/api/send", json={"url": "https://a.test"})
    assert response.status_code == 502
    assert response.get_json()["error"].startswith("SSL error:")

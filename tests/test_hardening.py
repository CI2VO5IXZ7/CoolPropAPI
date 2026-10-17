from typing import Optional

import pytest
from starlette.requests import Request

from main import MAX_BATCH_POINTS, _client_ip


@pytest.mark.parametrize(
    "params, needle",
    [
        ({"T": 25, "R": 0.5, "P": 49999}, "参数 P"),
        ({"T": 25, "R": 0.5, "P": 110001}, "参数 P"),
        ({"T": -100.1, "R": 0.5}, "参数 T"),
        ({"T": 200.1, "R": 0.5}, "参数 T"),
        ({"Tdb": 250, "R": 0.5}, "参数 Tdb"),
        ({"T": 25, "Twb": 201}, "参数 Twb"),
        ({"T": 25, "Tdp": -101}, "参数 Tdp"),
        ({"T": 25, "R": 1.01}, "参数 R"),
        ({"T": 25, "R": -0.01}, "参数 R"),
        ({"T": 25, "W": 0.11}, "参数 W"),
        ({"T": 25, "W": -0.001}, "参数 W"),
        ({"T": 25, "H": 501}, "参数 H"),
        ({"T": 25, "Hda": -101}, "参数 Hda"),
    ],
)
def test_out_of_range_400(client, params, needle):
    resp = client.get("/ha", params=params)
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert needle in detail and "超出允许范围" in detail


@pytest.mark.parametrize(
    "params",
    [
        {"T": 25, "R": 0.5, "P": 50000},
        {"T": 25, "R": 0.5, "P": 110000},
        {"T": 25, "R": 1},
        {"T": 25, "R": 0},
        {"T": 25, "W": 0.0},
    ],
)
def test_range_boundaries_ok(client, params):
    assert client.get("/ha", params=params).status_code == 200


@pytest.mark.parametrize(
    "a, b",
    [("T", "Tdb"), ("B", "Twb"), ("D", "Tdp"), ("H", "Hda"), ("V", "Vda"), ("S", "Sda"), ("Y", "psi_w")],
)
def test_synonym_conflict_400(client, a, b):
    resp = client.get("/ha", params={a: 10, b: 10})
    assert resp.status_code == 400
    assert "同义参数" in resp.json()["detail"]


def test_batch_limit(client):
    ok = client.post("/ha/batch", json={"points": [{"T": 25, "R": 0.5}] * MAX_BATCH_POINTS})
    assert ok.status_code == 200
    assert ok.json()["count"] == MAX_BATCH_POINTS

    too_many = client.post("/ha/batch", json={"points": [{"T": 25, "R": 0.5}] * (MAX_BATCH_POINTS + 1)})
    assert too_many.status_code == 400
    assert "超过上限" in too_many.json()["detail"]


def test_batch_point_errors_are_per_point(client):
    body = client.post(
        "/ha/batch",
        json={"points": [{"T": 25, "R": 0.5}, {"T": 25, "R": 2}, {"T": 25, "Tdb": 25}]},
    ).json()
    assert [r["status"] for r in body["results"]] == ["success", "error", "error"]
    assert "超出允许范围" in body["results"][1]["error"]
    assert "同义参数" in body["results"][2]["error"]


def test_batch_malformed_body_400(client):
    resp = client.post("/ha/batch", json={"points": [{"T": "abc"}]})
    assert resp.status_code == 400
    assert "请求参数格式错误" in resp.json()["detail"]


def test_cors_methods(client):
    headers = {"Origin": "https://example.com", "Access-Control-Request-Method": "GET"}
    resp = client.options("/ha", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "*"
    allowed = resp.headers["access-control-allow-methods"]
    assert "GET" in allowed and "POST" in allowed and "DELETE" not in allowed

    bad = client.options("/ha", headers={**headers, "Access-Control-Request-Method": "DELETE"})
    assert bad.status_code == 400


def test_rate_limit_429(client):
    for _ in range(60):
        assert client.get("/ha/keys").status_code == 200
    resp = client.get("/ha/keys")
    assert resp.status_code == 429
    assert "请求过于频繁" in resp.json()["detail"]
    # 健康检查不计入限流
    assert client.get("/health").status_code == 200


def test_rate_limit_shared_across_routes(client):
    for _ in range(30):
        assert client.get("/ha/keys").status_code == 200
    for _ in range(30):
        assert client.get("/ha", params={"T": 25, "R": 0.5}).status_code == 200
    assert client.get("/ha", params={"T": 25, "R": 0.5}).status_code == 429
    assert client.post("/ha/batch", json={"points": [{"T": 25, "R": 0.5}]}).status_code == 429


def _request(host: str, forwarded: Optional[str] = None) -> Request:
    headers = []
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode("latin-1")))
    scope = {
        "type": "http",
        "asgi": {"spec_version": "2.3", "version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/ha/keys",
        "raw_path": b"/ha/keys",
        "query_string": b"",
        "headers": headers,
        "client": (host, 50000),
        "server": ("test", 80),
    }
    return Request(scope)


def test_client_ip_ignores_forwarded_header_by_default(monkeypatch):
    monkeypatch.delenv("TRUST_PROXY", raising=False)
    monkeypatch.delenv("TRUST_PROXY_HOPS", raising=False)
    assert _client_ip(_request("10.1.1.1", "203.0.113.9, 198.51.100.9")) == "10.1.1.1"
    assert _client_ip(_request("10.1.1.1")) == "10.1.1.1"


@pytest.mark.parametrize("value", ["0", "2", "true", "yes", "on"])
def test_trust_proxy_enables_only_for_literal_one(monkeypatch, value):
    monkeypatch.setenv("TRUST_PROXY", value)
    monkeypatch.delenv("TRUST_PROXY_HOPS", raising=False)
    # 两个地址，避免把「TRUST_PROXY=2」误当成 2 跳时仍然碰巧落到直连地址。
    assert _client_ip(_request("10.1.1.1", "203.0.113.9, 198.51.100.9")) == "10.1.1.1"


def test_client_ip_trust_proxy_uses_rightmost(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY", "1")
    monkeypatch.delenv("TRUST_PROXY_HOPS", raising=False)
    assert _client_ip(_request("10.0.0.1", "203.0.113.9")) == "203.0.113.9"
    assert _client_ip(_request("10.0.0.1", "203.0.113.9, 198.51.100.9")) == "198.51.100.9"
    assert _client_ip(_request("10.0.0.1", "203.0.113.9,,198.51.100.9")) == "198.51.100.9"
    assert _client_ip(_request("10.0.0.1")) == "10.0.0.1"
    assert _client_ip(_request("10.0.0.1", "   ")) == "10.0.0.1"


def test_client_ip_hops_count_from_the_right(monkeypatch):
    monkeypatch.delenv("TRUST_PROXY", raising=False)
    monkeypatch.setenv("TRUST_PROXY_HOPS", "2")
    # 跳数大于等于 1 即启用，不必再设 TRUST_PROXY。右起第 2 个是客户端。
    assert _client_ip(_request("10.0.0.1", "192.0.2.1, 203.0.113.7, 198.51.100.8")) == "203.0.113.7"
    # 地址个数少于跳数时不采用最左侧（客户端可伪造），回退直连地址。
    assert _client_ip(_request("10.0.0.1", "203.0.113.7")) == "10.0.0.1"


def test_invalid_hops_falls_back_to_trust_proxy_flag(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY", "1")
    monkeypatch.setenv("TRUST_PROXY_HOPS", "nope")
    assert _client_ip(_request("10.0.0.1", "203.0.113.5, 198.51.100.2")) == "198.51.100.2"


def test_trust_proxy_hops_zero_falls_back_to_trust_proxy(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY", "1")
    monkeypatch.setenv("TRUST_PROXY_HOPS", "0")
    assert _client_ip(_request("10.0.0.1", "203.0.113.5, 198.51.100.2")) == "198.51.100.2"


def test_forged_xff_cannot_bypass_rate_limit(client, monkeypatch):
    monkeypatch.delenv("TRUST_PROXY", raising=False)
    monkeypatch.delenv("TRUST_PROXY_HOPS", raising=False)
    for i in range(60):
        resp = client.get("/ha/keys", headers={"X-Forwarded-For": f"203.0.113.{i}"})
        assert resp.status_code == 200, resp.text
    assert client.get("/ha/keys", headers={"X-Forwarded-For": "198.51.100.20"}).status_code == 429
    assert client.get("/ha/keys", headers={"X-Forwarded-For": "203.0.113.1, 198.51.100.8"}).status_code == 429
    assert client.get("/ha/keys").status_code == 429


def test_trust_proxy_rate_limit_follows_rightmost_header(client, monkeypatch):
    monkeypatch.delenv("TRUST_PROXY_HOPS", raising=False)
    monkeypatch.setenv("TRUST_PROXY", "1")
    for _ in range(60):
        assert client.get("/ha/keys", headers={"X-Forwarded-For": "203.0.113.1"}).status_code == 200
    assert client.get("/ha/keys", headers={"X-Forwarded-For": "203.0.113.1"}).status_code == 429
    # 左侧伪造地址被忽略，最右侧不同则是另一个限流桶。
    assert client.get("/ha/keys", headers={"X-Forwarded-For": "203.0.113.1, 198.51.100.8"}).status_code == 200
    # 最右侧仍是已耗尽的地址，即使左侧换成别的值。
    assert client.get("/ha/keys", headers={"X-Forwarded-For": "198.51.100.9, 203.0.113.1"}).status_code == 429
    assert client.get("/ha/keys", headers={"X-Forwarded-For": "203.0.113.2"}).status_code == 200
    # 没有转发头时回到直连地址，不占用上面的桶。
    assert client.get("/ha/keys").status_code == 200


def test_trust_proxy_hops_rate_limit_uses_nth_from_right(client, monkeypatch):
    monkeypatch.delenv("TRUST_PROXY", raising=False)
    monkeypatch.setenv("TRUST_PROXY_HOPS", "2")
    for _ in range(60):
        resp = client.get("/ha/keys", headers={"X-Forwarded-For": "198.51.100.1, 203.0.113.10, 10.0.0.1"})
        assert resp.status_code == 200, resp.text
    # 从右数第 2 个不变；最左伪造值和最右代理地址都变了，仍是同一桶。
    same = client.get("/ha/keys", headers={"X-Forwarded-For": "198.51.100.99, 203.0.113.10, 10.0.0.2"})
    assert same.status_code == 429
    other = client.get("/ha/keys", headers={"X-Forwarded-For": "198.51.100.1, 203.0.113.11, 10.0.0.1"})
    assert other.status_code == 200
    # 只有 1 个地址，不足 2 跳：忽略该头，按直连地址另计。
    assert client.get("/ha/keys", headers={"X-Forwarded-For": "203.0.113.10"}).status_code == 200

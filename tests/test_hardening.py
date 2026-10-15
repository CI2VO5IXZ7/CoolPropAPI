import pytest

from main import MAX_BATCH_POINTS


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


def test_rate_limit_per_forwarded_ip(client):
    for _ in range(60):
        client.get("/ha/keys", headers={"X-Forwarded-For": "203.0.113.1"})
    assert client.get("/ha/keys", headers={"X-Forwarded-For": "203.0.113.1"}).status_code == 429
    assert client.get("/ha/keys", headers={"X-Forwarded-For": "203.0.113.2, 10.0.0.1"}).status_code == 200

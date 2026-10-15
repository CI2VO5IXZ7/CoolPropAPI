def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_keys(client):
    body = client.get("/ha/keys").json()
    assert body["pressure_key"] == "P"
    assert "T" in body["state_keys"]


def test_home(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_invalid_key(client):
    resp = client.get("/ha", params={"T": 25, "XYZ": 1})
    assert resp.status_code == 400
    assert "无效的属性代码" in resp.json()["detail"]


def test_non_numeric(client):
    resp = client.get("/ha", params={"T": "abc", "R": 0.5})
    assert resp.status_code == 400
    assert "不是有效的数字" in resp.json()["detail"]


def test_wrong_param_count(client):
    resp = client.get("/ha", params={"T": 25})
    assert resp.status_code == 400
    assert "2 个状态参数" in resp.json()["detail"]


def test_explicit_pressure(client):
    body = client.get("/ha", params={"T": 25, "R": 0.5, "P": 80000}).json()
    assert body["pressure"] == {"P": 80000.0, "default": False}

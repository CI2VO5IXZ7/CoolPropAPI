"""黄金值回归：期望值取自 CoolProp 7.2.0 实测，升级依赖后不得修改。"""

import pytest

REL_TOL = 1e-6

GOLDEN = {
    (25, 0.5): {"W": 0.009925739296161223, "H": 50.42345039075701, "Twb": 17.883486810309023, "Tdp": 13.866886648880495, "V": 0.8577882434265997, "S": 180.75676473200795},
    (30, 0.6): {"W": 0.016116408413589262, "H": 71.36522098702095, "Twb": 23.81040128784639, "Tdp": 21.391445279330924, "V": 0.8807292564000726, "S": 252.20738086321992},
    (0, 0.8): {"W": 0.003028336875167161, "H": 7.570863741089517, "Twb": -1.1584279806063478, "Tdp": -2.68283413116734, "V": 0.7770936058534716, "S": 29.430690305106257},
    (-10, 0.5): {"W": 0.0008020647721298145, "H": -8.065627243316223, "Twb": -11.644847395670297, "Tdp": -17.582811644183806, "V": 0.745880308412683, "S": -29.2740126819394},
    (40, 0.3): {"W": 0.013970603149971507, "H": 76.21407694001775, "Twb": 25.088842265474796, "Tdp": 19.13529211117344, "V": 0.9068118401450853, "S": 267.02482331921783},
    (35, 0.95): {"W": 0.03481920758981407, "H": 124.48762666833004, "Twb": 34.240271973479025, "Tdp": 34.076371011418416, "V": 0.9214155483666348, "S": 428.5536023346277},
}


@pytest.mark.parametrize("point", list(GOLDEN), ids=[f"T{t}_R{r}" for t, r in GOLDEN])
def test_ha_golden(client, point):
    t, r = point
    resp = client.get("/ha", params={"T": t, "R": r})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pressure"] == {"P": 101325.0, "default": True}
    state = body["state"]
    for key, expected in GOLDEN[point].items():
        assert state[key] == pytest.approx(expected, rel=REL_TOL), key


def test_batch_matches_single(client):
    points = [{"T": t, "R": r} for t, r in GOLDEN]
    resp = client.post("/ha/batch", json={"points": points})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == len(points)
    for item, point in zip(body["results"], GOLDEN):
        assert item["status"] == "success"
        for key, expected in GOLDEN[point].items():
            assert item["state"][key] == pytest.approx(expected, rel=REL_TOL), key

from fastapi.testclient import TestClient


def test_health_meta_and_capabilities(client: TestClient) -> None:
    health = client.get("/api/health")
    assert health.json() == {"status": "ok"}
    assert health.headers["Cache-Control"] == "no-store"
    meta = client.get("/api/meta")
    assert meta.json() == {
        "total": 466368,
        "from": "2021-01-01",
        "to": "2026-04-30",
    }
    assert meta.headers["Cache-Control"] == "public, max-age=3600"
    capabilities = client.get("/api/capabilities").json()
    assert capabilities["chat"] is False
    assert capabilities["graph_version"] == "lpe-agent-v1"


def test_transactions_modes(client: TestClient) -> None:
    clusters = client.get("/api/transactions", params={"bbox": "-0.3,51.4,0.1,51.7", "zoom": 11})
    assert clusters.status_code == 200
    assert clusters.json()["mode"] == "clusters"
    assert clusters.headers["Cache-Control"] == "public, max-age=3600"
    points = client.get("/api/transactions", params={"bbox": "-0.3,51.4,0.1,51.7", "zoom": 12})
    assert points.status_code == 200
    assert points.json()["points"][0]["postcode"] == "SW11 4NB"


def test_invalid_bbox_and_history(client: TestClient) -> None:
    response = client.get("/api/transactions", params={"bbox": "bad", "zoom": 12})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"
    history = client.get("/api/postcode/sw114nb/history")
    assert history.status_code == 200
    assert history.json()["postcode"] == "SW11 4NB"

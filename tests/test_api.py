import sqlite3

from fastapi.testclient import TestClient

from server.config import Settings
from server.main import create_app


class NeverConnect:
    async def create_conversation(self, kind):
        raise AssertionError("An unconfigured app must not call Azure.")

    async def respond(self, *args):
        raise AssertionError("An unconfigured app must not call Azure.")

    async def close(self):
        pass


def test_unconfigured_chat_and_authoring_are_honest_but_local_features_work(tmp_path):
    settings = Settings(database_path=tmp_path / "memory.sqlite3")
    with TestClient(create_app(settings, NeverConnect())) as client:
        status = client.get("/api/status").json()
        assert status["configured"] is False
        assert status["connection"] == "not_configured"
        assert status["published_skills"] == 3
        response = client.get("/api/runtime/skills?query=software")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        skill = response.json()["skills"][0]
        assert "guidance" not in skill
        assert client.get(f"/api/runtime/skills/{skill['id']}").json()["guidance"]
        response = client.post("/api/chat", json={"message": "Who approves this?"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "FOUNDRY_NOT_CONFIGURED"
        assert "az login" in response.json()["error"]["message"]
        assert "answer" not in response.json()
        intake = client.post("/api/intakes", json={
            "title": "Expert workshop",
            "notes": "At shift change, document the current incident and its next owner.",
        }).json()
        response = client.post(f"/api/intakes/{intake['id']}/organize")
        assert response.status_code == 503
        assert client.get(f"/api/intakes/{intake['id']}").json()["status"] == "saved"
    with TestClient(create_app(settings, NeverConnect())) as restarted:
        assert restarted.get(f"/api/intakes/{intake['id']}").json()["notes"] == intake["notes"]


def test_validation_storage_errors_and_conflicts_are_visible(tmp_path, monkeypatch):
    app = create_app(Settings(database_path=tmp_path / "memory.sqlite3"), NeverConnect())
    with TestClient(app) as client:
        assert client.post("/api/skills", json={"name": "x"}).status_code == 422
        assert client.get("/api/runtime/skills?limit=999").status_code == 422
        skill = client.get("/api/skills/incident-response").json()
        edited = {key: skill[key] for key in ("name", "description", "category", "guidance")}
        response = client.put(f"/api/skills/{skill['id']}", json={**edited, "expected_version": 1})
        assert response.status_code == 200
        assert client.put(f"/api/skills/{skill['id']}", json={**edited, "expected_version": 1}).status_code == 409
        assert client.get("/api/runtime/skills/deleted").status_code == 404
        assert client.post("/api/skills", headers={"Origin": "https://not-local.example"}, json=edited).status_code == 403

        def broken_storage(*args, **kwargs):
            raise sqlite3.OperationalError("test disk failure")

        monkeypatch.setattr(app.state.store, "discover", broken_storage)
        response = client.get("/api/runtime/skills")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "STORAGE_ERROR"


def test_malformed_endpoint_does_not_disable_local_features(tmp_path):
    settings = Settings(
        project_endpoint="https://[invalid/api/projects/test",
        model_deployment="test-deployment",
        database_path=tmp_path / "memory.sqlite3",
    )
    with TestClient(create_app(settings, NeverConnect())) as client:
        response = client.get("/api/status")
        assert response.status_code == 200
        assert response.json()["configured"] is False
        assert "HTTPS Azure project URL" in response.json()["problems"][0]
        assert client.get("/api/runtime/skills").json()["total"] == 3
        assert client.post("/api/chat", json={"message": "Hello"}).status_code == 503

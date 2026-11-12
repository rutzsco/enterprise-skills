import json
from io import BytesIO
from zipfile import ZipFile

import httpx
import pytest
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import McpError

from server.config import Settings
from server.main import create_app
from server.models import SkillInput
from test_api import NeverConnect


@pytest.mark.asyncio
async def test_real_mcp_initialization_discovery_read_freshness_and_draft_isolation(tmp_path):
    app = create_app(Settings(database_path=tmp_path / "registry.sqlite3"), NeverConnect())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
            async with streamable_http_client("http://testserver/mcp", http_client=http) as (read, write, _):
                async with ClientSession(read, write) as session:
                    initialized = await session.initialize()
                    assert initialized.capabilities.resources is not None
                    assert initialized.capabilities.tools is None
                    listed = await session.list_resources()
                    assert str(listed.resources[0].uri) == "skill://index.json"
                    index = json.loads((await session.read_resource("skill://index.json")).contents[0].text)
                    assert all("guidance" not in item and "references" not in item for item in index["skills"])
                    uri = "skill://incident-response/SKILL.md"
                    original = (await session.read_resource(uri)).contents[0].text
                    skill = app.state.store.get_skill("incident-response")
                    fields = skill.model_dump(include=set(SkillInput.model_fields))
                    fields["guidance"] = "Notify the commander after confirming a shared outage."
                    draft = app.state.store.manual_draft(SkillInput(**fields), skill.id, 1)
                    assert (await session.read_resource(uri)).contents[0].text == original
                    app.state.store.approve_proposal(draft["id"], 1)
                    updated = (await session.read_resource(uri)).contents[0].text
                    assert "version: \"2\"" in updated and fields["guidance"] in updated
                    historical = (await session.read_resource("skill://incident-response/versions/1/SKILL.md")).contents[0].text
                    assert historical == original
                    for invalid in ("skill://incident-response/scripts/run.py", "skill://incident-response/references/../secret.md",
                                    f"skill://{draft['id']}/SKILL.md"):
                        with pytest.raises(McpError):
                            await session.read_resource(invalid)


def test_http_authoring_export_and_retirement_require_review(tmp_path):
    with TestClient(create_app(Settings(database_path=tmp_path / "registry.sqlite3"), NeverConnect())) as client:
        body = {"name": "New policy", "description": "A deliberately synthetic example policy.",
                "category": "General", "guidance": "Confirm applicability before using this synthetic policy."}
        response = client.post("/api/skills", json=body)
        assert response.status_code == 202
        draft = response.json()
        assert client.get("/api/runtime/skills?query=New%20policy").json()["total"] == 0
        approved = client.post(f"/api/proposals/{draft['id']}/approve", json={"expected_revision": 1}).json()
        skill_id = approved["skill"]["id"]
        archive = client.get(f"/api/skills/{skill_id}/package")
        with ZipFile(BytesIO(archive.content)) as package:
            assert package.read(f"{skill_id}/SKILL.md").decode().startswith("---\nname:")
        retirement = client.delete(f"/api/skills/{skill_id}?expected_version=1").json()
        assert retirement["action"] == "retire"
        assert client.get(f"/api/runtime/skills/{skill_id}").status_code == 200
        client.post(f"/api/proposals/{retirement['id']}/approve", json={"expected_revision": 1})
        assert client.get(f"/api/runtime/skills/{skill_id}").status_code == 404
        assert client.get(f"/api/skills/{skill_id}/versions/1").status_code == 200

import json
from types import SimpleNamespace

import httpx
import pytest
from agent_framework.foundry import RawFoundryAgentChatClient
from openai import AsyncOpenAI

from server.foundry import FoundryService
from server.models import SkillEdit, SkillInput


def response_body(output, number):
    return {
        "id": f"resp_{number}", "object": "response", "created_at": 1,
        "model": "test-deployment", "status": "completed", "output": output,
        "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
        "error": None, "incomplete_details": None, "instructions": None,
        "metadata": {}, "temperature": 1, "top_p": 1,
    }


@pytest.mark.asyncio
async def test_real_framework_serializes_agent_reference_conversation_and_matching_tool_outputs():
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            output = [{
                "type": "function_call", "id": "fc_1", "call_id": "call_load",
                "name": "load_skill", "arguments": '{"skill_id":"software-purchasing"}',
                "status": "completed",
            }]
        else:
            output = [{
                "type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": "Using the loaded skill.", "annotations": []}],
            }]
        return httpx.Response(200, json=response_body(output, len(requests)))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http_client:
        openai = AsyncOpenAI(api_key="unit-test-placeholder", base_url="https://foundry.example/openai/v1", http_client=http_client, max_retries=0)
        project = SimpleNamespace(get_openai_client=lambda **kwargs: openai)
        async with RawFoundryAgentChatClient(project_client=project, agent_name="memory-test", agent_version="7") as client:
            first = await FoundryService.invoke(client, "conv_contract", [
                {"type": "message", "role": "user", "content": "Who approves this purchase?"}
            ])
            assert first.calls[0].call_id == "call_load"
            assert first.calls[0].arguments == '{"skill_id":"software-purchasing"}'
            second = await FoundryService.invoke(client, "conv_contract", [
                {"type": "function_call_output", "call_id": "call_load", "output": '{"id":"software-purchasing","version":2,"guidance":"Test rule"}'}
            ])
            assert second.text == "Using the loaded skill."
            assert not second.incomplete
    assert len(requests) == 2
    for body in requests:
        assert body["agent_reference"] == {"type": "agent_reference", "name": "memory-test", "version": "7"}
        assert body["conversation"] == "conv_contract"
        assert "model" not in body
        assert "tools" not in body
    assert "Test rule" not in json.dumps(requests[0])
    output = next(item for item in requests[1]["input"] if item["type"] == "function_call_output")
    assert output["call_id"] == "call_load"
    assert json.loads(output["output"])["version"] == 2


@pytest.mark.asyncio
async def test_registered_agents_are_reused_after_restart_without_embedding_skill_bodies(store, configured, monkeypatch):
    registry = {}
    created = []
    looked_up = []

    class Resource:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    class OpenAIStub(Resource):
        async def create(self):
            return SimpleNamespace(id="conv_registration_test")

        @property
        def conversations(self):
            return self

    class ProjectStub(Resource):
        def __init__(self, *, endpoint, credential):
            assert endpoint == configured.project_endpoint
            self.agents = self

        def get_openai_client(self, **kwargs):
            return OpenAIStub()

        async def create_version(self, *, agent_name, definition):
            agent = SimpleNamespace(name=agent_name, version=str(len(created) + 1))
            created.append(definition.as_dict())
            registry[(agent.name, agent.version)] = agent
            return agent

        async def get_version(self, *, agent_name, agent_version):
            looked_up.append((agent_name, agent_version))
            return registry[(agent_name, agent_version)]

    class FrameworkStub(Resource):
        def __init__(self, *, project_client, agent_name, agent_version, timeout):
            assert (agent_name, agent_version) in registry

    monkeypatch.setattr("server.foundry.DefaultAzureCredential", Resource)
    monkeypatch.setattr("server.foundry.AIProjectClient", ProjectStub)
    monkeypatch.setattr("server.foundry.RawFoundryAgentChatClient", FrameworkStub)
    first = FoundryService(configured, store)
    await first.create_conversation("chat")
    await first.create_conversation("chat")
    await first.create_conversation("author")
    await first.close()
    assert len(created) == 2
    assert created[0]["kind"] == created[1]["kind"] == "prompt"
    assert created[0]["model"] == configured.model_deployment
    assert [tool["name"] for tool in created[0]["tools"]] == ["discover_skills", "load_skill"]
    assert [tool["name"] for tool in created[1]["tools"]] == ["discover_skills", "load_skill", "propose_skills"]
    for metadata in store.discover()["skills"]:
        assert store.get_skill(metadata["id"]).guidance not in json.dumps(created)

    skill = store.get_skill("software-purchasing")
    store.update_skill(skill.id, SkillEdit(
        **{**skill.model_dump(include=set(SkillInput.model_fields)), "guidance": "New published guidance does not require redeploying an agent."},
        expected_version=1,
    ))
    restarted = FoundryService(configured, store)
    await restarted.create_conversation("chat")
    await restarted.close()
    assert len(created) == 2
    assert looked_up == [("enterprise-memory-demo-chat", "1")]

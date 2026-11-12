import asyncio
import copy
import json

import pytest

from server.errors import AppError
from server.models import NotesInput, SkillEdit, SkillInput
from server.runtime import AgentReply, FunctionCall, Runtime


class ScriptedService:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self.created = []

    async def create_conversation(self, kind):
        self.created.append(kind)
        return f"conv_test_{len(self.created)}"

    async def respond(self, kind, conversation_id, inputs):
        self.requests.append((kind, conversation_id, copy.deepcopy(inputs)))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    async def close(self):
        pass


def call(call_id, name, arguments):
    return AgentReply("", [FunctionCall(call_id, name, json.dumps(arguments))])


@pytest.mark.asyncio
async def test_chat_discovers_loads_and_returns_outputs_with_matching_ids_in_same_conversation(store, configured):
    service = ScriptedService([
        call("discover-1", "discover_skills", {"query": "purchasing"}),
        call("load-1", "load_skill", {"skill_id": "software-purchasing"}),
        AgentReply("Use the approvals in Software purchasing v1.", []),
        call("load-2", "load_skill", {"skill_id": "software-purchasing"}),
        AgentReply("The updated skill is Software purchasing v2.", []),
    ])
    runtime = Runtime(store, configured, service)
    first = await runtime.chat("Who approves $6,000 of software?", None)
    discover_output = service.requests[1][2][0]
    assert discover_output["type"] == "function_call_output"
    assert discover_output["call_id"] == "discover-1"
    assert "guidance" not in json.loads(discover_output["output"])["skills"][0]
    load_output = service.requests[2][2][0]
    assert load_output["call_id"] == "load-1"
    assert json.loads(load_output["output"])["version"] == 1
    assert [event["tool"] for event in first["events"]] == ["discover_skills", "load_skill"]
    current = store.get_skill("software-purchasing")
    new_guidance = "New synthetic guidance: Finance approval is needed for all software requests."
    store.update_skill(current.id, SkillEdit(
        **{**current.model_dump(include=set(SkillInput.model_fields)), "guidance": new_guidance},
        expected_version=1,
    ))
    second = await runtime.chat("What about after the policy update?", first["session_id"])
    assert service.created == ["chat"]
    assert {item[1] for item in service.requests} == {"conv_test_1"}
    assert json.loads(service.requests[-1][2][0]["output"])["guidance"] == new_guidance
    assert second["loaded_skills"][0]["version"] == 2


@pytest.mark.asyncio
async def test_malformed_unknown_and_missing_tool_calls_are_explicit_and_returned_together(store, configured):
    service = ScriptedService([
        AgentReply("", [
            FunctionCall("bad-json", "discover_skills", "{broken"),
            FunctionCall("bad-type", "load_skill", '{"skill_id": 123}'),
            FunctionCall("missing", "load_skill", '{"skill_id": "deleted"}'),
            FunctionCall("unknown", "delete_skill", "{}"),
        ]),
        AgentReply("Those tools could not supply the requested information.", []),
    ])
    result = await Runtime(store, configured, service).chat("Check these skills.", None)
    outputs = service.requests[1][2]
    assert [item["call_id"] for item in outputs] == ["bad-json", "bad-type", "missing", "unknown"]
    assert [json.loads(item["output"])["error"]["code"] for item in outputs] == [
        "INVALID_TOOL_ARGUMENTS", "INVALID_TOOL_ARGUMENTS", "SKILL_NOT_FOUND", "UNKNOWN_TOOL"
    ]
    assert all(event["status"] == "error" for event in result["events"])
    assert result["loaded_skills"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["rounds", "batch", "repeat"])
async def test_tool_execution_is_bounded_and_failed_sessions_are_not_reused(store, configured, mode):
    if mode == "rounds":
        replies = [call(f"call-{index}", "discover_skills", {}) for index in range(7)]
    elif mode == "batch":
        replies = [AgentReply("", [FunctionCall(str(index), "discover_skills", "{}") for index in range(13)])]
    else:
        replies = [call("same-id", "discover_skills", {})] * 2
    service = ScriptedService(replies)
    runtime = Runtime(store, configured, service)
    with pytest.raises(AppError) as error:
        await runtime.chat("Keep calling tools.", None)
    assert error.value.code in {"TOOL_LIMIT", "INVALID_TOOL_CALL"}
    assert error.value.reset_required
    assert len(service.requests) <= 6
    assert len(error.value.events) <= 6
    assert runtime.sessions == {}


@pytest.mark.asyncio
async def test_exact_twelve_call_budget_can_complete_without_truncating_outputs(store, configured):
    service = ScriptedService([
        AgentReply("", [FunctionCall(f"load-{index}", "load_skill", '{"skill_id":"incident-response"}') for index in range(12)]),
        AgentReply("The requested skill was loaded.", []),
    ])
    result = await Runtime(store, configured, service).chat("Check the skill.", None)
    assert len(result["events"]) == 12
    assert [item["call_id"] for item in service.requests[1][2]] == [f"load-{index}" for index in range(12)]
    assert result["answer"] == "The requested skill was loaded."


@pytest.mark.asyncio
async def test_service_errors_preserve_real_trace_without_fake_success(store, configured):
    service = ScriptedService([
        call("load", "load_skill", {"skill_id": "incident-response"}),
        RuntimeError("Simulated service failure; not a live Azure run."),
    ])
    with pytest.raises(AppError) as error:
        await Runtime(store, configured, service).chat("Help with an outage.", None)
    assert error.value.code == "FOUNDRY_ERROR"
    assert error.value.events[0]["tool"] == "load_skill"
    assert error.value.reset_required
    assert "No live result" in error.value.message


@pytest.mark.asyncio
async def test_turn_timeout_is_reported_as_error(store, configured, monkeypatch):
    class SlowService(ScriptedService):
        async def respond(self, *args):
            await asyncio.sleep(10)

    monkeypatch.setattr("server.runtime.TURN_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(AppError) as error:
        await Runtime(store, configured, SlowService([])).chat("Hello", None)
    assert error.value.code == "FOUNDRY_TIMEOUT"


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [AgentReply("", []), AgentReply("Partial result", [], incomplete=True)])
async def test_empty_and_incomplete_responses_are_not_presented_as_success(store, configured, reply):
    with pytest.raises(AppError):
        await Runtime(store, configured, ScriptedService([reply])).chat("Hello", None)


@pytest.mark.asyncio
async def test_authoring_inspects_existing_skill_and_creates_review_only_proposal(store, configured):
    notes = "For all software purchases, Finance approval is required regardless of price."
    intake = store.create_intake(NotesInput(title="Finance workshop", notes=notes))
    existing = store.get_skill("software-purchasing")
    candidate = {
        **existing.model_dump(include=set(SkillInput.model_fields)),
        "guidance": notes,
        "action": "update", "skill_id": existing.id, "base_version": 1,
        "rationale": "Update the approval route using the new Finance workshop notes.",
        "evidence": [notes], "missing_information": ["No approval SLA was supplied."],
        "rules": [{"rule": "Finance approval is required regardless of price.", "quotes": [notes]}],
    }
    service = ScriptedService([
        call("catalog", "discover_skills", {}),
        call("current", "load_skill", {"skill_id": existing.id}),
        call("proposal", "propose_skills", {"proposals": [candidate]}),
        AgentReply("One update is ready for human review.", []),
    ])
    result = await Runtime(store, configured, service).organize(intake["id"])
    assert service.created == ["author"]
    assert result["status"] == "ready"
    assert result["proposals"][0]["status"] == "pending"
    assert store.get_skill(existing.id).guidance == existing.guidance
    assert store.get_skill(existing.id).version == 1
    store.approve_proposal(result["proposals"][0]["id"], 1)
    assert store.get_skill(existing.id).guidance == notes
    assert store.get_skill(existing.id).version == 2


@pytest.mark.asyncio
async def test_authoring_cannot_fabricate_evidence_and_notes_survive_failure(store, configured):
    notes = "At shift change, the on-call engineer records open incidents and the next owner."
    intake = store.create_intake(NotesInput(title="Handover", notes=notes))
    candidate = {
        "name": "Shift handover", "description": "Handover procedure from expert notes.",
        "category": "Operations", "guidance": notes, "action": "create",
        "rationale": "Structure the handover procedure from the supplied notes.",
        "evidence": ["Invented quotation that the SME never supplied."],
    }
    service = ScriptedService([
        call("catalog", "discover_skills", {}),
        call("proposal", "propose_skills", {"proposals": [candidate]}),
        AgentReply("I could not produce a grounded proposal.", []),
    ])
    with pytest.raises(AppError) as error:
        await Runtime(store, configured, service).organize(intake["id"])
    assert error.value.code == "NO_PROPOSALS"
    assert json.loads(service.requests[-1][2][0]["output"])["error"]["code"] == "UNGROUNDED_EVIDENCE"
    assert store.get_intake(intake["id"])["notes"] == notes
    assert store.get_intake(intake["id"])["status"] == "failed"
    assert store.list_proposals() == []
    assert store.discover("handover")["total"] == 0

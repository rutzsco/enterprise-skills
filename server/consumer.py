"""Separate Agent Framework consumer; all skill reads go through MCP."""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import ValidationError
import yaml

from .config import ROOT, Settings
from .errors import AppError
from .foundry import FoundryService
from .mcp_service import resource_uri
from .models import DiscoverArguments, LoadArguments
from .runtime import MAX_ROUNDS, MAX_TOOL_CALLS, TURN_TIMEOUT_SECONDS
from .store import Store, now


async def text_resource(session, uri, trace):
    result = await session.read_resource(uri)
    if len(result.contents) != 1 or not hasattr(result.contents[0], "text"):
        raise AppError("MCP_CONTENT", "Expected exactly one text resource.", 502)
    text = result.contents[0].text
    trace.append({"uri": uri, "status": "success"})
    return text


async def answer(session, service, question, *, pin=None):
    trace, loaded, catalog = [], [], None
    conversation = await service.create_conversation("chat")
    inputs = [{"type": "message", "role": "user", "content": question}]
    call_count, call_ids = 0, set()
    for _ in range(MAX_ROUNDS):
        response = await service.respond("chat", conversation, inputs)
        if response.incomplete:
            raise AppError("INCOMPLETE_RESPONSE", "Consumer received an incomplete Foundry response.", 502)
        if not response.calls:
            if not response.text.strip() or not loaded:
                raise AppError("MISSING_SKILL_LOAD", "Consumer must produce a real answer after loading a skill through MCP.", 502)
            return {"answer": response.text, "conversation_id": conversation, "mcp_reads": trace, "loaded_skills": loaded}
        call_count += len(response.calls)
        if call_count > MAX_TOOL_CALLS:
            raise AppError("TOOL_LIMIT", "Consumer exceeded its tool budget.", 502)
        inputs = []
        for call in response.calls:
            if not call.call_id or call.call_id in call_ids:
                raise AppError("INVALID_TOOL_CALL", "Consumer received a duplicate/missing call ID.", 502)
            call_ids.add(call.call_id)
            try:
                arguments = json.loads(call.arguments) if isinstance(call.arguments, str) else call.arguments
                if call.name == "discover_skills":
                    args = DiscoverArguments.model_validate(arguments)
                    catalog = json.loads(await text_resource(session, "skill://index.json", trace))
                    terms = args.query.casefold().split()
                    matches = [item for item in catalog["skills"] if not terms or any(
                        term in f"{item['name']} {item['description']} {item['category']}".casefold() for term in terms)]
                    output = {"skills": matches[:100], "total": len(matches)}
                elif call.name == "load_skill":
                    args = LoadArguments.model_validate(arguments)
                    if catalog is None:
                        raise AppError("DISCOVERY_REQUIRED", "Discover the MCP index before loading.", 422)
                    item = next((item for item in catalog["skills"] if item["id"] == args.skill_id), None)
                    if item is None:
                        raise AppError("SKILL_NOT_FOUND", "That skill was not in the discovered index.", 404)
                    version = pin[1] if pin and pin[0] == args.skill_id else None
                    uri = resource_uri(args.skill_id, version=version)
                    content = await text_resource(session, uri, trace)
                    frontmatter, guidance = content.removeprefix("---\n").split("\n---\n", 1)
                    header = yaml.safe_load(frontmatter)
                    actual_version = int(header["metadata"]["version"])
                    output = {
                        "id": args.skill_id, "name": header["metadata"]["display-name"],
                        "version": actual_version, "guidance": guidance.strip(), "uri": uri,
                        "applicability": header["metadata"]["applicability"],
                    }
                    loaded.append({key: value for key, value in output.items() if key != "guidance"})
                else:
                    raise AppError("UNKNOWN_TOOL", "Consumer supports only read-only discovery and loading.", 422)
            except (ValidationError, json.JSONDecodeError) as error:
                output = {"error": {"code": "INVALID_ARGUMENTS", "message": str(error)}}
            except AppError as error:
                output = {"error": {"code": error.code, "message": error.message}}
            inputs.append({"type": "function_call_output", "call_id": call.call_id, "output": json.dumps(output)})
    raise AppError("TOOL_LIMIT", "Consumer exhausted its response-round budget.", 502)


async def run(args):
    load_dotenv(ROOT / ".env")
    settings = Settings.from_env()
    if settings.problems():
        raise ValueError(" ".join(settings.problems()))
    # Bindings only: this separate database never supplies skill content.
    bindings = Store(ROOT / "data" / "consumer-bindings.sqlite3")
    bindings.initialize()
    service = FoundryService(settings, bindings)
    try:
        async with streamable_http_client(args.endpoint) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                async with asyncio.timeout(TURN_TIMEOUT_SECONDS * 2):
                    if args.before_version:
                        if not args.skill_id:
                            raise ValueError("--skill-id is required for a pinned baseline.")
                        before = await answer(session, service, args.question, pin=(args.skill_id, args.before_version))
                        after = await answer(session, service, args.question)
                        if not any(item["id"] == args.skill_id and item["version"] == args.before_version for item in before["loaded_skills"]):
                            raise ValueError("The baseline did not load the requested skill release.")
                        if not any(item["id"] == args.skill_id and item["version"] != args.before_version for item in after["loaded_skills"]):
                            raise ValueError("Fresh discovery did not load a changed active release.")
                        result = {"before": before, "after": after}
                    else:
                        result = {"current": await answer(session, service, args.question)}
        result.update(id=str(uuid4()), at=now(), question=args.question, endpoint=args.endpoint,
                      model=settings.model_deployment, agent=service.identities.get("chat"),
                      note="Actual isolated runs; decision correctness requires reviewing the answers against the expected rule.")
        if args.expect_before and args.expect_before.casefold() not in result["before"]["answer"].casefold():
            raise ValueError("Baseline did not contain the expected decision phrase.")
        if args.expect_after and args.expect_after.casefold() not in result["after"]["answer"].casefold():
            raise ValueError("Updated answer did not contain the expected decision phrase.")
        path = Path(args.output) if args.output else ROOT / "data" / "comparisons" / f"{result['id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as output:
            json.dump(result, output, indent=2)
        print(json.dumps(result, indent=2))
    finally:
        await service.close()
        bindings.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000/mcp")
    parser.add_argument("--question", required=True)
    parser.add_argument("--skill-id")
    parser.add_argument("--before-version", type=int)
    parser.add_argument("--expect-before")
    parser.add_argument("--expect-after")
    parser.add_argument("--output", help="Create a new JSON evidence file; existing files are never overwritten.")
    args = parser.parse_args()
    if (args.expect_before or args.expect_after) and not args.before_version:
        parser.error("Decision assertions require --before-version.")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()

import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from time import monotonic
from typing import Literal, Protocol
from uuid import uuid4

from .config import Settings
from .errors import AppError
from .store import Store
from .tools import ToolDispatcher
import anyio


logger = logging.getLogger(__name__)
AgentKind = Literal["chat", "author"]
MAX_ROUNDS = 6
MAX_TOOL_CALLS = 12
TURN_TIMEOUT_SECONDS = 90
SESSION_TTL_SECONDS = 3600


@dataclass
class FunctionCall:
    call_id: str
    name: str
    arguments: str | dict | None


@dataclass
class AgentReply:
    text: str
    calls: list[FunctionCall]
    incomplete: bool = False


class AgentService(Protocol):
    async def create_conversation(self, kind: AgentKind) -> str: ...
    async def respond(self, kind: AgentKind, conversation_id: str, inputs: list[dict]) -> AgentReply: ...
    async def close(self) -> None: ...


@dataclass
class ChatSession:
    conversation_id: str
    touched: float
    busy: bool = False


class Runtime:
    def __init__(self, store: Store, settings: Settings, service: AgentService):
        self.store = store
        self.settings = settings
        self.service = service
        self.sessions: dict[str, ChatSession] = {}
        self.connection_state = "not_tested"

    def status(self) -> dict:
        problems = self.settings.problems()
        return {
            "configured": not problems,
            "provider": "Azure Foundry Agent Service",
            "framework": "Microsoft Agent Framework",
            "connection": "not_configured" if problems else self.connection_state,
            "problems": problems,
            "model_deployment": self.settings.model_deployment or None,
        }

    def require_configuration(self) -> None:
        problems = self.settings.problems()
        if problems:
            raise AppError(
                "FOUNDRY_NOT_CONFIGURED",
                " ".join(problems) + " Authenticate with Azure CLI (az login), then restart the server. Skills and saved notes work without Azure.",
                503,
            )

    async def _run(self, kind: AgentKind, conversation_id: str, message: str, tools: ToolDispatcher) -> str:
        inputs = [{"type": "message", "role": "user", "content": message}]
        seen_calls: set[str] = set()
        call_count = 0
        for _ in range(MAX_ROUNDS):
            reply = await self.service.respond(kind, conversation_id, inputs)
            if reply.incomplete:
                raise AppError("INCOMPLETE_RESPONSE", "Foundry returned an incomplete response. No final answer was accepted.", 502)
            if not reply.calls:
                if not reply.text.strip():
                    raise AppError("EMPTY_RESPONSE", "Foundry returned no answer. Check the deployment and server logs.", 502)
                return reply.text
            if call_count + len(reply.calls) > MAX_TOOL_CALLS:
                raise AppError("TOOL_LIMIT", "The agent exceeded the 12-call safety limit. Try a narrower request.", 502)
            inputs = []
            for call in reply.calls:
                if not call.call_id or call.call_id in seen_calls:
                    raise AppError("INVALID_TOOL_CALL", "Foundry repeated or omitted a tool call ID. The run was stopped.", 502)
                seen_calls.add(call.call_id)
                call_count += 1
                output = await anyio.to_thread.run_sync(tools.execute, call.call_id, call.name, call.arguments)
                inputs.append({"type": "function_call_output", "call_id": call.call_id, "output": output})
        raise AppError("TOOL_LIMIT", "The agent reached the 6-round safety limit without a final answer. Try a narrower request.", 502)

    def _service_error(self, error: Exception, tools: ToolDispatcher, *, reset_required: bool) -> AppError:
        if isinstance(error, AppError):
            return AppError(error.code, error.message, error.status, events=tools.events, reset_required=reset_required)
        self.connection_state = "failed"
        if isinstance(error, TimeoutError):
            message = "Foundry did not finish within 90 seconds. No final answer was accepted. Check connectivity or try a narrower request."
            code, status = "FOUNDRY_TIMEOUT", 504
        elif isinstance(error, sqlite3.Error):
            logger.exception("Local storage failed during an agent run", exc_info=error)
            message = "Local skill storage failed. Check disk permissions, disk space, and the server logs. No final result was accepted."
            code, status = "STORAGE_ERROR", 503
        else:
            logger.exception("Foundry operation failed", exc_info=error)
            message = "Foundry could not complete this request. Check az login, project permissions, the model deployment, and the server logs. No live result was produced."
            code, status = "FOUNDRY_ERROR", 502
        return AppError(code, message, status, events=tools.events, reset_required=reset_required)

    async def chat(self, message: str, session_id: str | None) -> dict:
        self.require_configuration()
        tools = ToolDispatcher(self.store)
        timestamp = monotonic()
        self.sessions = {
            key: value for key, value in self.sessions.items()
            if value.busy or timestamp - value.touched < SESSION_TTL_SECONDS
        }
        session = self.sessions.get(session_id) if session_id else None
        if session_id and session is None:
            raise AppError("SESSION_EXPIRED", "This conversation expired or the server restarted. Start a new conversation.", 409, reset_required=True)
        if session and session.busy:
            raise AppError("SESSION_BUSY", "A reply is already in progress for this conversation.", 409)
        if not session and len(self.sessions) >= 100:
            raise AppError("SESSION_LIMIT", "The local demo has 100 active conversations. Wait for old sessions to expire or restart it.", 429)
        if session:
            session.busy = True
        try:
            async with asyncio.timeout(TURN_TIMEOUT_SECONDS):
                if session is None:
                    conversation_id = await self.service.create_conversation("chat")
                    session = ChatSession(conversation_id, timestamp, busy=True)
                    session_id = str(uuid4())
                    self.sessions[session_id] = session
                answer = await self._run("chat", session.conversation_id, message, tools)
            self.connection_state = "verified"
            return {
                "session_id": session_id,
                "answer": answer,
                "events": tools.events,
                "loaded_skills": list(tools.loaded.values()),
            }
        except Exception as error:
            if session_id:
                self.sessions.pop(session_id, None)
            raise self._service_error(error, tools, reset_required=True) from error
        finally:
            if session:
                session.busy = False
                session.touched = monotonic()

    async def organize(self, intake_id: str) -> dict:
        self.require_configuration()
        intake = await anyio.to_thread.run_sync(self.store.claim_intake, intake_id)
        tools = ToolDispatcher(self.store, notes=intake["notes"])
        try:
            async with asyncio.timeout(TURN_TIMEOUT_SECONDS):
                conversation_id = await self.service.create_conversation("author")
                await self._run(
                    "author",
                    conversation_id,
                    f"Organize these SME notes into skill proposals for human review.\n"
                    f"Title: {intake['title']}\n\n<source_notes>\n{intake['notes']}\n</source_notes>",
                    tools,
                )
                if not tools.candidates:
                    raise AppError("NO_PROPOSALS", "The agent did not submit valid skill proposals. Your notes are saved; try making the rules more specific.", 502)
                result = await anyio.to_thread.run_sync(self.store.finish_intake, intake_id, tools.candidates, tools.events)
            self.connection_state = "verified"
            return result
        except Exception as error:
            failure = self._service_error(error, tools, reset_required=False)
            await anyio.to_thread.run_sync(self.store.fail_intake, intake_id, failure.message, tools.events)
            raise failure from error

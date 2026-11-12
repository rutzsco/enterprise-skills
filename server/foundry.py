import asyncio
import hashlib
import json
from collections.abc import Mapping
from contextlib import AsyncExitStack

from agent_framework import Content, Message
from agent_framework.foundry import RawFoundryAgentChatClient
from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import FunctionTool, PromptAgentDefinition
from azure.core.exceptions import ResourceNotFoundError
from azure.identity.aio import DefaultAzureCredential

from .config import Settings
from .runtime import AgentKind, AgentReply, FunctionCall
from .store import Store
from .tools import AUTHOR_INSTRUCTIONS, AUTHOR_TOOL, CHAT_INSTRUCTIONS, READ_TOOLS


class FoundryService:
    """Microsoft Agent Framework client for registered Foundry prompt agents."""

    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store
        self._stack = AsyncExitStack()
        self._lock = asyncio.Lock()
        self._project: AIProjectClient | None = None
        self._clients: dict[AgentKind, RawFoundryAgentChatClient] = {}
        self._openai = None

    async def _client(self, kind: AgentKind) -> RawFoundryAgentChatClient:
        async with self._lock:
            if kind in self._clients:
                return self._clients[kind]
            if self._project is None:
                async with AsyncExitStack() as startup:
                    credential = await startup.enter_async_context(DefaultAzureCredential())
                    project = await startup.enter_async_context(
                        AIProjectClient(endpoint=self.settings.project_endpoint, credential=credential)
                    )
                    openai = await startup.enter_async_context(
                        project.get_openai_client(max_retries=0, timeout=40)
                    )
                    self._stack.push_async_callback(startup.pop_all().aclose)
                    self._project = project
                    self._openai = openai
            schemas = READ_TOOLS + ([AUTHOR_TOOL] if kind == "author" else [])
            instructions = AUTHOR_INSTRUCTIONS if kind == "author" else CHAT_INSTRUCTIONS
            definition = PromptAgentDefinition(
                model=self.settings.model_deployment,
                instructions=instructions,
                tools=[FunctionTool(**schema, strict=False) for schema in schemas],
            )
            definition_key = hashlib.sha256(json.dumps({
                "endpoint": self.settings.project_endpoint,
                "prefix": self.settings.agent_prefix,
                "kind": kind,
                "model": self.settings.model_deployment,
                "instructions": instructions,
                "tools": schemas,
            }, sort_keys=True).encode()).hexdigest()
            binding = self.store.get_agent_binding(definition_key)
            agent = None
            if binding:
                try:
                    agent = await self._project.agents.get_version(
                        agent_name=binding["name"], agent_version=binding["version"]
                    )
                except ResourceNotFoundError:
                    # A user may remove the demo agent in Foundry between runs.
                    agent = None
            if agent is None:
                agent = await self._project.agents.create_version(
                    agent_name=f"{self.settings.agent_prefix}-{kind}",
                    definition=definition,
                )
                self.store.save_agent_binding(definition_key, agent.name, agent.version)
            client = RawFoundryAgentChatClient(
                project_client=self._project,
                agent_name=agent.name,
                agent_version=agent.version,
                timeout=40,
            )
            await self._stack.enter_async_context(client)
            self._clients[kind] = client
            return client

    async def create_conversation(self, kind: AgentKind) -> str:
        await self._client(kind)
        conversation = await self._openai.conversations.create()
        return conversation.id

    @staticmethod
    async def invoke(client: RawFoundryAgentChatClient, conversation_id: str, inputs: list[dict]) -> AgentReply:
        messages = []
        for item in inputs:
            if item["type"] == "message":
                messages.append(Message("user", [item["content"]]))
            elif item["type"] == "function_call_output":
                messages.append(Message("tool", [
                    Content.from_function_result(call_id=item["call_id"], result=item["output"])
                ]))
            else:
                raise ValueError(f"Unsupported local agent input type: {item['type']}")
        response = await client.get_response(
            messages,
            options={"conversation_id": conversation_id, "max_tokens": 5000},
        )
        calls = [
            FunctionCall(
                call_id=content.call_id or "",
                name=content.name or "",
                arguments=dict(content.arguments) if isinstance(content.arguments, Mapping) else content.arguments,
            )
            for message in response.messages
            for content in message.contents
            if content.type == "function_call" and not content.informational_only
        ]
        raw_status = getattr(response.raw_representation, "status", None)
        incomplete = (
            raw_status not in (None, "completed")
            or response.finish_reason in ("length", "content_filter")
            or any(content.type == "error" for message in response.messages for content in message.contents)
        )
        return AgentReply(text=response.text, calls=calls, incomplete=incomplete)

    async def respond(self, kind: AgentKind, conversation_id: str, inputs: list[dict]) -> AgentReply:
        return await self.invoke(await self._client(kind), conversation_id, inputs)

    async def close(self) -> None:
        await self._stack.aclose()

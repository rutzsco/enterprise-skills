import json
import re

import anyio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings

from .errors import AppError
from .packages import reference_path


def resource_uri(skill_id, path="SKILL.md", version=None):
    return f"skill://{skill_id}/" + (f"versions/{version}/" if version else "") + path


def read_uri(store, uri):
    if len(uri) > 512:
        raise AppError("INVALID_RESOURCE", "Skill resource URIs must not exceed 512 characters.", 422)
    if uri == "skill://index.json":
        catalog = store.discover(limit=100000)
        if catalog["total"] != len(catalog["skills"]):
            raise AppError("CATALOG_TOO_LARGE", "The catalog exceeds the MVP discovery budget.", 503)
        return json.dumps({
            "skills": [{**item, "uri": resource_uri(item["id"]), "version_uri": resource_uri(item["id"], version=item["version"])}
                       for item in catalog["skills"]],
            "total": catalog["total"],
        })
    match = re.fullmatch(r"skill://([a-z0-9]+(?:-[a-z0-9]+)*)/(?:versions/([1-9][0-9]*)/)?(.+)", uri)
    if not match:
        raise AppError("INVALID_RESOURCE", "Unknown skill resource URI.", 422)
    skill_id, version, path = match.groups()
    if path != "SKILL.md":
        reference_path(path)
    return store.read_resource(skill_id, path, int(version) if version else None)


def create_mcp(store, settings):
    server = Server("Enterprise Memory")

    @server.list_resources()
    async def resources():
        return [types.Resource(uri="skill://index.json", name="Approved skill index", mimeType="application/json",
                               description="Metadata only. Refresh before choosing current guidance.")]

    @server.list_resource_templates()
    async def templates():
        return [
            types.ResourceTemplate(uriTemplate="skill://{skill_id}/SKILL.md", name="Current approved skill", mimeType="text/markdown"),
            types.ResourceTemplate(uriTemplate="skill://{skill_id}/versions/{version}/SKILL.md", name="Explicit historical release", mimeType="text/markdown"),
            types.ResourceTemplate(uriTemplate="skill://{skill_id}/references/{filename}", name="Approved text reference", mimeType="text/plain"),
        ]

    @server.read_resource()
    async def read(uri):
        try:
            content = await anyio.to_thread.run_sync(read_uri, store, str(uri))
            mime_type = "application/json" if str(uri) == "skill://index.json" else "text/markdown" if str(uri).endswith(".md") else "text/plain"
            return [ReadResourceContents(content=content, mime_type=mime_type)]
        except AppError as error:
            raise ValueError(f"{error.code}: {error.message}") from error

    manager = StreamableHTTPSessionManager(
        server, stateless=True, json_response=True,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[item for host in settings.allowed_hosts for item in (host, f"{host}:*")],
            allowed_origins=[*settings.allowed_origins, *[
                f"{scheme}://{host}{port}" for host in settings.allowed_hosts
                for scheme in ("http", "https") for port in ("", ":*")
            ]],
        ),
    )

    class Endpoint:
        async def __call__(self, scope, receive, send):
            await manager.handle_request(scope, receive, send)

    # Parent host/origin middleware also applies to the MCP ASGI route.
    return Endpoint(), manager

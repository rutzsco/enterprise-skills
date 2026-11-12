import logging
import sqlite3
from contextlib import asynccontextmanager
from io import BytesIO
from zipfile import ZipFile

import anyio
from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.routing import Route

from .config import ROOT, Settings
from .errors import AppError
from .foundry import FoundryService
from .models import ChatInput, NotesInput, ProposalEdit, ReleaseAction, ReviewRequest, SkillEdit, SkillInput
from .mcp_service import create_mcp
from .packages import build_package
from .runtime import AgentService, Runtime
from .store import Store


logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, service: AgentService | None = None) -> FastAPI:
    if settings is None:
        load_dotenv(ROOT / ".env")
        settings = Settings.from_env()
    settings.validate_storage()
    if settings.storage_backend == "azure":
        from .azure_store import BlobPackages, CosmosDocuments
        store = Store(settings.database_path, documents=CosmosDocuments(settings), packages=BlobPackages(settings))
    else:
        store = Store(settings.database_path)
    agent_service = service or FoundryService(settings, store)
    runtime = Runtime(store, settings, agent_service)
    mcp_endpoint, mcp_manager = create_mcp(store, settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await anyio.to_thread.run_sync(store.initialize)
        await anyio.to_thread.run_sync(store.recover_interrupted_intakes)
        try:
            async with mcp_manager.run():
                yield
        finally:
            await agent_service.close()
            store.close()

    app = FastAPI(title="Enterprise Memory", version="0.1.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.state.store = store
    app.state.runtime = runtime
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        if request.url.path == "/health" and request.method == "GET":
            return JSONResponse({"status": "alive"}, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
        origin = request.headers.get("origin")
        local_origin = f"{request.url.scheme}://{request.headers.get('host', '')}"
        if origin and origin not in (local_origin, *settings.allowed_origins):
            return JSONResponse(AppError("ORIGIN_NOT_ALLOWED", "This demo only accepts same-origin or local development browser requests.", 403).body(), status_code=403)
        response = await call_next(request)
        if request.url.path.startswith(("/api", "/mcp")):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(AppError)
    async def app_error(_: Request, error: AppError):
        return JSONResponse(error.body(), status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, error: RequestValidationError):
        issues = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'] if part != 'body')}: {item['msg']}"
            for item in error.errors()[:5]
        )
        return JSONResponse(AppError("VALIDATION_ERROR", issues, 422).body(), status_code=422)

    @app.exception_handler(sqlite3.Error)
    @app.exception_handler(OSError)
    async def storage_error(_: Request, error: Exception):
        logger.exception("Local storage operation failed", exc_info=error)
        return JSONResponse(
            AppError("STORAGE_ERROR", "Local storage is unavailable. Check disk space, database permissions, and the server logs. Your change was not confirmed.", 503).body(),
            status_code=503,
        )

    @app.get("/api/status")
    def status():
        return {
            **runtime.status(),
            "published_skills": store.discover()["total"],
            "pending_proposals": sum(item["status"] == "pending" for item in store.list_proposals()),
            "local_only": settings.storage_backend == "sqlite",
            "storage_backend": settings.storage_backend,
            "access_boundary": "No end-user authentication. Trusted private demo access only.",
            "synthetic_seed_content": True,
        }

    @app.get("/api/skills")
    @app.get("/api/runtime/skills")
    def discover_skills(query: str = Query(default="", max_length=200), limit: int = Query(default=100, ge=1, le=100)):
        return store.discover(query, limit=limit)

    @app.get("/api/skills/{skill_id}")
    @app.get("/api/runtime/skills/{skill_id}")
    def load_skill(skill_id: str):
        return store.get_skill(skill_id)

    @app.post("/api/skills", status_code=202)
    def create_skill(value: SkillInput):
        return store.manual_draft(value)

    @app.put("/api/skills/{skill_id}")
    def update_skill(skill_id: str, value: SkillEdit):
        return store.manual_draft(SkillInput.model_validate(value.model_dump(exclude={"expected_version"})),
                                  skill_id, value.expected_version)

    @app.delete("/api/skills/{skill_id}", status_code=202)
    def delete_skill(skill_id: str, expected_version: int = Query(ge=1)):
        return store.action_draft(skill_id, ReleaseAction(action="retire", expected_version=expected_version,
                                                         reason="Explicit retirement requested from the skill library."))

    @app.get("/api/skills/{skill_id}/history")
    def history(skill_id: str):
        return store.history(skill_id)

    @app.get("/api/skills/{skill_id}/versions/{version}")
    def release(skill_id: str, version: int):
        return store.get_skill(skill_id, version)

    @app.get("/api/skills/{skill_id}/package")
    def package(skill_id: str):
        skill = store.get_skill(skill_id)
        buffer = BytesIO()
        with ZipFile(buffer, "w") as archive:
            for path, content in build_package(skill.model_dump()).items():
                archive.writestr(f"{skill.id}/{path}", content)
        return Response(buffer.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{skill.id}-v{skill.version}.zip"'})

    @app.post("/api/skills/{skill_id}/actions", status_code=202)
    def action(skill_id: str, value: ReleaseAction):
        return store.action_draft(skill_id, value)

    @app.get("/api/runtime")
    def runtime_contract():
        return {
            "name": "Enterprise Memory",
            "protocol_version": 1,
            "discovery": "/api/runtime/skills?query=<keywords>",
            "load": "/api/runtime/skills/{id}",
            "discovery_fields": ["id", "name", "description", "category", "version", "created_at", "updated_at", "owner", "applicability", "digest"],
            "load_adds": ["guidance", "references"],
            "publication": "Only published skills are visible. Loads read the current database version.",
            "mcp": "/mcp",
            "mcp_index": "skill://index.json",
            "mcp_resources": "skill://{id}/SKILL.md and skill://{id}/versions/{version}/SKILL.md",
            "security": "No end-user authentication or skill ACLs. Loopback locally; trusted private ingress on Azure.",
        }

    @app.post("/api/chat")
    async def chat(value: ChatInput):
        return await runtime.chat(value.message, value.session_id)

    @app.get("/api/intakes")
    def list_intakes():
        return {"intakes": store.list_intakes()}

    @app.post("/api/intakes", status_code=201)
    def create_intake(value: NotesInput):
        return store.create_intake(value)

    @app.get("/api/intakes/{intake_id}")
    def get_intake(intake_id: str):
        return store.get_intake(intake_id)

    @app.post("/api/intakes/{intake_id}/organize")
    async def organize_intake(intake_id: str):
        return await runtime.organize(intake_id)

    @app.get("/api/proposals")
    def list_proposals():
        return {"proposals": store.list_proposals()}

    @app.get("/api/proposals/{proposal_id}")
    def get_proposal(proposal_id: str):
        return store.get_proposal(proposal_id)

    @app.get("/api/proposals/{proposal_id}/diff")
    def proposal_diff(proposal_id: str):
        return store.proposal_diff(proposal_id)

    @app.put("/api/proposals/{proposal_id}")
    def edit_proposal(proposal_id: str, value: ProposalEdit):
        return store.edit_proposal(proposal_id, value)

    @app.post("/api/proposals/{proposal_id}/approve")
    def approve_proposal(proposal_id: str, value: ReviewRequest):
        return store.approve_proposal(proposal_id, value.expected_revision, value.reviewer_label)

    @app.post("/api/proposals/{proposal_id}/reject")
    def reject_proposal(proposal_id: str, value: ReviewRequest):
        return store.reject_proposal(proposal_id, value.expected_revision)

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def missing_api(path: str):
        raise AppError("NOT_FOUND", f"No API route at /api/{path[:100]}.", 404)

    app.router.routes.append(Route("/mcp", endpoint=mcp_endpoint, methods=["GET", "POST", "DELETE"]))

    if (ROOT / "dist").is_dir():
        app.mount("/", StaticFiles(directory=ROOT / "dist", html=True), name="frontend")
    else:
        @app.get("/", response_class=HTMLResponse)
        async def missing_frontend():
            return "<h1>Enterprise Memory API is running</h1><p>Build the UI with <code>npm install</code> and <code>npm run build</code>, then restart the server. Or run <code>npm run dev</code>.</p><a href='/api/docs'>API documentation</a>"

    return app


app = create_app()

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    project_endpoint: str = ""
    model_deployment: str = ""
    agent_prefix: str = "enterprise-memory-demo"
    database_path: Path = ROOT / "data" / "enterprise-memory.sqlite3"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            project_endpoint=os.getenv("FOUNDRY_PROJECT_ENDPOINT", "").strip().rstrip("/"),
            model_deployment=os.getenv("FOUNDRY_MODEL_DEPLOYMENT", "").strip(),
            agent_prefix=os.getenv("FOUNDRY_AGENT_PREFIX", "enterprise-memory-demo").strip(),
            database_path=Path(os.getenv("MEMORY_DB_PATH", str(ROOT / "data" / "enterprise-memory.sqlite3"))),
        )

    def problems(self) -> list[str]:
        problems = []
        if not self.project_endpoint:
            problems.append("Set FOUNDRY_PROJECT_ENDPOINT in .env to your existing Foundry project endpoint.")
        else:
            try:
                endpoint = urlparse(self.project_endpoint)
                valid_endpoint = (
                    endpoint.scheme == "https"
                    and bool(endpoint.hostname)
                    and endpoint.hostname.endswith(".ai.azure.com")
                    and endpoint.port in (None, 443)
                    and bool(re.fullmatch(r"/api/projects/[A-Za-z0-9._-]+", endpoint.path))
                    and not any((endpoint.username, endpoint.password, endpoint.query, endpoint.fragment))
                    and "<" not in self.project_endpoint
                )
            except ValueError:
                valid_endpoint = False
            if not valid_endpoint:
                problems.append("FOUNDRY_PROJECT_ENDPOINT must be an HTTPS Azure project URL ending in /api/projects/<project-name>.")
        if not self.model_deployment or "<" in self.model_deployment:
            problems.append("Set FOUNDRY_MODEL_DEPLOYMENT to a deployed, function-calling model in that project.")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]{0,49}", self.agent_prefix):
            problems.append("FOUNDRY_AGENT_PREFIX must be 1-50 letters, numbers, or hyphens.")
        return problems

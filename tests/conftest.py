import pytest

from server.config import Settings
from server.store import Store


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / "memory.sqlite3")
    result.initialize()
    return result


@pytest.fixture
def configured(tmp_path):
    return Settings(
        project_endpoint="https://synthetic-project.services.ai.azure.com/api/projects/test-project",
        model_deployment="test-deployment",
        database_path=tmp_path / "memory.sqlite3",
    )

import copy
import json
from types import SimpleNamespace

import pytest
from azure.core.exceptions import ResourceExistsError
from azure.cosmos.exceptions import CosmosBatchOperationError, CosmosResourceNotFoundError

from server.azure_store import BlobPackages, CosmosDocuments
from server.errors import AppError
from server.models import SkillInput
from server.packages import build_package, digest
from server.store import Store


class Container:
    def __init__(self):
        self.docs = {}
        self.batch = []
        self.etag = 0
        self.fail_commit = False

    def read(self):
        return {}

    def read_item(self, item, partition_key):
        if item not in self.docs:
            raise CosmosResourceNotFoundError(status_code=404)
        return copy.deepcopy(self.docs[item])

    def query_items(self, *args, **kwargs):
        return iter(copy.deepcopy(list(self.docs.values())))

    def execute_item_batch(self, batch_operations, partition_key):
        self.batch = copy.deepcopy(batch_operations)
        first = batch_operations[0]
        stale = first[0] == "replace" and first[2]["if_match_etag"] != self.docs["_revision"]["_etag"]
        if stale or self.fail_commit:
            raise CosmosBatchOperationError(status_code=412, headers={}, message="Concurrent write")
        for operation, args, options in batch_operations:
            if operation == "delete":
                del self.docs[args[0]]
            else:
                body = copy.deepcopy(args[1] if operation == "replace" else args[0])
                self.etag += 1
                body["_etag"] = str(self.etag)
                self.docs[body["id"]] = body
        return []


def backend():
    result = CosmosDocuments.__new__(CosmosDocuments)
    result.container = Container()
    result.workspace = "demo"
    return result


def test_cosmos_batches_condition_on_workspace_revision_and_abort_stale_writer():
    documents = backend()
    with documents.transaction(write=True) as docs:
        docs["skill:a"] = {"name": "First"}
    assert documents.container.batch[0][0] == "create"
    with pytest.raises(AppError) as failure:
        with documents.transaction(write=True) as docs:
            docs["skill:a"]["name"] = "Stale writer"
            with documents.transaction(write=True) as newer:
                newer["skill:a"]["name"] = "Newer writer"
    assert failure.value.code == "STORAGE_CONFLICT"
    with documents.transaction() as docs:
        assert docs["skill:a"]["name"] == "Newer writer"


def test_cosmos_publication_commit_failure_does_not_expose_uploaded_release(tmp_path):
    class Packages:
        def __init__(self):
            self.values = {}

        def put(self, skill_id, version, checksum, files, snapshot):
            self.values[(skill_id, version, checksum)] = (files, snapshot)

        def get(self, skill_id, version, checksum):
            return self.values[(skill_id, version, checksum)]

    documents, packages = backend(), Packages()
    store = Store(tmp_path / "unused.sqlite3", documents=documents, packages=packages)
    store.initialize()
    skill = store.get_skill("incident-response")
    values = skill.model_dump(include=set(SkillInput.model_fields))
    values["guidance"] = "Confirm the outage scope, then alert the incident commander."
    proposal = store.manual_draft(SkillInput(**values), skill.id, 1)
    documents.container.fail_commit = True
    with pytest.raises(AppError) as failure:
        store.approve_proposal(proposal["id"], 1)
    assert failure.value.code == "STORAGE_CONFLICT"
    assert store.get_skill(skill.id).version == 1
    assert store.get_proposal(proposal["id"])["status"] == "pending"
    documents.container.fail_commit = False
    store.approve_proposal(proposal["id"], 1)
    operations = documents.container.batch
    keys = [args[0]["id"] for op, args, _ in operations if op == "upsert"]
    assert f"skill:{skill.id}" in keys and f"release:{skill.id}:2" in keys and f"proposal:{proposal['id']}" in keys
    assert any(key.startswith("event:") for key in keys)
    assert not (tmp_path / "unused.sqlite3").exists()


def test_cosmos_rejects_oversized_atomic_change_without_partial_commit():
    documents = backend()
    with pytest.raises(AppError) as failure:
        with documents.transaction(write=True) as docs:
            for number in range(100):
                docs[str(number)] = {"value": number}
    assert failure.value.code == "TRANSACTION_TOO_LARGE"
    assert not documents.container.docs


def test_blob_create_only_retry_checks_digest_and_never_overwrites():
    class Blob:
        def __init__(self):
            self.body = None

        def upload_blob(self, body, overwrite, **kwargs):
            assert overwrite is False
            if self.body is not None:
                raise ResourceExistsError("Already uploaded")
            self.body = body

        def download_blob(self, **kwargs):
            return SimpleNamespace(readall=lambda: self.body)

        def get_blob_properties(self, **kwargs):
            return SimpleNamespace(size=len(self.body), etag="test-etag")

    blob = Blob()
    packages = BlobPackages.__new__(BlobPackages)
    packages.container = SimpleNamespace(get_blob_client=lambda path: blob)
    snapshot = {
        "id": "test-skill", "version": 1, "description": "A test skill with approved instructions.",
        "guidance": "Confirm the scope before deciding the next escalation.",
    }
    files = build_package(snapshot)
    checksum = digest(files)
    packages.put("test-skill", 1, checksum, files, snapshot)
    packages.put("test-skill", 1, checksum, files, snapshot)
    assert packages.get("test-skill", 1, checksum) == (files, snapshot)
    blob.body = json.dumps({"files": {"SKILL.md": "tampered"}, "snapshot": snapshot}).encode()
    with pytest.raises(AppError, match="different content"):
        packages.put("test-skill", 1, checksum, files, snapshot)
    with pytest.raises(AppError, match="validation"):
        packages.get("test-skill", 1, checksum)

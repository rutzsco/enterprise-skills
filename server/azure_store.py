import copy
import json
import logging
from contextlib import contextmanager

from azure.core import MatchConditions
from azure.core.exceptions import AzureError, ResourceExistsError
from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosBatchOperationError, CosmosHttpResponseError, CosmosResourceNotFoundError
from azure.identity import DefaultAzureCredential

from .errors import AppError
from .packages import digest


logger = logging.getLogger(__name__)


class CosmosDocuments:
    """Single-workspace metadata; every commit includes a conditional revision write."""

    def __init__(self, settings):
        self.credential = DefaultAzureCredential()
        self.client = CosmosClient(settings.cosmos_endpoint, credential=self.credential,
                                   consistency_level="Session", retry_total=3, connection_timeout=10)
        self.container = self.client.get_database_client(settings.cosmos_database).get_container_client(settings.cosmos_container)
        self.workspace = settings.workspace

    def initialize(self):
        try:
            self.container.read()
        except AzureError as error:
            logger.exception("Cosmos initialization failed")
            raise AppError("STORAGE_ERROR", "Private Cosmos DB is unavailable. Check network, DNS, provisioning and managed-identity permissions.", 503) from error

    def close(self):
        self.client.close()
        self.credential.close()

    def _revision(self):
        try:
            return self.container.read_item("_revision", partition_key=self.workspace)
        except CosmosResourceNotFoundError:
            return None

    @contextmanager
    def transaction(self, *, write=False):
        try:
            before = self._revision()
            rows = list(self.container.query_items(
                "SELECT * FROM c WHERE c.workspace = @workspace",
                parameters=[{"name": "@workspace", "value": self.workspace}],
                partition_key=self.workspace, max_item_count=100,
            ))
            after = self._revision()
            if (before or {}).get("_etag") != (after or {}).get("_etag"):
                raise AppError("STORAGE_CONFLICT", "The registry changed while reading. Reload and retry.", 409)
            original = {item["id"]: item["body"] for item in rows if item["id"] != "_revision"}
            documents = copy.deepcopy(original)
            yield documents
            if not write or documents == original:
                return
            revision = {"id": "_revision", "workspace": self.workspace, "revision": (before or {}).get("revision", 0) + 1}
            operations = [
                ("replace", ("_revision", revision), {"if_match_etag": before["_etag"]})
                if before else ("create", (revision,), {})
            ]
            for key, value in documents.items():
                if original.get(key) != value:
                    body = {"id": key, "workspace": self.workspace, "body": value}
                    operations.append(("upsert", (body,), {}))
            for key in original.keys() - documents.keys():
                operations.append(("delete", (key,), {}))
            if len(operations) > 100 or len(json.dumps(operations).encode()) > 1800000:
                raise AppError("TRANSACTION_TOO_LARGE", "This change exceeds the single-workspace transaction budget. Split the operation.", 422)
            self.container.execute_item_batch(batch_operations=operations, partition_key=self.workspace)
        except (CosmosHttpResponseError, CosmosBatchOperationError) as error:
            operation_statuses = {item.get("statusCode") for item in (getattr(error, "operation_responses", None) or [])}
            if error.status_code in (409, 412) or operation_statuses.intersection({409, 412}):
                raise AppError("STORAGE_CONFLICT", "Another writer changed the registry. Reload before retrying.", 409) from error
            logger.exception("Cosmos operation failed")
            raise AppError("STORAGE_ERROR", "Cosmos DB could not confirm this operation. Check service logs and reload before retrying.", 503) from error
        except AzureError as error:
            logger.exception("Private Cosmos access failed")
            raise AppError("STORAGE_ERROR", "Private registry storage is unavailable. Check network and managed-identity access.", 503) from error


class BlobPackages:
    def __init__(self, settings):
        from azure.storage.blob import BlobServiceClient

        self.credential = DefaultAzureCredential()
        self.client = BlobServiceClient(settings.blob_endpoint, credential=self.credential, retry_total=3,
                                        connection_timeout=10, read_timeout=20)
        self.container = self.client.get_container_client(settings.blob_container)

    def close(self):
        self.client.close()
        self.credential.close()

    def _blob(self, skill_id, version, checksum):
        return self.container.get_blob_client(f"{skill_id}/v{version}/{checksum}/package.json")

    def put(self, skill_id, version, checksum, files, snapshot):
        if digest(files) != checksum:
            raise AppError("PACKAGE_INTEGRITY", "The package digest does not match.", 422)
        body = json.dumps({"files": files, "snapshot": snapshot}, sort_keys=True).encode()
        try:
            blob = self._blob(skill_id, version, checksum)
            try:
                blob.upload_blob(body, overwrite=False, timeout=30)
            except ResourceExistsError:
                if blob.download_blob(timeout=30).readall() != body:
                    raise AppError("PACKAGE_CONFLICT", "An immutable package already exists with different content.", 409)
            stored = json.loads(blob.download_blob(timeout=30).readall())
            if stored != {"files": files, "snapshot": snapshot}:
                raise AppError("PACKAGE_INTEGRITY", "Blob verification failed. Nothing was published.", 503)
        except AzureError as error:
            logger.exception("Blob package publication failed")
            raise AppError("STORAGE_ERROR", "Private Blob Storage could not confirm the package. Nothing was published.", 503) from error

    def get(self, skill_id, version, checksum):
        try:
            blob = self._blob(skill_id, version, checksum)
            properties = blob.get_blob_properties(timeout=20)
            if properties.size > 512000:
                raise AppError("PACKAGE_INTEGRITY", "Stored package exceeds the size limit.", 503)
            result = json.loads(blob.download_blob(timeout=20, etag=properties.etag,
                                                  match_condition=MatchConditions.IfNotModified).readall())
            if not isinstance(result, dict) or set(result) != {"files", "snapshot"} or digest(result["files"]) != checksum:
                raise AppError("PACKAGE_INTEGRITY", "Stored package failed validation.", 503)
            return result["files"], result["snapshot"]
        except (ValueError, KeyError, TypeError) as error:
            raise AppError("PACKAGE_INTEGRITY", "Stored package is malformed.", 503) from error
        except AzureError as error:
            logger.exception("Blob package read failed")
            raise AppError("STORAGE_ERROR", "Approved package storage is unavailable. No stale fallback was returned.", 503) from error

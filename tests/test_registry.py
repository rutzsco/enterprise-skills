import json
import sqlite3

import pytest
import yaml

from server.errors import AppError
from server.models import ReleaseAction, SkillEdit, SkillInput
from server.packages import build_package, digest
from server.store import Store


def fields(skill, **changes):
    return SkillInput.model_validate({**skill.model_dump(include=set(SkillInput.model_fields)), **changes})


def test_manual_drafts_release_history_rollback_and_retirement(store):
    original = store.get_skill("software-purchasing")
    draft = store.manual_draft(fields(original, guidance="Finance approves every purchase regardless of annual cost."), original.id, 1)
    assert store.get_skill(original.id).guidance == original.guidance
    change = store.proposal_diff(draft["id"])["diff"]
    assert "-# " in change and "+Finance approves" in change
    result = store.approve_proposal(draft["id"], 1)
    assert result["proposal"]["published_version"] == 2
    assert store.get_skill(original.id, 1) == original
    release = store.history(original.id)["releases"][0]
    assert release["intake_id"] == draft["intake_id"]
    assert release["reviewer_authenticated"] is False
    rollback = store.action_draft(original.id, ReleaseAction(action="rollback", expected_version=2,
                                                           target_version=1, reason="Restore the earlier reviewed synthetic guidance."))
    assert store.get_skill(original.id).version == 2
    store.approve_proposal(rollback["id"], 1)
    assert store.get_skill(original.id) == original
    next_draft = store.manual_draft(fields(original, guidance="The third release preserves a new approved decision rule."), original.id, 1)
    assert store.approve_proposal(next_draft["id"], 1)["skill"]["version"] == 3
    retirement = store.action_draft(original.id, ReleaseAction(action="retire", expected_version=3,
                                                             reason="This synthetic policy is no longer applicable."))
    assert store.get_skill(original.id).version == 3
    store.approve_proposal(retirement["id"], 1)
    with pytest.raises(AppError):
        store.get_skill(original.id)
    assert store.get_skill(original.id, 1) == original
    assert len(store.history(original.id)["releases"]) == 3
    with pytest.raises(AppError):
        store.read_resource(original.id, "SKILL.md", 1)


def test_rollback_makes_preexisting_draft_stale_even_when_version_matches(store):
    skill = store.get_skill("incident-response")
    stale = store.manual_draft(fields(skill), skill.id, 1)
    store.update_skill(skill.id, SkillEdit(**fields(skill).model_dump(), expected_version=1))
    rollback = store.action_draft(skill.id, ReleaseAction(action="rollback", expected_version=2, target_version=1,
                                                        reason="Restore original reviewed incident guidance."))
    store.approve_proposal(rollback["id"], 1)
    assert store.get_skill(skill.id).version == stale["base_version"]
    with pytest.raises(AppError, match="changed"):
        store.approve_proposal(stale["id"], 1)


def test_portable_package_frontmatter_references_and_integrity(store):
    skill = store.get_skill("incident-response")
    data = fields(skill, references={
        "references/z-context.md": "# Additional context\nSynthetic content.",
        "references/context.md": "# Supporting guidance\nSynthetic content.",
    })
    draft = store.manual_draft(data, skill.id, 1)
    store.approve_proposal(draft["id"], 1)
    package = build_package(store.get_skill(skill.id).model_dump())
    header = yaml.safe_load(package["SKILL.md"].split("---")[1])
    assert header["name"] == skill.id
    assert header["metadata"]["version"] == "2"
    assert store.read_resource(skill.id, "references/context.md") == data.references["references/context.md"]
    assert "references" not in store.discover()["skills"][0]
    assert store.history(skill.id)["releases"][0]["digest"] == digest(package)
    assert build_package(json.loads(json.dumps(store.get_skill(skill.id).model_dump(), sort_keys=True))) == package
    for path in ("../secret.txt", "references/../secret.md", "scripts/run.py", "references/nested/path.md"):
        with pytest.raises(AppError):
            build_package({**skill.model_dump(), "references": {path: "Do not execute."}})


def test_storage_failure_leaves_package_invisible_and_retry_publishes_once(tmp_path):
    class Packages:
        def __init__(self):
            self.values = {}
            self.fail = False

        def put(self, skill_id, version, checksum, files, snapshot):
            self.values[(skill_id, version, checksum)] = (files, snapshot)
            if self.fail:
                raise AppError("STORAGE_ERROR", "Upload verification failed.", 503)

        def get(self, skill_id, version, checksum):
            return self.values[(skill_id, version, checksum)]

    packages = Packages()
    store = Store(tmp_path / "registry.sqlite3", packages=packages)
    store.initialize()
    original = store.get_skill("incident-response")
    draft = store.manual_draft(fields(original, guidance="Notify the incident commander after confirming a shared outage."), original.id, 1)
    packages.fail = True
    with pytest.raises(AppError):
        store.approve_proposal(draft["id"], 1)
    assert store.get_skill(original.id).version == 1
    assert store.get_proposal(draft["id"])["status"] == "pending"
    packages.fail = False
    store.approve_proposal(draft["id"], 1)
    assert [item["version"] for item in store.history(original.id)["releases"]] == [2, 1]


def test_legacy_migration_preserves_current_snapshot_without_claiming_approval(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE skills (id TEXT, name TEXT, name_key TEXT, description TEXT, category TEXT,
                                 guidance TEXT, version INTEGER, created_at TEXT, updated_at TEXT);
            CREATE TABLE intakes (id TEXT);
            CREATE TABLE proposals (id TEXT);
            CREATE TABLE agent_bindings (key TEXT);
            CREATE TABLE metadata (key TEXT, value TEXT);
        """)
        connection.execute("INSERT INTO skills VALUES (?,?,?,?,?,?,?,?,?)", (
            "legacy-skill", "Legacy skill", "legacy skill", "Existing synthetic guidance.",
            "General", "Retain the current snapshot, not invented history.", 7, "2026-01-01", "2026-01-02",
        ))
    migrated = Store(path)
    migrated.initialize()
    assert migrated.get_skill("legacy-skill").version == 7
    release = migrated.history("legacy-skill")["releases"][0]
    assert release["origin"] == "legacy-import" and not release["approved"]
    assert len(migrated.history("legacy-skill")["releases"]) == 1
    migrated.initialize()
    assert migrated.discover()["total"] == 1

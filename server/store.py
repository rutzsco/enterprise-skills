import difflib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .documents import SQLiteDocuments
from .errors import AppError
from .models import NotesInput, ProposalCandidate, ProposalEdit, Skill, SkillEdit, SkillInput
from .packages import build_package, digest, metadata
from .seeds import SEED_SKILLS


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path, *, documents=None, packages=None):
        self.path = path
        self.documents = documents or SQLiteDocuments(path)
        self.packages = packages

    def close(self):
        if self.packages:
            self.packages.close()
        if hasattr(self.documents, "close"):
            self.documents.close()

    def initialize(self):
        self.documents.initialize()
        legacy = self.documents.legacy() if hasattr(self.documents, "legacy") else None
        with self.documents.transaction(write=True) as docs:
            if "initialized" in docs:
                return
            if legacy:
                for row in legacy["skills"]:
                    skill = Skill.model_validate({key: value for key, value in row.items() if key != "name_key"})
                    self._release(docs, skill, origin="legacy-import")
                for row in legacy["intakes"]:
                    row["events"] = json.loads(row["events"])
                    docs[f"intake:{row['id']}"] = row
                for row in legacy["proposals"]:
                    row.update(json.loads(row.pop("candidate")))
                    target = docs.get(f"skill:{row.get('skill_id')}")
                    if target and target["version"] == row.get("base_version") and row["status"] == "pending":
                        row["base_generation"] = target["generation"]
                    docs[f"proposal:{row['id']}"] = row
                for row in legacy["agent_bindings"]:
                    docs[f"binding:{row['key']}"] = {"name": row["name"], "version": row["version"]}
            else:
                for seed in SEED_SKILLS:
                    self._insert(docs, SkillInput.model_validate({key: value for key, value in seed.items() if key != "id"}), seed["id"], origin="synthetic-seed")
            docs["initialized"] = {"at": now()}

    def _event(self, docs, action, skill_id=None, **details):
        event = {"id": str(uuid4()), "at": now(), "action": action, "skill_id": skill_id, **details}
        docs[f"event:{event['id']}"] = event

    def _release(self, docs, skill, *, origin="approval", proposal=None, reviewer="System"):
        payload = skill.model_dump()
        files = build_package(payload)
        checksum = digest(files)
        release_key = f"release:{skill.id}:{skill.version}"
        if release_key in docs:
            raise AppError("RELEASE_EXISTS", "An immutable release already has this version.", 409)
        release = {
            **metadata(payload), "digest": checksum, "origin": origin,
            "proposal_id": proposal["id"] if proposal else None,
            "intake_id": proposal["intake_id"] if proposal else None,
            "evidence": proposal.get("evidence", []) if proposal else [],
            "rules": [
                {**rule, "id": f"{skill.id}:v{skill.version}:rule-{index + 1}",
                 "intake_id": proposal["intake_id"]}
                for index, rule in enumerate(proposal.get("rules", []))
            ] if proposal else [],
            "reviewer_label": reviewer, "reviewer_authenticated": False,
            "files": list(files), "approved": origin in ("approval", "synthetic-seed"),
        }
        if self.packages:
            self.packages.put(skill.id, skill.version, checksum, files, payload)
        else:
            release["package"] = files
            release["snapshot"] = payload
        docs[release_key] = release
        previous = docs.get(f"skill:{skill.id}", {})
        docs[f"skill:{skill.id}"] = {
            **metadata(payload), "digest": checksum, "retired": False,
            "generation": previous.get("generation", 0) + 1,
        }
        self._event(docs, "published" if origin == "approval" else origin, skill.id,
                    version=skill.version, proposal_id=release["proposal_id"], reviewer_label=reviewer,
                    reviewer_authenticated=False)
        return skill

    def _load(self, docs, skill_id, version=None):
        active = docs.get(f"skill:{skill_id}")
        if not active or (active["retired"] and version is None):
            raise AppError("SKILL_NOT_FOUND", "This skill no longer exists in the active registry.", 404)
        release = docs.get(f"release:{skill_id}:{version or active['version']}")
        if not release:
            raise AppError("RELEASE_NOT_FOUND", "This published release could not be found.", 404)
        if self.packages:
            files, snapshot = self.packages.get(skill_id, release["version"], release["digest"])
        else:
            files, snapshot = release["package"], release["snapshot"]
        if digest(files) != release["digest"] or build_package(snapshot) != files:
            raise AppError("PACKAGE_INTEGRITY", "Published package integrity verification failed.", 503)
        return Skill.model_validate(snapshot)

    def _unique(self, docs, name, skill_id=None):
        if any(key.startswith("skill:") and value["id"] != skill_id and value["name"].casefold() == name.casefold()
               for key, value in docs.items()):
            raise AppError("DUPLICATE_SKILL", "A published or retired skill already uses that name.", 409)

    def _insert(self, docs, value, skill_id=None, *, origin="approval", proposal=None, reviewer="System"):
        self._unique(docs, value.name)
        timestamp = now()
        skill = Skill(**value.model_dump(), id=skill_id or str(uuid4()), version=1, created_at=timestamp, updated_at=timestamp)
        return self._release(docs, skill, origin=origin, proposal=proposal, reviewer=reviewer)

    def _update(self, docs, skill_id, value, expected_version, *, proposal=None, reviewer="System"):
        current = self._load(docs, skill_id)
        if current.version != expected_version:
            raise AppError("STALE_SKILL", "This skill changed. Reload before saving.", 409)
        self._unique(docs, value.name, skill_id)
        versions = [item["version"] for key, item in docs.items() if key.startswith(f"release:{skill_id}:")]
        skill = Skill(**value.model_dump(), id=skill_id, version=max(versions) + 1,
                      created_at=current.created_at, updated_at=now())
        return self._release(docs, skill, proposal=proposal, reviewer=reviewer)

    def get_skill(self, skill_id, version=None):
        with self.documents.transaction() as docs:
            return self._load(docs, skill_id, version)

    def discover(self, query="", *, limit=100):
        terms = query.casefold().split()
        with self.documents.transaction() as docs:
            matches = [
                {key: value for key, value in item.items() if key not in ("retired", "generation")}
                for key, item in docs.items() if key.startswith("skill:") and not item["retired"]
                and (not terms or any(term in f"{item['name']} {item['description']} {item['category']}".casefold() for term in terms))
            ]
        matches.sort(key=lambda item: item["name"])
        return {"skills": matches[:limit], "total": len(matches), "limit": limit}

    # Internal bootstrap/test helpers. HTTP authoring always creates review drafts.
    def create_skill(self, value: SkillInput):
        with self.documents.transaction(write=True) as docs:
            return self._insert(docs, value)

    def update_skill(self, skill_id, value: SkillEdit):
        with self.documents.transaction(write=True) as docs:
            return self._update(docs, skill_id, SkillInput.model_validate(value.model_dump(exclude={"expected_version"})), value.expected_version)

    def delete_skill(self, skill_id, expected_version):
        with self.documents.transaction(write=True) as docs:
            current = self._load(docs, skill_id)
            if current.version != expected_version:
                raise AppError("STALE_SKILL", "This skill changed. Reload before retirement.", 409)
            docs[f"skill:{skill_id}"]["retired"] = True
            docs[f"skill:{skill_id}"]["generation"] += 1
            self._event(docs, "retired", skill_id)

    def history(self, skill_id):
        with self.documents.transaction() as docs:
            if f"skill:{skill_id}" not in docs:
                raise AppError("SKILL_NOT_FOUND", "This skill could not be found.", 404)
            return {
                "active": docs[f"skill:{skill_id}"],
                "releases": sorted([
                    {field: value for field, value in item.items() if field not in ("package", "snapshot")}
                    for key, item in docs.items() if key.startswith(f"release:{skill_id}:")
                ], key=lambda item: item["version"], reverse=True),
                "events": sorted([item for key, item in docs.items() if key.startswith("event:") and item["skill_id"] == skill_id],
                                 key=lambda item: item["at"]),
            }

    def read_resource(self, skill_id, path, version=None):
        with self.documents.transaction() as docs:
            if docs.get(f"skill:{skill_id}", {}).get("retired"):
                raise AppError("SKILL_NOT_FOUND", "This skill was retired and is unavailable to runtime consumers.", 404)
            skill = self._load(docs, skill_id, version)
            files = build_package(skill.model_dump())
            if path not in files:
                raise AppError("RESOURCE_NOT_FOUND", "This file is not in the approved package.", 404)
            return files[path]

    def create_intake(self, value: NotesInput):
        timestamp, intake_id = now(), str(uuid4())
        item = {"id": intake_id, **value.model_dump(), "status": "saved", "error": None,
                "events": [], "created_at": timestamp, "updated_at": timestamp}
        with self.documents.transaction(write=True) as docs:
            docs[f"intake:{intake_id}"] = item
        return {**item, "proposals": []}

    def _intake(self, docs, intake_id):
        if f"intake:{intake_id}" not in docs:
            raise AppError("INTAKE_NOT_FOUND", "These notes could not be found.", 404)
        return docs[f"intake:{intake_id}"]

    def get_intake(self, intake_id):
        with self.documents.transaction() as docs:
            return {**self._intake(docs, intake_id), "proposals": [
                self._proposal(docs, item["id"]) for key, item in docs.items()
                if key.startswith("proposal:") and item["intake_id"] == intake_id
            ]}

    def list_intakes(self):
        with self.documents.transaction() as docs:
            return sorted([
                {**{field: value for field, value in item.items() if field not in ("notes", "events")},
                 "pending_count": sum(key.startswith("proposal:") and value["intake_id"] == item["id"] and value["status"] == "pending"
                                      for key, value in docs.items())}
                for key, item in docs.items() if key.startswith("intake:")
            ], key=lambda item: item["created_at"], reverse=True)

    def claim_intake(self, intake_id):
        with self.documents.transaction(write=True) as docs:
            item = self._intake(docs, intake_id)
            if item["status"] not in ("saved", "failed"):
                raise AppError("INTAKE_ALREADY_ORGANIZED", "These notes are already being organized or have proposals.", 409)
            item.update(status="organizing", error=None, events=[], updated_at=now())
            return dict(item)

    def fail_intake(self, intake_id, message, events):
        with self.documents.transaction(write=True) as docs:
            self._intake(docs, intake_id).update(status="failed", error=message, events=events, updated_at=now())

    def recover_interrupted_intakes(self):
        with self.documents.transaction(write=True) as docs:
            for key, value in docs.items():
                if key.startswith("intake:") and value["status"] == "organizing":
                    value.update(status="failed", error="The server stopped during organization. Your notes are saved; try again.", updated_at=now())

    def finish_intake(self, intake_id, candidates: list[ProposalCandidate], events):
        with self.documents.transaction(write=True) as docs:
            intake = self._intake(docs, intake_id)
            if intake["status"] != "organizing":
                raise AppError("INTAKE_STATE_CHANGED", "These notes are no longer awaiting agent output.", 409)
            for candidate in candidates:
                proposal_id, timestamp = str(uuid4()), now()
                target = docs.get(f"skill:{candidate.skill_id}")
                docs[f"proposal:{proposal_id}"] = {
                    **candidate.model_dump(), "id": proposal_id, "intake_id": intake_id,
                    "status": "pending", "revision": 1, "published_skill_id": None,
                    "base_generation": target["generation"] if target else None,
                    "created_at": timestamp, "updated_at": timestamp,
                }
            intake.update(status="ready", events=events, error=None, updated_at=now())
        return self.get_intake(intake_id)

    def _proposal(self, docs, proposal_id):
        item = docs.get(f"proposal:{proposal_id}")
        if not item:
            raise AppError("PROPOSAL_NOT_FOUND", "This proposal could not be found.", 404)
        result = {**item, "conflict": None}
        if item["status"] == "pending":
            target = docs.get(f"skill:{item['skill_id']}")
            if item["action"] != "create":
                if not target or target["retired"] or target["version"] != item["base_version"] or (
                    item.get("base_generation") is not None and target["generation"] != item["base_generation"]
                ):
                    result["conflict"] = "The published skill changed or was retired. Reject this draft and review a fresh proposal."
            elif any(key.startswith("skill:") and value["name"].casefold() == item["name"].casefold() for key, value in docs.items()):
                result["conflict"] = "A published or retired skill already uses this name."
        return result

    def get_proposal(self, proposal_id):
        with self.documents.transaction() as docs:
            return self._proposal(docs, proposal_id)

    def list_proposals(self):
        with self.documents.transaction() as docs:
            return sorted([self._proposal(docs, item["id"]) for key, item in docs.items() if key.startswith("proposal:")],
                          key=lambda item: item["created_at"], reverse=True)

    def _reviewable(self, docs, proposal_id, revision):
        proposal = self._proposal(docs, proposal_id)
        if proposal["status"] != "pending":
            raise AppError("PROPOSAL_CLOSED", "This proposal was already approved or rejected.", 409)
        if proposal["revision"] != revision:
            raise AppError("STALE_PROPOSAL", "This draft was edited elsewhere. Reload before reviewing.", 409)
        return proposal

    def edit_proposal(self, proposal_id, value: ProposalEdit):
        with self.documents.transaction(write=True) as docs:
            proposal = self._reviewable(docs, proposal_id, value.expected_revision)
            if proposal["action"] not in ("create", "update"):
                raise AppError("ACTION_NOT_EDITABLE", "Release actions must be rejected and proposed again to change them.", 409)
            updated = value.model_dump(exclude={"expected_revision"})
            if updated["guidance"] != proposal["guidance"]:
                # Agent evidence does not attest to reviewer-written replacement rules.
                updated["rules"] = []
            docs[f"proposal:{proposal_id}"].update(**updated, revision=proposal["revision"] + 1, updated_at=now())
        return self.get_proposal(proposal_id)

    def reject_proposal(self, proposal_id, expected_revision):
        with self.documents.transaction(write=True) as docs:
            proposal = self._reviewable(docs, proposal_id, expected_revision)
            docs[f"proposal:{proposal_id}"].update(status="rejected", revision=proposal["revision"] + 1, updated_at=now())
            self._event(docs, "rejected", proposal["skill_id"], proposal_id=proposal_id)
        return self.get_proposal(proposal_id)

    def approve_proposal(self, proposal_id, expected_revision, reviewer="Trusted demo reviewer (unverified)"):
        with self.documents.transaction(write=True) as docs:
            proposal = self._reviewable(docs, proposal_id, expected_revision)
            if proposal["conflict"]:
                raise AppError("STALE_PROPOSAL", proposal["conflict"], 409)
            fields = SkillInput.model_validate({key: proposal[key] for key in SkillInput.model_fields if key in proposal})
            if proposal["action"] == "create":
                skill = self._insert(docs, fields, proposal=proposal, reviewer=reviewer)
            elif proposal["action"] == "update":
                skill = self._update(docs, proposal["skill_id"], fields, proposal["base_version"], proposal=proposal, reviewer=reviewer)
            else:
                pointer = docs[f"skill:{proposal['skill_id']}"]
                if proposal["action"] == "rollback":
                    release = docs.get(f"release:{pointer['id']}:{proposal['target_version']}")
                    if not release or not release["approved"]:
                        raise AppError("NOT_APPROVED_RELEASE", "Rollback requires an earlier approved release.", 409)
                    skill = self._load(docs, pointer["id"], proposal["target_version"])
                    docs[f"skill:{pointer['id']}"] = {
                        **metadata(skill.model_dump()), "digest": release["digest"], "retired": False,
                        "generation": pointer["generation"] + 1,
                    }
                else:
                    skill = self._load(docs, pointer["id"])
                    pointer.update(retired=True, generation=pointer["generation"] + 1)
                self._event(docs, proposal["action"], skill.id, version=skill.version, proposal_id=proposal_id,
                            reviewer_label=reviewer, reviewer_authenticated=False)
            docs[f"proposal:{proposal_id}"].update(
                status="approved", published_skill_id=skill.id, published_version=skill.version,
                revision=proposal["revision"] + 1, updated_at=now(),
            )
        return {"skill": skill.model_dump(), "proposal": self.get_proposal(proposal_id)}

    def _manual_draft(self, docs, value, target=None, *, action=None):
        build_package({"id": target.id if target else str(uuid4()), "version": 1, **value.model_dump()})
        intake_id, proposal_id, timestamp = str(uuid4()), str(uuid4()), now()
        candidate = ProposalCandidate(
            **value.model_dump(), action="update" if target else "create",
            skill_id=target.id if target else None, base_version=target.version if target else None,
            rationale="Manually authored guidance submitted for explicit review.",
            evidence=[value.guidance[:2000]],
        )
        docs[f"intake:{intake_id}"] = {
            "id": intake_id, "title": f"Manual draft: {value.name}"[:100], "notes": value.guidance,
            "status": "ready", "events": [], "error": None, "created_at": timestamp, "updated_at": timestamp,
        }
        docs[f"proposal:{proposal_id}"] = {
            **candidate.model_dump(), "id": proposal_id, "intake_id": intake_id,
            "status": "pending", "revision": 1, "published_skill_id": None,
            "base_generation": docs[f"skill:{target.id}"]["generation"] if target else None,
            "created_at": timestamp, "updated_at": timestamp,
        }
        if action:
            docs[f"proposal:{proposal_id}"].update(action=action.action, target_version=action.target_version, rationale=action.reason)
        return self._proposal(docs, proposal_id)

    def manual_draft(self, value: SkillInput, skill_id=None, expected_version=None):
        with self.documents.transaction(write=True) as docs:
            target = self._load(docs, skill_id) if skill_id else None
            if target and target.version != expected_version:
                raise AppError("STALE_SKILL", "This skill changed. Reload before proposing changes.", 409)
            return self._manual_draft(docs, value, target)

    def action_draft(self, skill_id, action):
        with self.documents.transaction(write=True) as docs:
            target = self._load(docs, skill_id)
            if target.version != action.expected_version:
                raise AppError("STALE_SKILL", "This skill changed. Reload before proposing a release action.", 409)
            if action.action == "rollback":
                release = docs.get(f"release:{skill_id}:{action.target_version}")
                if not release or not release["approved"]:
                    raise AppError("NOT_APPROVED_RELEASE", "Rollback requires an existing approved release.", 422)
            return self._manual_draft(docs, SkillInput.model_validate(target.model_dump(include=set(SkillInput.model_fields))), target, action=action)

    def proposal_diff(self, proposal_id):
        proposal = self.get_proposal(proposal_id)
        before = self.get_skill(proposal["skill_id"], proposal["base_version"]).guidance if proposal["skill_id"] else ""
        if proposal["action"] == "retire":
            after = ""
        elif proposal["action"] == "rollback":
            after = self.get_skill(proposal["skill_id"], proposal["target_version"]).guidance
        else:
            after = proposal["guidance"]
        return {"diff": "".join(difflib.unified_diff([line + "\n" for line in before.splitlines()],
                                                   [line + "\n" for line in after.splitlines()],
                                                   fromfile="reviewed base", tofile="proposal"))}

    def get_agent_binding(self, key):
        with self.documents.transaction() as docs:
            return docs.get(f"binding:{key}")

    def save_agent_binding(self, key, name, version):
        with self.documents.transaction(write=True) as docs:
            docs[f"binding:{key}"] = {"name": name, "version": version}

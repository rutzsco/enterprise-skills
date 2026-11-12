import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .errors import AppError
from .models import NotesInput, ProposalCandidate, ProposalEdit, Skill, SkillEdit, SkillInput
from .seeds import SEED_SKILLS


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connection(self, *, write: bool = False):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS skills (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL, category TEXT NOT NULL, guidance TEXT NOT NULL,
                    version INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS intakes (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, notes TEXT NOT NULL,
                    status TEXT NOT NULL, error TEXT, events TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS proposals (
                    id TEXT PRIMARY KEY, intake_id TEXT NOT NULL REFERENCES intakes(id),
                    candidate TEXT NOT NULL, status TEXT NOT NULL, revision INTEGER NOT NULL,
                    published_skill_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_bindings (
                    key TEXT PRIMARY KEY, name TEXT NOT NULL, version TEXT NOT NULL
                );
            """)
        with self.connection(write=True) as connection:
            if not connection.execute("SELECT 1 FROM metadata WHERE key = 'seeded'").fetchone():
                for seed in SEED_SKILLS:
                    self._insert_skill(
                        connection,
                        SkillInput.model_validate({key: value for key, value in seed.items() if key != "id"}),
                        skill_id=seed["id"],
                    )
                connection.execute("INSERT INTO metadata VALUES ('seeded', '1')")

    def recover_interrupted_intakes(self) -> None:
        with self.connection(write=True) as connection:
            connection.execute(
                "UPDATE intakes SET status = 'failed', error = ?, updated_at = ? WHERE status = 'organizing'",
                ("The server stopped during organization. Your notes are saved; try organizing again.", now()),
            )

    @staticmethod
    def _skill(row: sqlite3.Row | None) -> Skill:
        if row is None:
            raise AppError("SKILL_NOT_FOUND", "This skill no longer exists.", 404)
        return Skill.model_validate({key: row[key] for key in row.keys() if key != "name_key"})

    def get_skill(self, skill_id: str) -> Skill:
        with self.connection() as connection:
            return self._skill(connection.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone())

    def discover(self, query: str = "", *, limit: int = 100) -> dict:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT id, name, description, category, version, created_at, updated_at FROM skills ORDER BY name"
            ).fetchall()
        terms = query.casefold().split()
        matches = [
            dict(row)
            for row in rows
            if not terms
            or any(term in f"{row['name']} {row['description']} {row['category']}".casefold() for term in terms)
        ]
        return {"skills": matches[:limit], "total": len(matches), "limit": limit}

    def _insert_skill(self, connection: sqlite3.Connection, value: SkillInput, *, skill_id: str | None = None) -> Skill:
        timestamp = now()
        skill = Skill(**value.model_dump(), id=skill_id or str(uuid4()), version=1, created_at=timestamp, updated_at=timestamp)
        try:
            connection.execute(
                "INSERT INTO skills (id, name, name_key, description, category, guidance, version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    skill.id, skill.name, skill.name.casefold(), skill.description, skill.category,
                    skill.guidance, skill.version, skill.created_at, skill.updated_at,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise AppError("DUPLICATE_SKILL", "A published skill already uses that name. Edit it or choose a distinct name.", 409) from error
        return skill

    def create_skill(self, value: SkillInput) -> Skill:
        with self.connection(write=True) as connection:
            return self._insert_skill(connection, value)

    def _update_skill(self, connection: sqlite3.Connection, skill_id: str, value: SkillInput, expected_version: int) -> Skill:
        current = self._skill(connection.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone())
        if current.version != expected_version:
            raise AppError("STALE_SKILL", "This skill changed since you opened it. Reload it before saving.", 409)
        updated = Skill(
            **value.model_dump(),
            id=current.id,
            version=current.version + 1,
            created_at=current.created_at,
            updated_at=now(),
        )
        try:
            connection.execute(
                "UPDATE skills SET name = ?, name_key = ?, description = ?, category = ?, guidance = ?, version = ?, updated_at = ? WHERE id = ?",
                (
                    updated.name, updated.name.casefold(), updated.description, updated.category,
                    updated.guidance, updated.version, updated.updated_at, updated.id,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise AppError("DUPLICATE_SKILL", "Another published skill already uses that name.", 409) from error
        return updated

    def update_skill(self, skill_id: str, value: SkillEdit) -> Skill:
        fields = SkillInput.model_validate(value.model_dump(exclude={"expected_version"}))
        with self.connection(write=True) as connection:
            return self._update_skill(connection, skill_id, fields, value.expected_version)

    def delete_skill(self, skill_id: str, expected_version: int) -> None:
        with self.connection(write=True) as connection:
            current = self._skill(connection.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone())
            if current.version != expected_version:
                raise AppError("STALE_SKILL", "This skill changed. Reload it before deleting.", 409)
            connection.execute("DELETE FROM skills WHERE id = ?", (skill_id,))

    def create_intake(self, value: NotesInput) -> dict:
        intake_id, timestamp = str(uuid4()), now()
        with self.connection(write=True) as connection:
            connection.execute(
                "INSERT INTO intakes (id, title, notes, status, created_at, updated_at) VALUES (?, ?, ?, 'saved', ?, ?)",
                (intake_id, value.title, value.notes, timestamp, timestamp),
            )
        return self.get_intake(intake_id)

    @staticmethod
    def _intake(row: sqlite3.Row | None) -> dict:
        if row is None:
            raise AppError("INTAKE_NOT_FOUND", "These notes could not be found.", 404)
        result = dict(row)
        result["events"] = json.loads(result["events"])
        return result

    def get_intake(self, intake_id: str) -> dict:
        with self.connection() as connection:
            result = self._intake(connection.execute("SELECT * FROM intakes WHERE id = ?", (intake_id,)).fetchone())
            result["proposals"] = [
                self._proposal(connection, row)
                for row in connection.execute("SELECT * FROM proposals WHERE intake_id = ? ORDER BY created_at", (intake_id,))
            ]
            return result

    def list_intakes(self) -> list[dict]:
        with self.connection() as connection:
            return [
                dict(row)
                for row in connection.execute("""
                    SELECT i.id, i.title, i.status, i.error, i.created_at, i.updated_at,
                        (SELECT COUNT(*) FROM proposals p WHERE p.intake_id = i.id AND p.status = 'pending') AS pending_count
                    FROM intakes i ORDER BY created_at DESC
                """)
            ]

    def claim_intake(self, intake_id: str) -> dict:
        with self.connection(write=True) as connection:
            intake = self._intake(connection.execute("SELECT * FROM intakes WHERE id = ?", (intake_id,)).fetchone())
            if intake["status"] not in ("saved", "failed"):
                raise AppError("INTAKE_ALREADY_ORGANIZED", "These notes are already being organized or have proposals. Submit a new intake for new notes.", 409)
            connection.execute(
                "UPDATE intakes SET status = 'organizing', error = NULL, events = '[]', updated_at = ? WHERE id = ?",
                (now(), intake_id),
            )
            return intake

    def fail_intake(self, intake_id: str, message: str, events: list[dict]) -> None:
        with self.connection(write=True) as connection:
            connection.execute(
                "UPDATE intakes SET status = 'failed', error = ?, events = ?, updated_at = ? WHERE id = ?",
                (message, json.dumps(events), now(), intake_id),
            )

    def finish_intake(self, intake_id: str, candidates: list[ProposalCandidate], events: list[dict]) -> dict:
        with self.connection(write=True) as connection:
            intake = self._intake(connection.execute("SELECT * FROM intakes WHERE id = ?", (intake_id,)).fetchone())
            if intake["status"] != "organizing":
                raise AppError("INTAKE_STATE_CHANGED", "These notes are no longer awaiting agent output.", 409)
            for candidate in candidates:
                timestamp = now()
                connection.execute(
                    "INSERT INTO proposals VALUES (?, ?, ?, 'pending', 1, NULL, ?, ?)",
                    (str(uuid4()), intake_id, candidate.model_dump_json(), timestamp, timestamp),
                )
            connection.execute(
                "UPDATE intakes SET status = 'ready', error = NULL, events = ?, updated_at = ? WHERE id = ?",
                (json.dumps(events), now(), intake_id),
            )
        return self.get_intake(intake_id)

    def _proposal(self, connection: sqlite3.Connection, row: sqlite3.Row | None) -> dict:
        if row is None:
            raise AppError("PROPOSAL_NOT_FOUND", "This proposal could not be found.", 404)
        result = dict(row)
        candidate = json.loads(result.pop("candidate"))
        result.update(candidate)
        result["conflict"] = None
        if result["status"] == "pending":
            if candidate["action"] == "update":
                current = connection.execute("SELECT version FROM skills WHERE id = ?", (candidate["skill_id"],)).fetchone()
                if current is None or current["version"] != candidate["base_version"]:
                    result["conflict"] = "The published skill changed or was deleted. Reject this draft and organize fresh notes against the current catalog."
            elif connection.execute("SELECT 1 FROM skills WHERE name_key = ?", (candidate["name"].casefold(),)).fetchone():
                result["conflict"] = "A published skill now uses this name. Rename the draft, or reject it and propose an update instead."
        return result

    def get_proposal(self, proposal_id: str) -> dict:
        with self.connection() as connection:
            return self._proposal(connection, connection.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone())

    def list_proposals(self) -> list[dict]:
        with self.connection() as connection:
            return [
                self._proposal(connection, row)
                for row in connection.execute("SELECT * FROM proposals ORDER BY created_at DESC")
            ]

    def _reviewable(self, connection: sqlite3.Connection, proposal_id: str, expected_revision: int) -> dict:
        proposal = self._proposal(connection, connection.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone())
        if proposal["status"] != "pending":
            raise AppError("PROPOSAL_CLOSED", "This proposal has already been approved or rejected.", 409)
        if proposal["revision"] != expected_revision:
            raise AppError("STALE_PROPOSAL", "This draft was edited elsewhere. Reload it before reviewing.", 409)
        return proposal

    def edit_proposal(self, proposal_id: str, value: ProposalEdit) -> dict:
        with self.connection(write=True) as connection:
            proposal = self._reviewable(connection, proposal_id, value.expected_revision)
            candidate = ProposalCandidate.model_validate({
                key: proposal[key] for key in ProposalCandidate.model_fields
            }).model_copy(update=value.model_dump(exclude={"expected_revision"}))
            connection.execute(
                "UPDATE proposals SET candidate = ?, revision = revision + 1, updated_at = ? WHERE id = ?",
                (candidate.model_dump_json(), now(), proposal_id),
            )
        return self.get_proposal(proposal_id)

    def reject_proposal(self, proposal_id: str, expected_revision: int) -> dict:
        with self.connection(write=True) as connection:
            self._reviewable(connection, proposal_id, expected_revision)
            connection.execute(
                "UPDATE proposals SET status = 'rejected', revision = revision + 1, updated_at = ? WHERE id = ?",
                (now(), proposal_id),
            )
        return self.get_proposal(proposal_id)

    def approve_proposal(self, proposal_id: str, expected_revision: int) -> dict:
        with self.connection(write=True) as connection:
            proposal = self._reviewable(connection, proposal_id, expected_revision)
            if proposal["conflict"]:
                raise AppError("STALE_PROPOSAL", proposal["conflict"], 409)
            fields = SkillInput.model_validate({key: proposal[key] for key in SkillInput.model_fields})
            if proposal["action"] == "create":
                skill = self._insert_skill(connection, fields)
            else:
                skill = self._update_skill(connection, proposal["skill_id"], fields, proposal["base_version"])
            connection.execute(
                "UPDATE proposals SET status = 'approved', published_skill_id = ?, revision = revision + 1, updated_at = ? WHERE id = ?",
                (skill.id, now(), proposal_id),
            )
        return {"skill": skill.model_dump(), "proposal": self.get_proposal(proposal_id)}

    def get_agent_binding(self, key: str) -> dict | None:
        with self.connection() as connection:
            row = connection.execute("SELECT name, version FROM agent_bindings WHERE key = ?", (key,)).fetchone()
            return dict(row) if row else None

    def save_agent_binding(self, key: str, name: str, version: str) -> None:
        with self.connection(write=True) as connection:
            connection.execute("INSERT OR REPLACE INTO agent_bindings VALUES (?, ?, ?)", (key, name, version))

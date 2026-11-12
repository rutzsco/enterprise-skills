from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SkillInput(StrictModel):
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(min_length=8, max_length=400)
    category: str = Field(default="General", min_length=2, max_length=40)
    guidance: str = Field(min_length=20, max_length=16000)
    owner: str = Field(default="Unassigned", min_length=2, max_length=100)
    applicability: str = Field(default="Review applicability before use.", min_length=2, max_length=500)
    references: dict[str, str] = Field(default_factory=dict, max_length=10)


class SkillEdit(SkillInput):
    expected_version: int = Field(strict=True, ge=1)


class Skill(SkillInput):
    id: str
    version: int
    created_at: str
    updated_at: str

    def metadata(self) -> dict:
        return self.model_dump(exclude={"guidance", "references"})


class RuleEvidence(StrictModel):
    rule: str = Field(min_length=5, max_length=1000)
    quotes: list[Annotated[str, Field(min_length=1, max_length=2000)]] = Field(min_length=1, max_length=6)


class NotesInput(StrictModel):
    title: str = Field(min_length=2, max_length=100)
    notes: str = Field(min_length=30, max_length=16000)


class ProposalCandidate(SkillInput):
    action: Literal["create", "update"]
    skill_id: str | None = None
    base_version: int | None = Field(default=None, strict=True, ge=1)
    rationale: str = Field(min_length=10, max_length=1000)
    evidence: list[Annotated[str, Field(min_length=1, max_length=2000)]] = Field(
        min_length=1, max_length=6
    )
    missing_information: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        default_factory=list, max_length=10
    )
    rules: list[RuleEvidence] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_target(self) -> "ProposalCandidate":
        if self.action == "update" and (not self.skill_id or self.base_version is None):
            raise ValueError("An update needs a skill_id and the version that was loaded.")
        if self.action == "create" and (self.skill_id is not None or self.base_version is not None):
            raise ValueError("A new skill must not specify a target or base version.")
        return self


class ProposalBatch(StrictModel):
    proposals: list[ProposalCandidate] = Field(min_length=1, max_length=5)


class ProposalEdit(SkillInput):
    expected_revision: int = Field(strict=True, ge=1)
    missing_information: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        default_factory=list, max_length=10
    )


class ReviewRequest(StrictModel):
    expected_revision: int = Field(strict=True, ge=1)
    reviewer_label: str = Field(default="Trusted demo reviewer (unverified)", min_length=2, max_length=100)


class ReleaseAction(StrictModel):
    action: Literal["rollback", "retire"]
    expected_version: int = Field(strict=True, ge=1)
    target_version: int | None = Field(default=None, strict=True, ge=1)
    reason: str = Field(min_length=10, max_length=1000)


class ChatInput(StrictModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str | None = Field(default=None, pattern=r"^[a-f0-9-]{36}$")


class DiscoverArguments(StrictModel):
    query: str = Field(default="", max_length=200)


class LoadArguments(StrictModel):
    skill_id: str = Field(min_length=1, max_length=100)

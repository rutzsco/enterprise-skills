import pytest

from server.errors import AppError
from server.models import NotesInput, ProposalCandidate, ProposalEdit, SkillEdit, SkillInput
from server.store import Store


def new_skill(name="Team handover"):
    return SkillInput(
        name=name, description="A synthetic handover procedure for this test.",
        category="Operations", guidance="At the end of a shift, document open incidents and the next owner.",
    )


def propose(store, *, action="create", target=None):
    notes = "At the end of a shift, document open incidents and the next owner."
    intake = store.create_intake(NotesInput(title="Handover notes", notes=notes))
    store.claim_intake(intake["id"])
    fields = new_skill().model_dump() if target is None else {
        key: getattr(target, key) for key in SkillInput.model_fields
    }
    candidate = ProposalCandidate(
        **fields, action=action, skill_id=target.id if target else None,
        base_version=target.version if target else None,
        rationale="Organize the supplied handover note into a reusable playbook.",
        evidence=[notes], missing_information=["The next owner is not named."],
    )
    result = store.finish_intake(intake["id"], [candidate], [])
    return result["proposals"][0]


def test_edits_and_deletions_survive_restart_and_discovery_is_metadata_only(store):
    original = store.get_skill("incident-response")
    edited = SkillEdit(
        **{**original.model_dump(include=set(SkillInput.model_fields)), "guidance": "New synthetic rule: notify the incident commander within three minutes."},
        expected_version=original.version,
    )
    updated = store.update_skill(original.id, edited)
    created = store.create_skill(new_skill())
    reopened = Store(store.path)
    reopened.initialize()
    assert reopened.get_skill(original.id).guidance == edited.guidance
    assert reopened.get_skill(original.id).version == updated.version == 2
    assert reopened.get_skill(created.id).name == created.name
    metadata = reopened.discover()
    assert all("guidance" not in item for item in metadata["skills"])
    assert reopened.discover("handover")["skills"][0]["id"] == created.id
    for item in metadata["skills"]:
        reopened.delete_skill(item["id"], item["version"])
    restarted_empty = Store(store.path)
    restarted_empty.initialize()
    assert restarted_empty.discover()["total"] == 0
    with pytest.raises(AppError, match="no longer exists"):
        restarted_empty.get_skill(original.id)


def test_stale_writes_and_name_collisions_do_not_overwrite(store):
    skill = store.create_skill(new_skill())
    edit = SkillEdit(**new_skill().model_dump(), expected_version=1)
    store.update_skill(skill.id, edit)
    with pytest.raises(AppError) as error:
        store.update_skill(skill.id, edit)
    assert error.value.code == "STALE_SKILL"
    with pytest.raises(AppError):
        store.delete_skill(skill.id, 1)
    with pytest.raises(AppError) as error:
        store.create_skill(new_skill("TEAM HANDOVER"))
    assert error.value.code == "DUPLICATE_SKILL"
    assert store.get_skill(skill.id).version == 2


def test_draft_edits_are_isolated_until_explicit_approval_and_persist(store):
    proposal = propose(store)
    assert store.discover("handover")["total"] == 0
    edited = store.edit_proposal(proposal["id"], ProposalEdit(
        **new_skill("Shift handover").model_dump(),
        expected_revision=1,
        missing_information=["The next owner still needs to be named."],
    ))
    reopened = Store(store.path)
    reopened.initialize()
    assert reopened.get_proposal(proposal["id"])["name"] == "Shift handover"
    assert reopened.discover("handover")["total"] == 0
    with pytest.raises(AppError) as error:
        reopened.approve_proposal(proposal["id"], 1)
    assert error.value.code == "STALE_PROPOSAL"
    approved = reopened.approve_proposal(proposal["id"], edited["revision"])
    assert reopened.get_skill(approved["skill"]["id"]).name == "Shift handover"
    assert approved["proposal"]["status"] == "approved"
    with pytest.raises(AppError):
        reopened.approve_proposal(proposal["id"], approved["proposal"]["revision"])


def test_pending_update_keeps_published_version_and_reject_has_no_effect(store):
    target = store.get_skill("software-purchasing")
    draft = propose(store, action="update", target=target)
    replacement = "The new synthetic threshold in these reviewed notes is $4,000."
    edited = store.edit_proposal(draft["id"], ProposalEdit(
        **{**target.model_dump(include=set(SkillInput.model_fields)), "guidance": replacement},
        expected_revision=1,
    ))
    assert store.get_skill(target.id).guidance == target.guidance
    result = store.approve_proposal(draft["id"], edited["revision"])
    assert result["skill"]["id"] == target.id
    assert store.get_skill(target.id).version == 2
    assert store.get_skill(target.id).guidance == replacement
    rejected = propose(store)
    store.reject_proposal(rejected["id"], 1)
    assert store.discover("handover")["total"] == 0
    with pytest.raises(AppError):
        store.approve_proposal(rejected["id"], 2)


@pytest.mark.parametrize("intervening_change", ["edit", "delete"])
def test_stale_update_proposal_cannot_replace_intervening_changes(store, intervening_change):
    target = store.get_skill("software-purchasing")
    draft = propose(store, action="update", target=target)
    if intervening_change == "edit":
        store.update_skill(target.id, SkillEdit(
            **target.model_dump(include=set(SkillInput.model_fields)), expected_version=1
        ))
    else:
        store.delete_skill(target.id, 1)
    assert store.get_proposal(draft["id"])["conflict"]
    with pytest.raises(AppError) as error:
        store.approve_proposal(draft["id"], 1)
    assert error.value.code == "STALE_PROPOSAL"
    assert store.get_proposal(draft["id"])["status"] == "pending"


def test_new_proposal_cannot_duplicate_newly_published_name(store):
    draft = propose(store)
    manual = store.create_skill(new_skill())
    with pytest.raises(AppError):
        store.approve_proposal(draft["id"], 1)
    assert store.get_skill(manual.id).version == 1
    assert store.discover("handover")["total"] == 1

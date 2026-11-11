import pytest
from django.db import IntegrityError, connection, transaction

from apps.core.models import AuditEvent
from apps.matching.models import SkillNode
from apps.matching.vocabulary import load_seed_pack
from apps.projects.models import (
    Importance,
    Project,
    RequirementSkill,
    RubricLocked,
    RubricVersion,
)
from apps.projects.services import add_skill, approve_rubric, next_version
from apps.tenancy.models import Role
from tests.factories.world import client_for, make_org, make_project, make_user

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture(autouse=True)
def vocabulary():
    load_seed_pack()


@pytest.fixture
def org():
    return make_org()


@pytest.fixture
def manager(org):
    return make_user(org, Role.DELIVERY_MANAGER)


@pytest.fixture
def client(manager):
    return client_for(manager)


def _project_with_draft(client):
    project = client.post("/api/projects/", {"name": "P", "start_date": "2026-12-01"}, JSON).json()
    client.post(f"/api/projects/{project['id']}/rubrics/", {}, JSON)
    return project["id"]


def _add(client, pid, skill="ENOVIA", weight=5, importance="REQUIRED", version=1, months=0):
    return client.post(
        f"/api/projects/{pid}/rubrics/{version}/skills/",
        {"skill": skill, "weight": weight, "importance": importance, "required_months": months},
        JSON,
    )


def test_project_starts_in_draft_in_the_users_org(client, org):
    """AC-PROJ-01"""
    response = client.post("/api/projects/", {"name": "New", "organisation": "x"}, JSON)
    assert response.status_code == 201
    assert response.json()["status"] == "DRAFT"
    assert Project.objects.get().organisation == org


def test_project_edit_and_close(client):
    """AC-PROJ-02"""
    pid = _project_with_draft(client)
    assert (
        client.patch(f"/api/projects/{pid}/", {"name": "Renamed"}, JSON).json()["name"] == "Renamed"
    )
    assert client.post(f"/api/projects/{pid}/close/", {}, JSON).json()["status"] == "CLOSED"
    assert client.patch(f"/api/projects/{pid}/", {"name": "Again"}, JSON).status_code == 409
    assert client.post(f"/api/projects/{pid}/rubrics/", {}, JSON).status_code == 409
    assert client.get(f"/api/projects/{pid}/").status_code == 200


@pytest.mark.parametrize("action", ["approve", "patch", "delete"])
def test_closed_project_refuses_remaining_rubric_writes(client, action):
    pid = _project_with_draft(client)
    _add(client, pid)
    item = RequirementSkill.objects.get()
    client.post(f"/api/projects/{pid}/close/", {}, JSON)

    if action == "approve":
        response = client.post(f"/api/projects/{pid}/rubrics/1/approve/", {}, JSON)
    else:
        response = getattr(client, action)(
            f"/api/projects/{pid}/rubrics/1/skills/{item.pk}/", {"weight": 9}, JSON
        )

    assert response.status_code == 409
    assert RequirementSkill.objects.get(pk=item.pk).weight == 5
    assert not RubricVersion.objects.get().is_approved


@pytest.mark.parametrize("months", [-1, "not-months", 1.5, True, 32768])
def test_rubric_rejects_invalid_required_months_without_saving(client, months):
    pid = _project_with_draft(client)
    response = _add(client, pid, months=months)
    assert response.status_code == 400
    assert not RequirementSkill.objects.exists()


@pytest.mark.parametrize("weight", [1.5, True, 2147483648])
def test_rubric_rejects_invalid_weight_without_saving(client, weight):
    pid = _project_with_draft(client)
    response = _add(client, pid, weight=weight)
    assert response.status_code == 400
    assert not RequirementSkill.objects.exists()


def test_rubric_skills_are_structured(client):
    """AC-PROJ-03"""
    pid = _project_with_draft(client)
    assert _add(client, pid).status_code == 201
    item = RequirementSkill.objects.get()
    assert item.skill.canonical_name == "ENOVIA"
    assert item.importance == Importance.REQUIRED
    assert item.weight == 5


@pytest.mark.parametrize("weight", [0, -3])
def test_zero_or_negative_weight_rejected_at_api(client, weight):
    """AC-PROJ-04"""
    pid = _project_with_draft(client)
    assert _add(client, pid, weight=weight).status_code == 400


def test_zero_weight_rejected_by_database(org):
    """AC-PROJ-04"""
    project = make_project(org, skills=(), approved=False)
    with pytest.raises(IntegrityError), transaction.atomic():
        RequirementSkill.objects.create(
            rubric=project.latest_rubric(),
            skill=SkillNode.objects.first(),
            importance=Importance.REQUIRED,
            weight=0,
        )


def test_empty_rubric_cannot_be_approved(client):
    """AC-PROJ-05"""
    pid = _project_with_draft(client)
    assert client.post(f"/api/projects/{pid}/rubrics/1/approve/", {}, JSON).status_code == 400
    assert RubricVersion.objects.get().status == "DRAFT"


def test_duplicate_skill_rejected_directly_and_by_alias(client):
    """AC-PROJ-06"""
    pid = _project_with_draft(client)
    assert _add(client, pid, skill="3DEXPERIENCE").status_code == 201
    assert _add(client, pid, skill="3DEXPERIENCE").status_code == 400
    assert _add(client, pid, skill="3DX").status_code == 400


def test_duplicate_skill_rejected_by_database(org):
    """AC-PROJ-06"""
    project = make_project(org, approved=False)
    item = project.latest_rubric().skills.first()
    with pytest.raises(IntegrityError), transaction.atomic():
        RequirementSkill.objects.create(
            rubric=item.rubric, skill=item.skill, importance=Importance.PREFERRED, weight=1
        )


def test_approval_locks_and_records_who(client, manager):
    """AC-PROJ-07"""
    pid = _project_with_draft(client)
    _add(client, pid)
    response = client.post(f"/api/projects/{pid}/rubrics/1/approve/", {}, JSON)
    assert response.status_code == 200
    rubric = RubricVersion.objects.get()
    assert rubric.is_approved
    assert rubric.approved_by == manager


def test_approved_rubric_refuses_change_at_every_layer(client, org):
    """AC-PROJ-08"""
    pid = _project_with_draft(client)
    _add(client, pid)
    client.post(f"/api/projects/{pid}/rubrics/1/approve/", {}, JSON)
    rubric = RubricVersion.objects.get()
    item = RequirementSkill.objects.get()
    assert _add(client, pid, skill="MQL").status_code == 409
    url = f"/api/projects/{pid}/rubrics/1/skills/{item.pk}/"
    assert client.patch(url, {"weight": 9}, JSON).status_code == 409
    assert client.delete(url).status_code == 409
    item.weight = 9
    with pytest.raises(RubricLocked):
        item.save()
    with pytest.raises(RubricLocked):
        item.delete()
    with pytest.raises(RubricLocked):
        rubric.save()
    with pytest.raises(RubricLocked):
        rubric.delete()
    with pytest.raises(RubricLocked):
        RequirementSkill.objects.filter(pk=item.pk).update(weight=9)
    with pytest.raises(RubricLocked):
        RequirementSkill.objects.filter(pk=item.pk).delete()
    with pytest.raises(RubricLocked):
        RubricVersion.objects.filter(pk=rubric.pk).update(version=7)
    with pytest.raises(RubricLocked):
        RequirementSkill.objects.bulk_update([item], ["weight"])
    new = RequirementSkill(
        rubric=rubric, skill=SkillNode.objects.last(), importance="PREFERRED", weight=1
    )
    with pytest.raises(RubricLocked):
        RequirementSkill.objects.bulk_create([new])
    item.refresh_from_db()
    assert item.weight == 5


@pytest.mark.parametrize("operation", ["save", "delete", "bulk_create", "bulk_update"])
def test_stale_rubric_instance_cannot_change_approved_skills(org, manager, operation):
    project = make_project(org, approved=False)
    stale = project.latest_rubric()
    item = stale.skills.select_related("rubric").first()
    approve_rubric(project.latest_rubric(), manager)

    with pytest.raises(RubricLocked):
        if operation == "save":
            item.weight = 99
            item.save()
        elif operation == "delete":
            item.delete()
        elif operation == "bulk_update":
            item.weight = 99
            RequirementSkill.objects.bulk_update([item], ["weight"])
        else:
            RequirementSkill.objects.bulk_create(
                [
                    RequirementSkill(
                        rubric=stale,
                        skill=SkillNode.objects.get(canonical_name="MQL"),
                        importance=Importance.PREFERRED,
                        weight=1,
                    )
                ]
            )


def test_queryset_cannot_move_a_draft_skill_into_an_approved_rubric(org):
    approved = make_project(org, skills=(("ENOVIA", "REQUIRED", 5),)).latest_rubric()
    draft = make_project(org, skills=(("MQL", "PREFERRED", 1),), approved=False).latest_rubric()
    with pytest.raises(RubricLocked):
        draft.skills.update(rubric=approved)
    assert draft.skills.count() == 1


def test_save_cannot_move_an_approved_skill_to_a_draft_rubric(org):
    approved = make_project(org).latest_rubric()
    draft = make_project(org, skills=(), approved=False).latest_rubric()
    item = approved.skills.first()
    item.rubric = draft
    with pytest.raises(RubricLocked):
        item.save()


def test_stale_rubric_instance_cannot_delete_approved_version(org, manager):
    project = make_project(org, approved=False)
    stale = project.latest_rubric()
    approve_rubric(project.latest_rubric(), manager)
    with pytest.raises(RubricLocked):
        stale.delete()


@pytest.mark.skipif(connection.vendor != "postgresql", reason="The trigger exists on PostgreSQL")
def test_postgres_trigger_refuses_raw_sql(org):
    """AC-PROJ-08"""
    item = make_project(org).latest_rubric().skills.first()
    with (
        pytest.raises(Exception, match="immutable"),
        transaction.atomic(),
        connection.cursor() as c,
    ):
        c.execute("UPDATE projects_requirementskill SET weight = 99 WHERE id = %s", [item.pk])


@pytest.mark.skipif(connection.vendor != "postgresql", reason="The trigger exists on PostgreSQL")
@pytest.mark.parametrize("operation", ["insert", "move"])
def test_postgres_trigger_refuses_adding_skills_to_approved_rubric(org, operation):
    approved = make_project(org, skills=(("ENOVIA", "REQUIRED", 5),)).latest_rubric()
    draft = make_project(org, skills=(("MQL", "PREFERRED", 1),), approved=False).latest_rubric()
    item = draft.skills.first()
    with (
        pytest.raises(Exception, match="immutable"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        if operation == "insert":
            cursor.execute(
                "INSERT INTO projects_requirementskill "
                "(rubric_id, skill_id, importance, weight, required_months) "
                "VALUES (%s, %s, 'PREFERRED', 1, 0)",
                [approved.pk, item.skill_id],
            )
        else:
            cursor.execute(
                "UPDATE projects_requirementskill SET rubric_id = %s WHERE id = %s",
                [approved.pk, item.pk],
            )


def test_editing_after_approval_creates_v2_and_v1_is_unchanged(org, manager):
    """AC-PROJ-09"""
    project = make_project(org, approver=manager)
    first = project.latest_rubric()
    before = list(first.skills.values_list("skill_id", "importance", "weight", "required_months"))
    draft = next_version(project)
    assert draft.version == 2
    add_skill(draft, "MQL", Importance.PREFERRED, 1)
    after = list(first.skills.values_list("skill_id", "importance", "weight", "required_months"))
    assert before == after
    assert draft.skills.count() == first.skills.count() + 1


def test_required_months_and_project_timing_are_recorded(client):
    """AC-PROJ-10"""
    project = client.post(
        "/api/projects/",
        {"name": "P", "start_date": "2026-12-01", "required_allocation_pct": 50},
        JSON,
    ).json()
    client.post(f"/api/projects/{project['id']}/rubrics/", {}, JSON)
    _add(client, project["id"], months=12)
    assert RequirementSkill.objects.get().required_months == 12
    stored = Project.objects.get()
    assert stored.required_allocation_pct == 50
    assert str(stored.start_date) == "2026-12-01"


def test_candidate_cannot_create_edit_or_approve(org):
    """AC-PROJ-14"""
    project = make_project(org, approved=False)
    client = client_for(make_user(org, Role.CANDIDATE))
    assert client.post("/api/projects/", {"name": "X"}, JSON).status_code == 403
    url = f"/api/projects/{project.pk}/rubrics/1/skills/"
    assert (
        client.post(url, {"skill": "MQL", "weight": 1, "importance": "REQUIRED"}, JSON).status_code
        == 403
    )
    assert (
        client.post(f"/api/projects/{project.pk}/rubrics/1/approve/", {}, JSON).status_code == 403
    )
    assert not project.latest_rubric().is_approved


def test_recruiter_cannot_approve(org):
    """AC-AUTH-15: role matrix for approval."""
    project = make_project(org, approved=False)
    client = client_for(make_user(org, Role.RECRUITER))
    assert (
        client.post(f"/api/projects/{project.pk}/rubrics/1/approve/", {}, JSON).status_code == 403
    )


def test_weight_change_writes_an_audit_event(client, manager):
    """AC-PROJ-16"""
    pid = _project_with_draft(client)
    _add(client, pid)
    item = RequirementSkill.objects.get()
    client.patch(f"/api/projects/{pid}/rubrics/1/skills/{item.pk}/", {"weight": 8}, JSON)
    event = AuditEvent.objects.get(action="rubric.weight_changed")
    assert event.actor == manager
    assert event.object_id == str(item.pk)


def test_approve_twice_is_refused(org, manager):
    """AC-PROJ-08"""
    rubric = make_project(org, approver=manager).latest_rubric()
    with pytest.raises(RubricLocked):
        approve_rubric(rubric, manager)

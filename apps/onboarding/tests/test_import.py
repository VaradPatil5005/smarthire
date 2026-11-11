import io
from decimal import Decimal

import pandas as pd
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.matching.services import create_run
from apps.onboarding.models import FieldChange, ImportBatch, ImportRow
from apps.onboarding.services import (
    ImportInvalid,
    confirm_import,
    preview_import,
    propose_mapping,
    resolve_queue_row,
    rollback_import,
)
from apps.talent.models import TalentProfile
from apps.tenancy.models import Role
from tests.factories.world import client_for, make_org, make_profile, make_project, make_user

pytestmark = pytest.mark.django_db
HEADER = "Emp ID,Emp Name,Primary Tech,Curr Proj %,Notice Pd,Email,Phone\n"


@pytest.fixture
def org():
    make_project(make_org())
    return make_org()


@pytest.fixture
def admin(org):
    return make_user(org, Role.ADMIN)


def _row(number, external=None, **kwargs):
    external = f"EMP-{number:03d}" if external is None else external
    name = kwargs.get("name", f"Fictional Person {number}")
    return f"{external},{name},{kwargs.get('skills', 'MQL')},{kwargs.get('alloc', '20')},,,\n"


def _rehearsal():
    """12 rows: 2 repeat an external ID, 1 lacks the mandatory ID."""
    rows = [_row(n) for n in range(1, 10)]
    rows.append(_row(10, external="EMP-DUP"))
    rows.append(_row(11, external="EMP-DUP"))
    rows.append(_row(12, external=""))
    return (HEADER + "".join(rows)).encode()


def _import(data, org, admin, source="SAP_HR", name="roster.csv"):
    return confirm_import(preview_import(name, data, source, org, admin))


def test_rehearsal_imports_9_and_withholds_3_with_reasons(org, admin):
    """AC-IMPORT-01"""
    batch = _import(_rehearsal(), org, admin)
    assert batch.insert_count == 9
    assert batch.withheld_count == 3
    assert TalentProfile.objects.for_org(org).count() == 9
    withheld = batch.rows.filter(state="WITHHELD")
    assert [r.row_number for r in withheld] == [10, 11, 12]
    assert all(r.reason for r in withheld)


def test_reimport_is_idempotent(org, admin):
    """AC-IMPORT-02"""
    _import(_rehearsal(), org, admin)
    changes = FieldChange.objects.count()
    second = _import(_rehearsal(), org, admin)
    assert (second.insert_count, second.update_count, second.unchanged_count) == (0, 0, 9)
    assert TalentProfile.objects.for_org(org).count() == 9
    assert FieldChange.objects.count() == changes


def test_batch_record_holds_id_digest_mapping_and_counts(org, admin):
    """AC-IMPORT-03"""
    batch = _import(_rehearsal(), org, admin)
    assert batch.pk
    assert len(batch.source_digest) == 64
    assert batch.mapping_version == 1
    assert batch.insert_count == 9
    assert batch.update_count == 0


def test_mapper_proposes_all_four_headers_and_writes_nothing_until_confirmed(org, admin):
    """AC-IMPORT-04"""
    mapping = propose_mapping(["Emp Name", "Primary Tech", "Curr Proj %", "Notice Pd"])
    assert set(mapping.values()) == {
        "display_name",
        "primary_skills",
        "allocation_pct",
        "notice_days",
    }
    batch = preview_import("r.csv", _rehearsal(), "SAP_HR", org, admin)
    assert batch.status == "PREVIEW"
    assert not TalentProfile.objects.for_org(org).exists()


def test_xlsx_import_works(org, admin):
    """AC-IMPORT-04"""
    frame = pd.DataFrame([{"Emp ID": "E1", "Emp Name": "Fictional One", "Curr Proj %": "10"}])
    buffer = io.BytesIO()
    frame.to_excel(buffer, index=False)
    batch = _import(buffer.getvalue(), org, admin, name="roster.xlsx")
    assert batch.insert_count == 1


def test_contact_fields_are_kept_apart_from_skills(org, admin):
    """AC-IMPORT-05"""
    data = (HEADER + "E1,Fictional One,MQL,10,,a@example.test,+91 1\n").encode()
    _import(data, org, admin)
    profile = TalentProfile.objects.get()
    assert (profile.email, profile.phone) == ("a@example.test", "+91 1")
    assert [c.skill.canonical_name for c in profile.claims.all()] == ["MQL"]


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b"Wrong,Headers\n1,2\n", id="bad-headers"),
        pytest.param("Emp ID,Emp Name\n1,café\n".encode("latin-1"), id="bad-encoding"),
    ],
)
def test_bad_files_are_refused_and_nothing_written(org, admin, data):
    """AC-IMPORT-06"""
    with pytest.raises(ImportInvalid):
        preview_import("r.csv", data, "SAP_HR", org, admin)
    assert not ImportBatch.objects.exists()


def test_bad_rows_get_a_per_row_report(org, admin):
    """AC-IMPORT-06"""
    data = (HEADER + "E1,,MQL,10,,,\nE2,Fictional,MQL,500,,,\n").encode()
    batch = preview_import("r.csv", data, "SAP_HR", org, admin)
    reasons = {r.row_number: r.reason for r in batch.rows.all()}
    assert "name" in reasons[1]
    assert "allocation" in reasons[2]
    assert not TalentProfile.objects.for_org(org).exists()


@pytest.mark.parametrize(
    ("existing", "row"),
    [
        ({"email": "shared@example.test"}, ",Different Name,,,,shared@example.test,\n"),
        ({"phone": "+91 5"}, ",Different Name,,,,,+91 5\n"),
        ({"name": "Same Name"}, ",Same Name,,,,,\n"),
    ],
    ids=["email", "phone", "name"],
)
def test_no_key_identity_match_goes_to_the_queue_not_a_merge(org, admin, existing, row):
    """AC-IMPORT-07"""
    make_profile(org, **existing)
    batch = _import((HEADER + row).encode(), org, admin)
    queued = batch.rows.get()
    assert queued.state == "QUEUED"
    assert queued.candidate_profile is not None
    assert TalentProfile.objects.for_org(org).count() == 1


@pytest.mark.parametrize(
    ("action", "state", "profiles"),
    [("LINK", "LINKED", 1), ("CREATE", "CREATED", 2), ("SKIP", "SKIPPED", 1)],
)
def test_queue_actions(org, admin, action, state, profiles):
    """AC-IMPORT-08"""
    make_profile(org, phone="+91 5")
    batch = _import((HEADER + ",Colleague,,,,,+91 5\n").encode(), org, admin)
    row = resolve_queue_row(batch.rows.get(), action)
    assert row.state == state
    assert TalentProfile.objects.for_org(org).count() == profiles


def test_queue_created_profile_is_archived_when_batch_is_rolled_back(org, admin):
    """AC-IMPORT-08, AC-IMPORT-15: queue-created people belong to the batch too."""
    existing = make_profile(org, phone="+91 5")
    batch = _import((HEADER + ",Colleague,,,,,+91 5\n").encode(), org, admin)
    resolved = resolve_queue_row(batch.rows.get(), "CREATE")
    assert batch.changes.filter(profile=resolved.profile, created=True).exists()

    report = rollback_import(batch)

    resolved.profile.refresh_from_db()
    existing.refresh_from_db()
    assert resolved.profile.archived_at is not None
    assert existing.archived_at is None
    assert report["archived"] == 1


@pytest.mark.parametrize("state", ["PREVIEW", "ROLLED_BACK"])
def test_queue_resolution_requires_a_confirmed_batch(org, admin, state):
    """AC-IMPORT-04, AC-IMPORT-08: preview and rolled-back batches cannot create people."""
    make_profile(org, phone="+91 5")
    batch = preview_import(
        "r.csv", (HEADER + ",Colleague,,,,,+91 5\n").encode(), "SAP_HR", org, admin
    )
    row = batch.rows.get()
    if state == "ROLLED_BACK":
        confirm_import(batch)
        rollback_import(batch)

    with pytest.raises(ImportInvalid, match="confirmed batch"):
        resolve_queue_row(row, "CREATE")

    assert TalentProfile.objects.for_org(org).count() == 1


def test_stale_queue_row_cannot_create_a_second_profile(org, admin):
    """AC-IMPORT-08: replaying an old row object is still a resolved decision."""
    make_profile(org, phone="+91 5")
    batch = _import((HEADER + ",Colleague,,,,,+91 5\n").encode(), org, admin)
    row = batch.rows.get()
    stale = ImportRow.objects.get(pk=row.pk)
    resolve_queue_row(row, "CREATE")

    with pytest.raises(ImportInvalid, match="not waiting"):
        resolve_queue_row(stale, "CREATE")

    assert TalentProfile.objects.for_org(org).count() == 2


@pytest.mark.parametrize("operation", ["confirm", "rollback"])
def test_stale_batch_cannot_repeat_a_completed_transition(org, admin, operation):
    """AC-IMPORT-02, AC-IMPORT-15: stale objects do not bypass persisted batch status."""
    batch = preview_import("r.csv", _rehearsal(), "SAP_HR", org, admin)
    stale = ImportBatch.objects.get(pk=batch.pk)
    confirmed = confirm_import(batch)
    if operation == "confirm":
        with pytest.raises(ImportInvalid, match="already confirmed"):
            confirm_import(stale)
    else:
        stale = ImportBatch.objects.get(pk=confirmed.pk)
        rollback_import(confirmed)
        with pytest.raises(ImportInvalid, match="Only a confirmed"):
            rollback_import(stale)


@pytest.mark.parametrize("state", ["PREVIEW", "ROLLED_BACK"])
def test_queue_list_does_not_offer_unconfirmed_batches(org, admin, state):
    """AC-IMPORT-04: only confirmed batches can offer queue resolution."""
    make_profile(org, phone="+91 5")
    batch = preview_import(
        "r.csv", (HEADER + ",Colleague,,,,,+91 5\n").encode(), "SAP_HR", org, admin
    )
    if state == "ROLLED_BACK":
        confirm_import(batch)
        rollback_import(batch)
    assert client_for(admin).get("/api/imports/queue/").json() == []


def test_changed_row_updates_with_a_change_log(org, admin):
    """AC-IMPORT-09"""
    _import((HEADER + "E1,Fictional One,MQL,10,,,\n").encode(), org, admin)
    batch = _import((HEADER + "E1,Fictional One,MQL,30,,,\n").encode(), org, admin)
    assert batch.update_count == 1
    change = batch.changes.get()
    assert (change.field, change.previous_value, change.imported_value) == (
        "allocation_pct",
        10,
        30,
    )
    assert TalentProfile.objects.get().allocation_pct == 30


def test_same_key_in_two_orgs_makes_two_profiles_and_batches_are_scoped(org, admin):
    """AC-IMPORT-10"""
    other = make_org()
    other_admin = make_user(other, Role.ADMIN)
    data = (HEADER + "E1,Fictional One,MQL,10,,,\n").encode()
    batch = _import(data, org, admin)
    _import(data, other, other_admin)
    assert TalentProfile.objects.filter(external_id="E1").count() == 2
    assert client_for(other_admin).get(f"/api/imports/{batch.pk}/").status_code == 404


def test_formula_and_script_in_imported_fields_are_safe(org, admin):
    """AC-IMPORT-11"""
    data = (
        HEADER + 'E1,"=HYPERLINK(""x"")",MQL,10,,,\nE2,<script>alert(1)</script>,MQL,10,,,\n'
    ).encode()
    _import(data, org, admin)
    client = client_for(admin)
    page = client.get("/profiles/").content.decode()
    assert "<script>alert(1)" not in page
    assert "&lt;script&gt;" in page
    project = make_project(org, approver=admin)
    run, _created = create_run(project, "k", {}, admin, org)
    body = client.get(f"/api/runs/{run.pk}/export.csv").content.decode()
    assert "'=HYPERLINK" in body


@pytest.mark.parametrize("role", [Role.CANDIDATE, Role.RECRUITER, Role.DELIVERY_MANAGER])
def test_only_admin_can_import(org, role):
    """AC-IMPORT-12"""
    client = client_for(make_user(org, role))
    upload = SimpleUploadedFile("r.csv", _rehearsal())
    response = client.post("/api/imports/", {"file": upload, "source_system": "SAP_HR"})
    assert response.status_code == 403
    assert client.get("/imports/").status_code == 403


def test_import_api_preview_confirm_and_rollback(org, admin):
    """AC-IMPORT-01"""
    client = client_for(admin)
    upload = SimpleUploadedFile("r.csv", _rehearsal())
    created = client.post("/api/imports/", {"file": upload, "source_system": "SAP_HR"}).json()
    assert created["withheld_count"] == 3
    url = f"/api/imports/{created['id']}/"
    confirmed = client.post(f"{url}confirm/", {}, "application/json").json()
    assert confirmed["insert_count"] == 9
    assert client.post(f"{url}confirm/", {}, "application/json").status_code == 409
    assert client.post(f"{url}rollback/", {}, "application/json").json()["archived"] == 9


def test_change_log_has_field_values_and_time(org, admin):
    """AC-IMPORT-13"""
    batch = _import((HEADER + "E1,Fictional One,MQL,10,,,\n").encode(), org, admin)
    change = batch.changes.get(field="allocation_pct")
    assert change.previous_value is None
    assert change.imported_value == 10
    assert change.changed_at is not None


def test_rollback_keeps_a_later_manual_edit(org, admin):
    """AC-IMPORT-14, AC-IMPORT-17"""
    data = (HEADER + "E1,Fictional One,MQL,20,,,\n").encode()
    first = _import(data, org, admin)
    assert _import(data, org, admin).unchanged_count == 1
    profile = TalentProfile.objects.get()
    update = _import((HEADER + "E1,Renamed Person,MQL,30,,,\n").encode(), org, admin)
    profile.refresh_from_db()
    profile.allocation_pct = 60
    profile.save()
    report = rollback_import(update)
    profile.refresh_from_db()
    assert profile.allocation_pct == 60
    assert profile.display_name == "Fictional One"
    assert report["kept_later_edits"] == 1
    assert first.status == "CONFIRMED"


def test_rollback_reverses_one_batch_and_archives_what_it_created(org, admin):
    """AC-IMPORT-15"""
    keep = _import((HEADER + "E1,Fictional One,MQL,20,,,\n").encode(), org, admin)
    remove = _import((HEADER + "E2,Fictional Two,MQL,20,,,\n").encode(), org, admin)
    report = rollback_import(remove)
    assert report["archived"] == 1
    assert TalentProfile.objects.get(external_id="E2").archived_at is not None
    assert TalentProfile.objects.get(external_id="E1").archived_at is None
    keep.refresh_from_db()
    assert keep.status == "CONFIRMED"
    with pytest.raises(ImportInvalid):
        rollback_import(remove)


def test_rolled_back_profile_can_be_imported_again(org, admin):
    """AC-IMPORT-15"""
    data = (HEADER + "E1,Fictional One,MQL,20,,,\n").encode()
    rollback_import(_import(data, org, admin))
    _import(data, org, admin)
    assert TalentProfile.objects.get().archived_at is None


def test_imported_skills_earn_nothing_until_confirmed(org, admin):
    """AC-IMPORT-16"""
    project = make_project(org, approver=admin, skills=(("MQL", "REQUIRED", 10),))
    _import((HEADER + "E1,Fictional One,MQL,20,,,\n").encode(), org, admin)
    run, _created = create_run(project, "k", {}, admin, org)
    result = run.results.get()
    assert result.coverage == Decimal("0.00")
    assert result.contributions.get().label == "Provisional"


def test_import_screens_work(org, admin):
    """AC-IMPORT-08"""
    client = client_for(admin)
    make_profile(org, phone="+91 5")
    upload = SimpleUploadedFile("r.csv", (HEADER + ",Colleague,,,,,+91 5\n").encode())
    response = client.post("/imports/", {"file": upload, "source_system": "SAP_HR"})
    assert response.status_code == 302
    batch = ImportBatch.objects.get()
    assert b"Confirm these counts" in client.get(f"/imports/{batch.pk}/").content
    client.post(f"/imports/{batch.pk}/confirm/")
    row = ImportRow.objects.get()
    assert b"Link to existing" in client.get("/imports/queue/").content
    assert (
        client.post(
            f"/api/imports/queue/{row.pk}/resolve/", {"action": "SKIP"}, "application/json"
        ).json()["state"]
        == "SKIPPED"
    )
    assert b"Nothing is waiting" in client.get("/imports/queue/").content
    client.post(f"/imports/{batch.pk}/rollback/")
    batch.refresh_from_db()
    assert batch.status == "ROLLED_BACK"

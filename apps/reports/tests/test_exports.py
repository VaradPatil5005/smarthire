import csv
import io
from datetime import date

import pytest
from django.utils import timezone
from openpyxl import load_workbook

from apps.matching.services import create_run
from apps.reports.services import dashboard_totals, neutralise, utilisation_summary
from apps.talent.models import ResourceType
from apps.tenancy.models import Membership, Role
from tests.factories.world import (
    accept_spans,
    client_for,
    make_org,
    make_profile,
    make_project,
    make_user,
    upload_fixture,
)

pytestmark = pytest.mark.django_db
GROUPS = [None, "READY", "NEEDS_CLARIFICATION", "UNMET"]
TYPES = [None, "INTERNAL", "EXTERNAL"]
PREFIXES = ["=", "+", "-", "@", "\t", "\r"]


@pytest.fixture
def world():
    org = make_org()
    reviewer = make_user(org)
    project = make_project(org, approver=reviewer, start_date=date(2026, 12, 1))
    ready = make_profile(org, name="Ready Person", notice_days=0)
    upload_fixture("demo_candidate_b_corrected", ready, reviewer)
    accept_spans(ready, reviewer)
    make_profile(org, name="Applicant Person")
    make_profile(
        org,
        name="Bench Person",
        resource_type=ResourceType.INTERNAL,
        allocation_pct=20,
        available_from=date(2026, 11, 1),
    )
    run, _created = create_run(project, "k", {"run_date": "2026-11-08"}, reviewer, org)
    return org, reviewer, run


def _csv_rows(content):
    return list(csv.reader(io.StringIO(content.decode())))


def _query(group, resource_type):
    pairs = [("group", group), ("resource_type", resource_type)]
    return "&".join(f"{k}={v}" for k, v in pairs if v)


@pytest.mark.parametrize("group", GROUPS)
@pytest.mark.parametrize("resource_type", TYPES)
def test_dashboard_totals_equal_export_rows_for_all_12_filters(world, group, resource_type):
    """AC-DASH-13"""
    _org, reviewer, run = world
    query = _query(group, resource_type)
    response = client_for(reviewer).get(f"/api/runs/{run.pk}/export.csv?{query}")
    assert (
        len(_csv_rows(response.content)) - 1 == dashboard_totals(run, group, resource_type)["total"]
    )
    api = client_for(reviewer).get(f"/api/runs/{run.pk}/dashboard/?{query}").json()
    assert api["total"] == dashboard_totals(run, group, resource_type)["total"]


def test_csv_and_xlsx_hold_the_filtered_rows_with_screen_values(world):
    """AC-DASH-14"""
    _org, reviewer, run = world
    client = client_for(reviewer)
    rows = _csv_rows(client.get(f"/api/runs/{run.pk}/export.csv?resource_type=INTERNAL").content)
    assert [r[2] for r in rows[1:]] == ["Bench Person"]
    workbook = load_workbook(
        io.BytesIO(client.get(f"/api/runs/{run.pk}/export.xlsx?resource_type=INTERNAL").content)
    )
    sheet = workbook.active
    assert [row[2].value for row in sheet.iter_rows(min_row=2)] == ["Bench Person"]
    screen = client.get(f"/runs/{run.pk}/?resource_type=INTERNAL").content.decode()
    assert "Bench Person" in screen
    assert "Ready Person" not in screen


@pytest.mark.parametrize("prefix", PREFIXES)
@pytest.mark.parametrize("leading", ["", "  "], ids=["no-space", "leading-spaces"])
def test_formula_cells_are_neutralised_in_csv_and_xlsx(world, prefix, leading):
    """AC-DASH-15: 6 prefixes x 2 forms x 2 formats = 24 cases"""
    org, reviewer, _run = world
    name = f"{leading}{prefix}cmd|calc"
    project = make_project(org, approver=reviewer)
    make_profile(org, name=name)
    run, _created = create_run(project, "formula", {}, reviewer, org)
    client = client_for(reviewer)
    rows = _csv_rows(client.get(f"/api/runs/{run.pk}/export.csv").content)
    cell = next(r[2] for r in rows if r[2].lstrip(" '").startswith(prefix) or "cmd" in r[2])
    assert cell.startswith("'")
    sheet = load_workbook(io.BytesIO(client.get(f"/api/runs/{run.pk}/export.xlsx").content)).active
    cells = [row[2] for row in sheet.iter_rows(min_row=2) if "cmd" in str(row[2].value)]
    assert cells
    assert cells[0].data_type == "s"


@pytest.mark.parametrize("value", ['=HYPERLINK("http://x")', "=cmd"])
def test_named_formula_payloads_are_neutralised(value):
    """AC-DASH-15"""
    assert neutralise(value).startswith("'")


def test_plain_values_and_numbers_are_untouched():
    """AC-DASH-14"""
    assert neutralise("Asha") == "Asha"
    assert neutralise(70.0) == 70.0


def test_export_denied_for_candidate_revoked_and_404_for_other_org(world):
    """AC-DASH-17"""
    org, _reviewer, run = world
    url = f"/api/runs/{run.pk}/export.csv"
    assert client_for(make_user(org, Role.CANDIDATE)).get(url).status_code == 403
    revoked = make_user(org)
    client = client_for(revoked)
    Membership.objects.filter(user=revoked).update(revoked_at=timezone.now())
    assert client.get(url).status_code == 403
    assert client_for(make_user(make_org())).get(url).status_code == 404


def test_screen_api_and_export_read_one_result(world):
    """AC-DASH-18"""
    _org, reviewer, run = world
    client = client_for(reviewer)
    result = run.results.get(profile__display_name="Ready Person")
    api = client.get(f"/api/runs/{run.pk}/results/").json()["results"]
    from_api = next(r for r in api if r["name"] == "Ready Person")
    rows = _csv_rows(client.get(f"/api/runs/{run.pk}/export.csv").content)
    from_csv = next(r for r in rows if r[2] == "Ready Person")
    screen = client.get(f"/runs/{run.pk}/").content.decode()
    assert from_api["coverage"] == str(result.coverage) == "100.00"
    assert float(from_csv[4]) == float(result.coverage)
    assert from_csv[0] == result.get_review_group_display()
    assert str(result.coverage) in screen
    assert str(result.staffing_fit) in screen


def test_utilisation_reports_mean_with_denominator(world):
    """AC-DASH-19"""
    org, reviewer, _run = world
    make_profile(
        org,
        resource_type=ResourceType.INTERNAL,
        allocation_pct=60,
        available_from=date(2026, 11, 1),
    )
    summary = utilisation_summary(org)
    assert summary == {
        "consultants": 2,
        "known": 2,
        "unknown": 0,
        "mean_allocation_pct": 40.0,
        "on_bench": 2,
    }
    api = client_for(reviewer).get("/api/reports/utilisation/").json()
    assert api["consultants"] == 2
    assert b"internal consultants" in client_for(reviewer).get("/utilisation/").content


def test_utilisation_with_no_consultants():
    """AC-DASH-19"""
    assert utilisation_summary(make_org())["consultants"] == 0

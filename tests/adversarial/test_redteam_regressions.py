"""Regressions for the T5.1 red-team campaign. Each one reproduced before it was fixed."""

import io
import zipfile
import zlib

import pymupdf
import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.test import Client, override_settings

from apps.ingestion import services as ingestion
from apps.ingestion.scanner import Limits, ScanFailure, scan_pdf
from apps.matching.models import SkillNode
from apps.matching.services import ReviewRefused, create_run, record_skill_decision
from apps.matching.vocabulary import load_seed_pack
from apps.onboarding.services import (
    ImportInvalid,
    confirm_import,
    preview_import,
    resolve_queue_row,
)
from apps.reports.services import neutralise
from apps.talent.models import TalentProfile
from apps.tenancy.models import Role
from tests.factories.world import (
    accept_spans,
    client_for,
    make_org,
    make_profile,
    make_project,
    make_user,
)

LIMITS = Limits(10, 3370, 100 * 1024 * 1024, 1.5, 4000)
BLACK = (0, 0, 0)
WHITE = (1, 1, 1)
KEYWORD = "ENOVIA configuration"


def _page():
    doc = pymupdf.open()
    return doc, doc.new_page()


def _scan(doc, tmp_path):
    path = tmp_path / "attack.pdf"
    doc.save(path)
    return scan_pdf(str(path), LIMITS)


def _black_on_black_overhang(page):
    page.draw_rect(pymupdf.Rect(71, 110, 190, 123), color=None, fill=BLACK)
    page.insert_text((72, 120), KEYWORD, fontsize=11, color=BLACK)


def _box_over_keyword_at_end_of_line(page):
    prefix = "Delivered many fictional things over the years with "
    page.insert_text((72, 120), prefix + KEYWORD, fontsize=9, color=BLACK)
    start = 72 + pymupdf.get_text_length(prefix, fontsize=9)
    page.draw_rect(pymupdf.Rect(start, 110, 540, 123), color=None, fill=WHITE)


def _white_in_white_box_in_frame(page):
    page.draw_rect(pymupdf.Rect(60, 100, 400, 135), color=None, fill=(0.2, 0.3, 0.6))
    page.draw_rect(pymupdf.Rect(70, 108, 390, 126), color=None, fill=WHITE)
    page.insert_text((72, 120), KEYWORD, fontsize=11, color=WHITE)


def _decoy_over_white_box(page):
    page.insert_text((72, 120), KEYWORD, fontsize=11, color=BLACK)
    page.draw_rect(pymupdf.Rect(70, 108, 400, 126), color=None, fill=WHITE)
    page.insert_text((72, 120), "Decoy words on top", fontsize=11, color=BLACK)


def _image_over_text(page):
    page.insert_text((72, 120), KEYWORD, fontsize=11, color=BLACK)
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 32, 32), False)
    pixmap.set_rect(pixmap.irect, (40, 90, 200))
    page.insert_image(pymupdf.Rect(70, 108, 400, 126), pixmap=pixmap, keep_proportion=False)


def _faint_opacity(page):
    page.insert_text((72, 120), KEYWORD, fontsize=11, color=BLACK, fill_opacity=0.11)


BYPASSES = [
    _black_on_black_overhang,
    _box_over_keyword_at_end_of_line,
    _white_in_white_box_in_frame,
    _decoy_over_white_box,
    _image_over_text,
    _faint_opacity,
]


@pytest.mark.parametrize("attack", BYPASSES, ids=lambda f: f.__name__.lstrip("_"))
def test_hidden_keyword_never_reaches_visible_text(attack, tmp_path):
    """AC-UPLOAD-26, finding 1"""
    doc, page = _page()
    page.insert_text((72, 80), "Work Experience", fontsize=12)
    attack(page)
    result = _scan(doc, tmp_path)
    assert result["status"] == "FLAGGED"
    assert KEYWORD not in result["visible_text"]
    assert "Work Experience" in result["visible_text"]


def test_covering_one_keyword_keeps_the_rest_of_the_line(tmp_path):
    """AC-UPLOAD-27: exclusion is per word, so honest text on the line survives."""
    doc, page = _page()
    _box_over_keyword_at_end_of_line(page)
    result = _scan(doc, tmp_path)
    assert "Delivered many fictional things" in result["visible_text"]
    audit = next(a for a in result["audits"] if a["vector"] == "OCCLUDED_OR_CLIPPED")
    assert "ENOVIA" in audit["text"]


@pytest.mark.django_db
def test_hidden_text_earns_no_credit_even_if_a_reviewer_accepts_everything():
    """AC-MATCH-23, finding 1, end to end"""
    load_seed_pack()
    org = make_org()
    reviewer = make_user(org)
    project = make_project(org, approver=reviewer)
    attacked = make_profile(org)
    doc, page = _page()
    page.insert_text((72, 80), "Work Experience", fontsize=12)
    _black_on_black_overhang(page)
    uploaded = SimpleUploadedFile("a.pdf", doc.tobytes())
    version = ingestion.receive_upload(uploaded, attacked, org, None)
    ingestion.scan_stored_version(version.pk)
    accept_spans(attacked, reviewer)
    run, _created = create_run(project, "k", {}, reviewer, org)
    assert run.results.get(profile=attacked).coverage == 0


def test_highlight_and_underline_do_not_flag_honest_text(tmp_path):
    """AC-UPLOAD-14: a transparent highlight or a thin rule over text is not hiding it."""
    doc, page = _page()
    page.insert_text((72, 120), KEYWORD, fontsize=11, color=BLACK)
    page.draw_rect(pymupdf.Rect(70, 110, 200, 123), color=None, fill=(1, 1, 0), fill_opacity=0.4)
    page.insert_text((72, 160), "Underlined line", fontsize=11, color=BLACK)
    page.draw_line((72, 162), (150, 162), color=BLACK, width=0.5)
    result = _scan(doc, tmp_path)
    assert result["status"] == "CLEAN"
    assert KEYWORD in result["visible_text"]


@pytest.mark.django_db
def test_login_throttle_cannot_be_bypassed_by_padding_the_username():
    """AC-AUTH-04, finding 2"""
    cache.clear()
    make_user(make_org(), username="alice")
    for _ in range(6):
        Client().post("/login/", {"username": "alice", "password": "wrong"})
    good = "test-only-password-1"
    assert Client().post("/login/", {"username": "alice", "password": good}).status_code == 200
    assert Client().post("/login/", {"username": "alice    ", "password": good}).status_code == 200


@pytest.mark.django_db
def test_nobody_reviews_their_own_profile():
    """AC-MATCH-26, finding 3"""
    load_seed_pack()
    org = make_org()
    recruiter = make_user(org, Role.RECRUITER)
    mine = make_profile(org, owner=recruiter)
    skill = SkillNode.objects.get(canonical_name="MQL")
    with pytest.raises(ReviewRefused, match="your own"):
        record_skill_decision(mine, skill, "VERIFIED", "Me", recruiter, org, "INTERVIEW")


def _xlsx_bomb():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"0" * (60 * 1024 * 1024))
    return buffer.getvalue()


@pytest.mark.django_db
def test_xlsx_bomb_is_refused_before_inflating():
    """AC-IMPORT-06, finding 4"""
    org = make_org()
    with pytest.raises(ImportInvalid, match="too much data"):
        preview_import("bomb.xlsx", _xlsx_bomb(), "HR", org, make_user(org, Role.ADMIN))


@pytest.mark.parametrize(
    "filters", ["[/ASCIIHexDecode /FlateDecode]", "[/FlateDecode /FlateDecode]", "/LZWDecode"]
)
def test_filter_chains_that_cannot_be_measured_fail_closed(filters, tmp_path):
    """AC-UPLOAD-04, finding 5"""
    doc, page = _page()
    xref = doc.get_new_xref()
    doc.update_object(xref, "<</Length 0>>")
    doc.update_stream(xref, b"payload", new=False, compress=False)
    doc.xref_set_key(xref, "Filter", filters)
    doc.xref_set_key(page.xref, "FixtureData", f"{xref} 0 R")
    with pytest.raises(ScanFailure) as failure:
        _scan(doc, tmp_path)
    assert failure.value.code == "TOO_MUCH_DATA"


def test_corrupt_flate_stream_fails_closed(tmp_path):
    """AC-UPLOAD-05, finding 5"""
    doc, page = _page()
    xref = doc.get_new_xref()
    doc.update_object(xref, "<</Length 0>>")
    doc.update_stream(xref, zlib.compress(b"x") + b"junk"[::-1], new=False, compress=False)
    doc.update_stream(xref, b"not deflate data", new=False, compress=False)
    doc.xref_set_key(xref, "Filter", "/FlateDecode")
    doc.xref_set_key(page.xref, "FixtureData", f"{xref} 0 R")
    with pytest.raises(ScanFailure) as failure:
        _scan(doc, tmp_path)
    assert failure.value.code == "CORRUPT"


def test_huge_declared_image_is_counted(tmp_path):
    """AC-UPLOAD-04, finding 5"""
    doc, page = _page()
    xref = doc.get_new_xref()
    doc.update_object(xref, "<</Type/XObject/Subtype/Image/Width 20000/Height 20000/Length 0>>")
    doc.update_stream(xref, b"x", new=False, compress=False)
    doc.xref_set_key(page.xref, "FixtureData", f"{xref} 0 R")
    with pytest.raises(ScanFailure) as failure:
        _scan(doc, tmp_path)
    assert failure.value.code == "TOO_MUCH_DATA"


HEADER = "Emp ID,Emp Name,Curr Proj %,Available From,Email,Designation\n"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "row",
    ["E1,Name,10,not-a-date,,\n", "E1,Name,²,,,\n"],
    ids=["bad-date", "superscript-digit"],
)
def test_one_bad_row_is_withheld_and_good_rows_still_import(row):
    """AC-IMPORT-06, finding 7"""
    org = make_org()
    admin = make_user(org, Role.ADMIN)
    data = (HEADER + row + "E2,Good Person,20,2026-12-01,,\n").encode()
    batch = confirm_import(preview_import("r.csv", data, "HR", org, admin))
    assert batch.insert_count == 1
    assert batch.withheld_count == 1


@pytest.mark.django_db
def test_queue_row_with_bad_values_cannot_cause_an_error():
    """AC-IMPORT-08, finding 7"""
    org = make_org()
    admin = make_user(org, Role.ADMIN)
    make_profile(org, name="Same Name")
    batch = preview_import("r.csv", (HEADER + ",Same Name,999,,,\n").encode(), "HR", org, admin)
    row = batch.rows.get()
    assert row.state == "WITHHELD"
    with pytest.raises(ImportInvalid):
        resolve_queue_row(row, "CREATE")


@pytest.mark.django_db
def test_reimport_with_fewer_columns_does_not_wipe_fields():
    """AC-IMPORT-09, finding 8"""
    org = make_org()
    admin = make_user(org, Role.ADMIN)
    first = (HEADER + "E1,Fictional One,10,2026-12-01,a@example.test,Architect\n").encode()
    confirm_import(preview_import("r.csv", first, "HR", org, admin))
    second = b"Emp ID,Emp Name\nE1,Renamed Person\n"
    confirm_import(preview_import("r.csv", second, "HR", org, admin))
    profile = TalentProfile.objects.get()
    assert profile.display_name == "Renamed Person"
    assert (profile.email, profile.title, profile.allocation_pct) == (
        "a@example.test",
        "Architect",
        10,
    )


@pytest.mark.django_db
def test_rolling_back_a_reimport_archives_again():
    """AC-IMPORT-15"""
    from apps.onboarding.services import rollback_import

    org = make_org()
    admin = make_user(org, Role.ADMIN)
    data = (HEADER + "E1,Fictional One,10,,,\n").encode()
    rollback_import(confirm_import(preview_import("r.csv", data, "HR", org, admin)))
    second = confirm_import(preview_import("r.csv", data, "HR", org, admin))
    assert TalentProfile.objects.get().archived_at is None
    rollback_import(second)
    assert TalentProfile.objects.get().archived_at is not None


@pytest.mark.django_db
@pytest.mark.parametrize("months", ["abc", -5, 40000])
def test_bad_months_is_a_400_not_a_500(months):
    """AC-CAND-05"""
    load_seed_pack()
    org = make_org()
    candidate = make_user(org, Role.CANDIDATE)
    make_profile(org, owner=candidate)
    response = client_for(candidate).post(
        "/api/profiles/me/claims/", {"skill": "MQL", "months": months}, "application/json"
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_other_bad_input_never_reaches_a_500():
    """AC-CAND-03, AC-RANK-02: the remaining low findings."""
    load_seed_pack()
    org = make_org()
    user = make_user(org, Role.DELIVERY_MANAGER)
    client = client_for(user)
    client.raise_request_exception = False
    person = make_profile(org)
    project = make_project(org, approver=user)
    json_type = "application/json"
    bad_notice = {"display_name": "X", "title": "Y", "notice_days": 99999}
    assert client.post("/api/profiles/", bad_notice, json_type).status_code == 400
    junk = {"span_id": "junk", "outcome": "ACCEPT", "reason": "r"}
    assert client.post(f"/api/profiles/{person.pk}/evidence/", junk, json_type).status_code == 404
    url = f"/api/projects/{project.pk}/runs/"
    bad_date = {"run_date": "junk"}
    assert client.post(url, bad_date, json_type, HTTP_IDEMPOTENCY_KEY="k").status_code == 400
    assert client.get("/bench/?free_by=junk").status_code == 200
    assert (
        client.post("/projects/", {"name": "P", "required_allocation_pct": "900"}).status_code
        == 200
    )
    assert (
        client.post(
            "/profiles/",
            {
                "display_name": "X",
                "title": "Y",
                "available_from": "junk",
                "resource_type": "INTERNAL",
            },
        ).status_code
        == 200
    )


@pytest.mark.parametrize("value", ["\n=cmd", " =cmd", "＝cmd", "  \n+cmd", "＠cmd"])
def test_formula_variants_are_neutralised(value):
    """AC-DASH-15"""
    assert neutralise(value).startswith("'")


@pytest.mark.django_db
def test_force_seed_needs_its_own_password(monkeypatch):
    """AC-PROJ-15"""
    monkeypatch.delenv("DEMO_PASSWORD", raising=False)
    with override_settings(DEBUG=False), pytest.raises(CommandError, match="DEMO_PASSWORD"):
        call_command("seed_demo", force=True, verbosity=0)


def test_production_turns_the_ocr_job_on_by_default():
    """AC-UPLOAD-30"""
    from config.settings import base

    assert base.OCR_DIFF_ENABLED is True

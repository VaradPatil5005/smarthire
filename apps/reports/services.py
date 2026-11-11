"""Dashboards and exports. They read stored results, so they always match the screen and the API."""

import csv
import io
import unicodedata

import pandas as pd
from openpyxl import Workbook

from apps.matching.api import filtered_results
from apps.matching.models import ReviewGroup
from apps.talent.models import ResourceType, TalentProfile

_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")
EXPORT_HEADERS = [
    "Group",
    "Rank",
    "Name",
    "Type",
    "Coverage",
    "Staffing fit",
    "Mandatory coverage",
    "Missing must-haves",
    "Matched skills",
    "Unresolved skills",
    "Missing skills",
]


def neutralise(value):
    """A CSV cell a spreadsheet would run as a formula starts with ', also after leading spaces."""
    if not isinstance(value, str):
        return value
    # Also through newlines, NBSP and fullwidth forms: spreadsheets differ on what they trim.
    start = unicodedata.normalize("NFKC", value).lstrip(" \n\x0b\x0c\xa0")
    if start[:1] in _DANGEROUS and start[:1]:
        return "'" + value
    return value


def _skills(result, bucket):
    return "; ".join(
        c.skill.canonical_name for c in result.contributions.all() if c.bucket == bucket
    )


def export_rows(run, group=None, resource_type=None, q=None, with_evidence=False):
    results = filtered_results(run, group, resource_type, q, with_evidence)
    for result in results.prefetch_related("contributions__skill"):
        yield [
            result.get_review_group_display(),
            result.rank,
            result.name_snapshot,
            result.resource_type_snapshot,
            float(result.coverage),
            float(result.staffing_fit),
            float(result.mandatory_coverage),
            result.missing_must_haves,
            _skills(result, "matched"),
            _skills(result, "unresolved"),
            _skills(result, "missing"),
        ]


def export_csv(run, group=None, resource_type=None, q=None, with_evidence=False) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_HEADERS)
    for row in export_rows(run, group, resource_type, q, with_evidence):
        writer.writerow([neutralise(cell) for cell in row])
    return buffer.getvalue()


def export_xlsx(run, group=None, resource_type=None, q=None, with_evidence=False) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Shortlist"
    sheet.append(EXPORT_HEADERS)
    for row in export_rows(run, group, resource_type, q, with_evidence):
        sheet.append(row)
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, str):
                # Assigned text starting with = would become a formula. This forces a plain string.
                cell.data_type = "s"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def dashboard_totals(run, group=None, resource_type=None, q=None, with_evidence=False) -> dict:
    results = filtered_results(run, group, resource_type, q, with_evidence)
    frame = pd.DataFrame(list(results.values("review_group", "coverage")))
    counts = dict.fromkeys(ReviewGroup.values, 0)
    if not frame.empty:
        for name, count in frame["review_group"].value_counts().items():
            counts[name] = int(count)
    return {"total": int(sum(counts.values())), **counts}


def utilisation_summary(organisation) -> dict:
    consultants = TalentProfile.objects.for_org(organisation).filter(
        resource_type=ResourceType.INTERNAL, archived_at__isnull=True
    )
    frame = pd.DataFrame(list(consultants.values("allocation_pct")))
    count = len(frame)
    known = frame["allocation_pct"].dropna().astype(float) if count else frame
    summary = {"consultants": count, "known": len(known), "unknown": count - len(known)}
    if known.empty:
        return {**summary, "mean_allocation_pct": None, "on_bench": 0}
    # Unknown capacity is shown as unknown. It is never presented as free capacity.
    return {
        **summary,
        "mean_allocation_pct": round(float(known.sum()) / len(known), 2),
        "on_bench": int((known < 100).sum()),
    }

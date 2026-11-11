"""Bulk import. Match only on a source key. Never merge on phone, email or name."""

import hashlib
import io
import json
import logging
import zipfile
from collections import Counter
from datetime import date

import pandas as pd
from django.db import transaction
from django.utils import timezone

from apps.matching.vocabulary import resolve_skill
from apps.talent.models import ClaimProvenance, ResourceType, SkillClaim, TalentProfile

from .models import BatchStatus, FieldChange, ImportBatch, ImportRow, RowState, SourceRecord

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
MAX_XLSX_INFLATED_BYTES = 50 * 1024 * 1024
MAX_XLSX_RATIO = 100
PROFILE_FIELDS = (
    "display_name",
    "title",
    "email",
    "phone",
    "allocation_pct",
    "available_from",
    "notice_days",
)
SYNONYMS = {
    "external_id": ("emp id", "employee id", "external id", "source id", "id", "emp no"),
    "display_name": ("emp name", "employee name", "name", "full name"),
    "title": ("designation", "title", "role", "job title"),
    "primary_skills": ("primary tech", "primary skill", "primary skills", "skills", "tech"),
    "allocation_pct": ("curr proj %", "allocation", "allocation %", "current allocation"),
    "available_from": ("available from", "free from", "roll off"),
    "notice_days": ("notice pd", "notice period", "notice", "notice days"),
    "email": ("email", "mail", "email id"),
    "phone": ("phone", "mobile", "contact number"),
}


MAPPABLE_FIELDS = tuple(SYNONYMS)
REQUIRED_FIELDS = {"external_id", "display_name"}


class ImportInvalid(Exception):
    pass


def propose_mapping(headers):
    """Header → field, by normalised name. The data owner sees this before anything is written."""
    mapping = {}
    for header in headers:
        normal = str(header).strip().lower()
        for field, names in SYNONYMS.items():
            if normal in names:
                mapping[str(header)] = field
                break
    return mapping


def _check_xlsx_is_not_a_bomb(data):
    """Read the sizes the archive declares and refuse before anything is inflated."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
    except zipfile.BadZipFile as error:
        raise ImportInvalid("This file could not be read as CSV or XLSX.") from error
    total = sum(entry.file_size for entry in entries)
    compressed = sum(entry.compress_size for entry in entries) or 1
    if total > MAX_XLSX_INFLATED_BYTES or total / compressed > MAX_XLSX_RATIO:
        raise ImportInvalid("This workbook expands to too much data. Save a smaller copy.")


def _read_frame(name, data):
    if len(data) > MAX_FILE_BYTES:
        raise ImportInvalid("This file is over the 5 MB limit.")
    try:
        if name.lower().endswith(".xlsx"):
            _check_xlsx_is_not_a_bomb(data)
            frame = pd.read_excel(
                io.BytesIO(data), dtype=str, engine="openpyxl", nrows=MAX_ROWS + 1
            )
        else:
            frame = pd.read_csv(io.BytesIO(data), dtype=str, encoding="utf-8", nrows=MAX_ROWS + 1)
    except ImportInvalid:
        raise
    except UnicodeDecodeError as error:
        raise ImportInvalid(
            "This file is not UTF-8 text. Save it as UTF-8 and try again."
        ) from error
    except Exception as error:
        raise ImportInvalid("This file could not be read as CSV or XLSX.") from error
    if len(frame) > MAX_ROWS:
        raise ImportInvalid(f"This file has more than {MAX_ROWS} rows.")
    return frame.fillna("")


def _row_problems(row):
    problems = []
    if not row.get("display_name"):
        problems.append("name is missing")
    for field, upper in (("allocation_pct", 100), ("notice_days", 3650)):
        value = row.get(field, "")
        if value and not (value.isascii() and value.isdigit() and int(value) <= upper):
            problems.append(f"{field} is not valid")
    if row.get("available_from"):
        try:
            date.fromisoformat(row["available_from"])
        except ValueError:
            problems.append("available_from is not a date, YYYY-MM-DD")
    return problems


def _identity_match(organisation, row):
    profiles = TalentProfile.objects.for_org(organisation).filter(archived_at__isnull=True)
    for field, lookup in (
        ("email", "email__iexact"),
        ("phone", "phone"),
        ("display_name", "display_name__iexact"),
    ):
        value = row.get(field, "")
        if value:
            match = profiles.filter(**{lookup: value}).first()
            if match:
                return match, field
    return None, ""


def row_hash(row) -> str:
    return hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()


def mapping_is_complete(mapping):
    return set(mapping.values()) >= REQUIRED_FIELDS


def _build_rows(batch):
    """Validate every source row under the batch's current mapping."""
    mapping = batch.mapping
    records = [dict(zip(batch.source_rows[0], row, strict=True)) for row in batch.source_rows[1:]]
    rows = [
        {mapping[col]: str(record.get(col, "")).strip() for col in mapping} for record in records
    ]
    counts = Counter(row["external_id"] for row in rows if row["external_id"])
    batch.rows.all().delete()
    for number, row in enumerate(rows, start=1):
        state, reason, candidate = _classify(batch.organisation, row, counts)
        ImportRow.objects.create(
            organisation=batch.organisation,
            batch=batch,
            row_number=number,
            external_id=row["external_id"],
            row_hash=row_hash(row),
            data=row,
            state=state,
            reason=reason,
            candidate_profile=candidate,
        )
    batch.withheld_count = batch.rows.filter(state=RowState.WITHHELD).count()
    batch.queued_count = batch.rows.filter(state=RowState.QUEUED).count()
    batch.save(update_fields=["withheld_count", "queued_count"])


@transaction.atomic
def preview_import(name, data, source_system, organisation, actor, strict=True) -> ImportBatch:
    """Dry run: validate every row, write no profile. The data owner signs off on the counts.

    With strict off, a file whose columns could not all be recognised still gets a batch, with no
    rows yet, so a person can map them on the screen.
    """
    frame = _read_frame(name, data)
    mapping = propose_mapping(frame.columns)
    complete = mapping_is_complete(mapping)
    if strict and not complete:
        raise ImportInvalid("The file needs an ID column and a name column.")
    batch = ImportBatch.objects.create(
        organisation=organisation,
        source_system=source_system,
        source_digest=hashlib.sha256(data).hexdigest(),
        mapping=mapping,
        # Headers first, then rows, as lists: jsonb reorders object keys, and order matters here.
        source_rows=[[str(c) for c in frame.columns], *frame.astype(str).values.tolist()],
        created_by=actor,
    )
    if complete:
        _build_rows(batch)
    return batch


def source_headers(batch):
    return batch.source_rows[0] if batch.source_rows else list(batch.mapping)


@transaction.atomic
def remap_import(batch, mapping) -> ImportBatch:
    """Apply a person's corrected mapping and validate again. Nothing is written to profiles."""
    if batch.status != BatchStatus.PREVIEW:
        raise ImportInvalid("Only a batch still in preview can be remapped.")
    fields = list(mapping.values())
    if any(field not in MAPPABLE_FIELDS for field in fields):
        raise ImportInvalid("Choose a field from the list.")
    if len(fields) != len(set(fields)):
        raise ImportInvalid("Each field can be used by one column only.")
    if not mapping_is_complete(mapping):
        raise ImportInvalid("Map one column to the ID and one to the name.")
    batch.mapping = mapping
    batch.mapping_version += 1
    batch.save(update_fields=["mapping", "mapping_version"])
    _build_rows(batch)
    return batch


def _classify(organisation, row, counts):
    external_id = row["external_id"]
    if external_id:
        pass
    elif _row_problems({**row, "display_name": row.get("display_name") or "unnamed"}):
        return RowState.WITHHELD, "A value in this row is not valid.", None
    if not external_id:
        match, field = _identity_match(organisation, row)
        if match:
            return RowState.QUEUED, f"No ID, but {field} matches an existing profile.", match
        return RowState.WITHHELD, "The mandatory ID is missing.", None
    if counts[external_id] > 1:
        return RowState.WITHHELD, f"ID {external_id} appears {counts[external_id]} times.", None
    problems = _row_problems(row)
    if problems:
        return RowState.WITHHELD, "; ".join(problems) + ".", None
    return RowState.READY, "", None


def _values_from_row(row):
    return {
        "display_name": row.get("display_name", ""),
        "title": row.get("title") or "Imported profile",
        "email": row.get("email", ""),
        "phone": row.get("phone", ""),
        "allocation_pct": int(row["allocation_pct"]) if row.get("allocation_pct") else None,
        "available_from": row.get("available_from") or None,
        "notice_days": int(row["notice_days"]) if row.get("notice_days") else None,
    }


def _as_json(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _add_claims(profile, row):
    """Imported skills are claims with no evidence: they earn nothing until confirmed."""
    for name in row.get("primary_skills", "").replace(";", ",").split(","):
        skill = resolve_skill(name) if name.strip() else None
        if skill:
            SkillClaim.objects.get_or_create(
                profile=profile,
                skill=skill,
                defaults={"provenance": ClaimProvenance.IMPORT, "confirmed": False},
            )


def _create_profile(batch, values):
    allocated = values["allocation_pct"] is not None or values["available_from"] is not None
    profile = TalentProfile.objects.create(
        organisation=batch.organisation,
        source_system=batch.source_system,
        resource_type=ResourceType.INTERNAL if allocated else ResourceType.EXTERNAL,
        **values,
    )
    profile.refresh_from_db()
    for field in PROFILE_FIELDS:
        FieldChange.objects.create(
            organisation=batch.organisation,
            batch=batch,
            profile=profile,
            field=field,
            previous_value=None,
            imported_value=_as_json(getattr(profile, field)),
            created=True,
        )
    return profile


def _apply_row(batch, row_record):
    row = row_record.data
    profile = (
        TalentProfile.objects.for_org(batch.organisation)
        .filter(source_system=batch.source_system, external_id=row_record.external_id)
        .first()
    )
    values = _values_from_row(row)
    if profile is None:
        profile = _create_profile(batch, {**values, "external_id": row_record.external_id})
        state = RowState.IMPORTED
    else:
        record = SourceRecord.objects.filter(profile=profile).first()
        if record and record.row_hash == row_record.row_hash and profile.archived_at is None:
            row_record.state = RowState.UNCHANGED
            row_record.profile = profile
            row_record.save(update_fields=["state", "profile"])
            return RowState.UNCHANGED
        changed = []
        if profile.archived_at is not None:
            # Re-importing brings the profile back, so rolling this batch back archives it again.
            FieldChange.objects.create(
                organisation=batch.organisation,
                batch=batch,
                profile=profile,
                field="display_name",
                previous_value=None,
                imported_value=profile.display_name,
                created=True,
            )
        for field, value in values.items():
            if field not in row:
                continue  # A column this file does not have says nothing about the field.
            current = _as_json(getattr(profile, field))
            if current != value:
                FieldChange.objects.create(
                    organisation=batch.organisation,
                    batch=batch,
                    profile=profile,
                    field=field,
                    previous_value=current,
                    imported_value=value,
                )
                setattr(profile, field, value)
                changed.append(field)
        profile.archived_at = None
        profile.save()
        state = RowState.UPDATED
    SourceRecord.objects.update_or_create(
        profile=profile,
        defaults={
            "organisation": batch.organisation,
            "row_hash": row_record.row_hash,
            "batch": batch,
        },
    )
    _add_claims(profile, row)
    row_record.state = state
    row_record.profile = profile
    row_record.save(update_fields=["state", "profile"])
    return state


@transaction.atomic
def confirm_import(batch) -> ImportBatch:
    batch = ImportBatch.objects.for_org(batch.organisation).select_for_update().get(pk=batch.pk)
    if batch.status != BatchStatus.PREVIEW:
        raise ImportInvalid("This batch was already confirmed.")
    if not mapping_is_complete(batch.mapping):
        raise ImportInvalid("Map one column to the ID and one to the name first.")
    outcome = Counter(_apply_row(batch, row) for row in batch.rows.filter(state=RowState.READY))
    batch.insert_count = outcome[RowState.IMPORTED]
    batch.update_count = outcome[RowState.UPDATED]
    batch.unchanged_count = outcome[RowState.UNCHANGED]
    batch.status = BatchStatus.CONFIRMED
    batch.source_rows = []
    batch.confirmed_at = timezone.now()
    batch.save()
    logger.info(
        "import confirmed batch=%s inserted=%s updated=%s withheld=%s",
        batch.pk,
        batch.insert_count,
        batch.update_count,
        batch.withheld_count,
    )
    return batch


@transaction.atomic
def rollback_import(batch) -> dict:
    """Revert a field only if it still equals the imported value, so later edits survive.

    Profiles the batch created are archived. Nothing is deleted (CLAUDE.md §9).
    """
    batch = ImportBatch.objects.for_org(batch.organisation).select_for_update().get(pk=batch.pk)
    if batch.status != BatchStatus.CONFIRMED:
        raise ImportInvalid("Only a confirmed batch can be rolled back.")
    reverted = 0
    kept = 0
    archived = 0
    changes = list(batch.changes.select_related("profile").order_by("-changed_at", "-pk"))
    for change in changes:
        if change.created:
            continue
        profile = change.profile
        current = _as_json(getattr(profile, change.field))
        if current == change.imported_value:
            setattr(profile, change.field, change.previous_value)
            profile.save(update_fields=[change.field, "updated_at"])
            reverted += 1
        else:
            kept += 1
    created_ids = {c.profile_id for c in changes if c.created}
    for profile in TalentProfile.objects.for_org(batch.organisation).filter(pk__in=created_ids):
        edited = [
            c
            for c in changes
            if c.profile_id == profile.pk
            and c.created
            and _as_json(getattr(profile, c.field)) != c.imported_value
        ]
        kept += len(edited)
        profile.archived_at = timezone.now()
        profile.save(update_fields=["archived_at", "updated_at"])
        archived += 1
    SourceRecord.objects.filter(batch=batch).delete()
    batch.status = BatchStatus.ROLLED_BACK
    batch.rolled_back_at = timezone.now()
    batch.save(update_fields=["status", "rolled_back_at"])
    return {"reverted": reverted, "kept_later_edits": kept, "archived": archived}


@transaction.atomic
def resolve_queue_row(row, action, actor=None):
    """A person decides: link to the existing profile, create a new person, or skip."""
    # All batch transitions take this lock first, so rollback and a queue action cannot interleave.
    batch = ImportBatch.objects.for_org(row.organisation).select_for_update().get(pk=row.batch_id)
    if batch.status != BatchStatus.CONFIRMED:
        raise ImportInvalid("Queue actions require a confirmed batch.")
    row = ImportRow.objects.for_org(row.organisation).select_for_update().get(pk=row.pk)
    if row.state != RowState.QUEUED:
        raise ImportInvalid("This row is not waiting for review.")
    if action == "LINK":
        row.state = RowState.LINKED
        row.profile = row.candidate_profile
    elif action == "CREATE":
        values = _values_from_row(row.data)
        row.profile = _create_profile(batch, values)
        _add_claims(row.profile, row.data)
        row.state = RowState.CREATED
    elif action == "SKIP":
        row.state = RowState.SKIPPED
    else:
        raise ImportInvalid("Choose link, create or skip.")
    row.save(update_fields=["state", "profile"])
    return row

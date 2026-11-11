"""Inspect evaluation denominators and ensure evaluation never creates credited evidence."""

import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.matching.models import EvidenceSpan, ReviewDecision
from apps.matching.vocabulary import load_seed_pack

pytestmark = pytest.mark.django_db


def test_evaluation_reports_synthetic_scope_and_does_not_credit_anyone():
    load_seed_pack()
    output = StringIO()
    call_command("evaluate_skill_extraction", stdout=output)
    report = json.loads(output.getvalue())
    assert report["label_source"] == "Developer-authored synthetic snippets"
    assert report["cases"] == 24
    assert len(report["case_results"]) == report["cases"]
    totals = report["totals"]
    assert totals["true_positive"] + totals["false_negative"] == totals["expected"]
    assert totals["true_positive"] + totals["false_positive"] == totals["proposed"]
    assert 0 <= report["proposal_precision"] <= 1
    assert 0 <= report["proposal_recall"] <= 1
    assert report["limitations"]
    assert not EvidenceSpan.objects.exists()
    assert not ReviewDecision.objects.exists()


def test_evaluation_requires_an_existing_dictionary():
    with pytest.raises(CommandError, match="dictionary"):
        call_command("evaluate_skill_extraction")

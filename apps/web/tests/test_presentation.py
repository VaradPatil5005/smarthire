"""Presentation regressions that do not require a database."""

from django.template.loader import render_to_string


def test_unchanged_evidence_level_explains_changed_skill_credit():
    change = {
        "skill": "ENOVIA",
        "old_e": "1.00",
        "new_e": "1.00",
        "old_credit": "0.2500",
        "new_credit": "1.0000",
        "reason": "Confirmed twelve months of delivery work.",
    }
    text = render_to_string("web/_change_reason.html", {"change": change})
    assert "skill credit 0.2500" in text
    assert "1.0000" in text
    assert change["reason"] in text
    assert "e 1.00" not in text


def test_older_change_records_keep_their_evidence_level_explanation():
    change = {
        "skill": "ENOVIA",
        "old_e": "0.00",
        "new_e": "1.00",
        "reason": "Accepted visible evidence.",
    }
    text = render_to_string("web/_change_reason.html", {"change": change})
    assert "e 0.00" in text
    assert "1.00" in text
    assert change["reason"] in text
    assert "skill credit" not in text

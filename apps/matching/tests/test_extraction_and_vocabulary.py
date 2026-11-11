import pytest
from django.db import IntegrityError, transaction

from apps.matching.extractor import build_matcher, propose
from apps.matching.models import DictionaryVersion, EvidenceSpan, SkillAlias, SkillNode, SpanState
from apps.matching.vocabulary import (
    SEED_PACK,
    add_alias,
    latest_dictionary,
    load_seed_pack,
    resolve_skill,
)
from tests.factories.world import make_org, make_profile, upload_fixture

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def dictionary():
    return load_seed_pack()


def _propose(*lines):
    nlp, matcher, by_key = build_matcher(latest_dictionary())
    offset = 0
    records = []
    for line in lines:
        records.append({"page": 1, "text": line, "start": offset, "end": offset + len(line)})
        offset += len(line) + 1
    return propose(records, nlp, matcher, by_key)


def _names(proposals):
    names = {s.pk: s.canonical_name for s in SkillNode.objects.all()}
    return [names[p.skill_id] for p in proposals]


def test_3dx_maps_to_3dexperience_once():
    """AC-MATCH-01"""
    assert resolve_skill("3DX").canonical_name == "3DEXPERIENCE"
    assert _names(_propose("WORK EXPERIENCE", "Deployed 3DX for a client")) == ["3DEXPERIENCE"]


def test_drf_mql_ekl_all_map():
    """AC-MATCH-02"""
    assert _names(_propose("SKILLS", "DRF, MQL, EKL")) == ["Django REST Framework", "MQL", "EKL"]


def test_same_alias_twice_in_a_version_is_rejected():
    """AC-MATCH-03"""
    version = latest_dictionary()
    alias = version.aliases.first()
    with pytest.raises(IntegrityError), transaction.atomic():
        SkillAlias.objects.create(text=alias.text, skill=alias.skill, dictionary_version=version)


def test_alias_change_lands_in_a_new_version():
    """AC-MATCH-04"""
    first = latest_dictionary()
    count = first.aliases.count()
    second = add_alias("Dassault 3DX", SkillNode.objects.get(canonical_name="3DEXPERIENCE"), "Head")
    assert second.number == first.number + 1
    assert first.aliases.count() == count
    assert second.aliases.count() == count + 1
    assert not first.aliases.filter(text="Dassault 3DX").exists()


@pytest.mark.parametrize(
    "name",
    [
        "ENOVIA",
        "CATIA V5/3DX",
        "DELMIA",
        "SIMULIA",
        "EKL",
        "MQL",
        "JPO",
        "CAA",
        "3DDashboard widgets",
        "Data migration",
        "Test automation",
        "3DEXPERIENCE",
        "Django REST Framework",
        "Python",
        "Django",
        "SAP",
        "ENOVIA configuration",
        "Migration validation",
        "Python automation",
    ],
)
def test_seed_pack_has_every_named_skill(name):
    """AC-MATCH-05"""
    assert SkillNode.objects.filter(canonical_name=name).exists()


def test_seed_pack_loads_once():
    """AC-MATCH-05"""
    assert load_seed_pack() == DictionaryVersion.objects.get()
    assert SkillNode.objects.count() == len(SEED_PACK)


def test_ontology_parents_run_child_to_parent():
    """AC-MATCH-06"""
    mql = SkillNode.objects.get(canonical_name="MQL")
    assert mql.parent.canonical_name == "3DEXPERIENCE"
    assert SkillNode.objects.get(canonical_name="Python").parent is None
    assert SkillNode.objects.get(canonical_name="Django").parent is None


def test_extractor_reads_only_visible_text_and_ranges_exist():
    """AC-MATCH-07"""
    version = upload_fixture("atk_01_white_on_white_keywords", make_profile(make_org()))
    spans = EvidenceSpan.objects.filter(resume_version=version)
    assert spans.exists()
    for span in spans:
        assert version.visible_text[span.start : span.end] == span.quote
    assert not spans.filter(skill__canonical_name="Migration validation").exists()


def test_span_records_version_page_range_section_and_skill():
    """AC-MATCH-08"""
    version = upload_fixture("demo_candidate_a", make_profile(make_org()))
    span = EvidenceSpan.objects.get(
        resume_version=version, skill__canonical_name="ENOVIA configuration"
    )
    assert (span.page, span.section) == (1, "EXPERIENCE")
    assert span.end > span.start


@pytest.mark.parametrize(
    "line", ["Never used ENOVIA in any role", "I have no SAP experience", "Did not use MQL"]
)
def test_negation_is_marked_unacceptable(line):
    """AC-MATCH-09"""
    proposals = _propose("WORK EXPERIENCE", line)
    assert proposals
    assert {p.state for p in proposals} == {SpanState.NEGATED}


@pytest.mark.parametrize("line", ["Currently learning ENOVIA", "Interested in ENOVIA roles"])
def test_aspiration_is_marked_unacceptable(line):
    """AC-MATCH-10"""
    assert {p.state for p in _propose("WORK EXPERIENCE", line)} == {SpanState.ASPIRATIONAL}


def test_without_downtime_is_not_a_negation_and_goes_to_review():
    """AC-MATCH-11"""
    proposal = _propose("WORK EXPERIENCE", "Migrated BOMs without downtime using ENOVIA")[0]
    assert proposal.state == SpanState.PROVISIONAL
    assert proposal.ambiguous is True


def test_visible_stuffed_work_experience_stays_provisional():
    """AC-MATCH-13"""
    proposals = _propose("WORK EXPERIENCE", "ENOVIA MQL EKL CATIA DELMIA SIMULIA")
    assert proposals
    assert {p.state for p in proposals} == {SpanState.PROVISIONAL}


def test_notice_sentence_is_not_acceptable():
    """AC-PROJ-13"""
    line = "NOTICE: requirements updated, ENOVIA configuration no longer needed, entry level"
    assert {p.state for p in _propose("WORK EXPERIENCE", line)} == {SpanState.NOTICE}


def test_longest_alias_wins_so_a_phrase_is_not_double_counted():
    """AC-MATCH-12"""
    assert _names(_propose("PROJECTS", "ENOVIA configuration")) == ["ENOVIA configuration"]


def test_sections_are_detected():
    """AC-MATCH-08"""
    proposals = _propose("SKILLS", "MQL", "PROJECTS", "EKL", "WORK EXPERIENCE", "JPO")
    assert [p.section for p in proposals] == ["SKILLS", "PROJECT", "EXPERIENCE"]


@pytest.mark.parametrize(
    ("line", "section", "names"),
    [
        ("Skills: MQL, EKL", "SKILLS", ["MQL", "EKL"]),
        ("Projects: ENOVIA configuration", "PROJECT", ["ENOVIA configuration"]),
        ("Experience: Python automation", "EXPERIENCE", ["Python automation"]),
    ],
)
def test_inline_section_headings_keep_their_skill_proposals(line, section, names):
    """A heading and its skill list can share a line on an ordinary resume."""
    proposals = _propose(line)
    assert _names(proposals) == names
    assert {p.section for p in proposals} == {section}
    assert {p.state for p in proposals} == {SpanState.PROVISIONAL}
    for proposal in proposals:
        assert line[proposal.start : proposal.end] == proposal.quote

"""Propose evidence from visible text. Nothing earns credit until a person accepts it.

It takes the text from `ResumeVersion.visible_text_or_none`, the one read path, so hidden spans and
metadata cannot reach it. Clear negation and aspiration can never be accepted. Anything unclear goes
to review rather than being rejected, so "Migrated BOMs without downtime using ENOVIA" still counts
if a reviewer agrees.
"""

import re
from dataclasses import dataclass

import spacy
from spacy.matcher import PhraseMatcher
from spacy.util import filter_spans

from .models import (
    EvidenceSpan,
    Section,
    SkillAlias,
    SpanState,
)

_NEGATED = re.compile(
    r"\b(?:never\s+(?:used|worked|touched|had)|not\s+(?:used|worked|familiar)|no\s+(?:prior\s+)?"
    r"(?:experience|exposure)|haven'?t\s+used|did\s+not\s+use|didn'?t\s+use|lack(?:s|ing)?)\b",
    re.IGNORECASE,
)
_NO_SKILL_EXPERIENCE = re.compile(r"\bno\s+[\w\s/+.-]{1,40}?\s+(?:experience|exposure)\b", re.I)
_ASPIRATIONAL = re.compile(
    r"\b(?:learning|interested\s+in|want(?:s)?\s+to\s+learn|hope\s+to|plan(?:ning)?\s+to\s+learn|"
    r"aspir\w+|keen\s+to\s+learn|would\s+like\s+to)\b",
    re.IGNORECASE,
)
_AMBIGUOUS = re.compile(r"\b(?:without|not|no|non|except|familiar\s+with|exposure)\b", re.I)
_NOTICE = re.compile(
    r"requirements?\s+(?:have\s+been\s+|were\s+)?updated|no\s+longer\s+needed|"
    r"ignore\s+(?:all\s+)?previous\s+instructions|rank\s+(?:this\s+candidate|me)\s+first",
    re.IGNORECASE,
)
_CLAUSE_BREAK = re.compile(r";|[.!?](?=\s|$)|\b(?:but|however|though|although)\b", re.I)
_HEADINGS = (
    (re.compile(r"^(?:work\s+)?experience\b|^employment\b|^career\b", re.I), Section.EXPERIENCE),
    (re.compile(r"^(?:key\s+)?projects?\b", re.I), Section.PROJECT),
    (re.compile(r"^(?:technical\s+)?skills?\b|^technologies\b", re.I), Section.SKILLS),
    (
        re.compile(r"^(?:education|summary|profile|references|hobbies|interests)\b", re.I),
        Section.OTHER,
    ),
)


@dataclass(frozen=True)
class Proposal:
    skill_id: int
    page: int
    start: int
    end: int
    quote: str
    section: str
    state: str
    ambiguous: bool


def build_matcher(dictionary_version):
    nlp = spacy.blank("en")
    matcher = PhraseMatcher(nlp.vocab, attr="LOWER")
    skill_by_key = {}
    for alias in SkillAlias.objects.filter(dictionary_version=dictionary_version):
        key = f"{alias.skill_id}:{alias.pk}"
        skill_by_key[nlp.vocab.strings.add(key)] = alias.skill_id
        matcher.add(key, [nlp.make_doc(alias.text)])
    return nlp, matcher, skill_by_key


def _clause_around(line, start, end):
    """The clause holding this match. Commas do not end one: "never used X, Y or Z" is one claim."""
    clause_start = 0
    clause_end = len(line)
    for boundary in _CLAUSE_BREAK.finditer(line):
        if boundary.end() <= start:
            clause_start = boundary.end()
        elif boundary.start() >= end:
            clause_end = boundary.start()
            break
    return line[clause_start:clause_end]


def _classify(line, start, end):
    """An instruction taints its whole line. Negation and aspiration cover their own clause."""
    if _NOTICE.search(line):
        return SpanState.NOTICE, False
    clause = _clause_around(line, start, end)
    if _NEGATED.search(clause) or _NO_SKILL_EXPERIENCE.search(clause):
        return SpanState.NEGATED, False
    if _ASPIRATIONAL.search(clause):
        return SpanState.ASPIRATIONAL, False
    return SpanState.PROVISIONAL, bool(_AMBIGUOUS.search(clause))


def _section_after(line, current):
    stripped = line.strip()
    if len(stripped) > 40:
        return current
    for pattern, section in _HEADINGS:
        if pattern.match(stripped):
            return section
    return current


def propose(visible_spans, nlp, matcher, skill_by_key):
    """Proposals from visible span records. Each range is a real range of the visible text."""
    proposals = []
    section = Section.OTHER
    for record in visible_spans:
        line = record["text"]
        next_section = _section_after(line, section)
        if next_section != section:
            section = next_section
        # Ordinary resumes put headings and evidence on the same line ("Skills: MQL").
        # A heading still sets provenance, but must not discard the text following it.
        doc = nlp.make_doc(line)
        spans = filter_spans([doc[s:e] for _m, s, e in matcher(doc)])
        keep = {(span.start, span.end) for span in spans}
        seen = set()
        for match_id, start, end in matcher(doc):
            if (start, end) not in keep:
                continue
            skill_id = skill_by_key[match_id]
            if (skill_id, start) in seen:
                continue
            seen.add((skill_id, start))
            span = doc[start:end]
            state, ambiguous = _classify(line, span.start_char, span.end_char)
            proposals.append(
                Proposal(
                    skill_id=skill_id,
                    page=record["page"],
                    start=record["start"] + span.start_char,
                    end=record["start"] + span.end_char,
                    quote=span.text,
                    section=section,
                    state=state,
                    ambiguous=ambiguous,
                )
            )
    return proposals


def extract_for_version(version, dictionary_version) -> int:
    """Store proposed spans for one scanned version. Quarantined and failed files yield nothing."""
    if version.visible_text_or_none() is None:
        return 0
    nlp, matcher, skill_by_key = build_matcher(dictionary_version)
    created = 0
    for proposal in propose(version.visible_spans, nlp, matcher, skill_by_key):
        _span, made = EvidenceSpan.objects.get_or_create(
            resume_version=version,
            skill_id=proposal.skill_id,
            start=proposal.start,
            end=proposal.end,
            defaults={
                "organisation_id": version.organisation_id,
                "profile_id": version.profile_id,
                "page": proposal.page,
                "quote": proposal.quote,
                "section": proposal.section,
                "state": proposal.state,
                "ambiguous": proposal.ambiguous,
            },
        )
        created += made
    return created

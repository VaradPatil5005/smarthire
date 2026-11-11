"""The controlled vocabulary: the 3DEXPERIENCE seed pack and versioned aliases."""

from django.db import transaction

from .models import DictionaryVersion, SkillAlias, SkillCategory, SkillNode

# (canonical name, category, parent, aliases). A parent is implied by its child, never the reverse.
SEED_PACK = [
    ("3DEXPERIENCE", SkillCategory.PLM, None, ["3DEXPERIENCE", "3DX", "3D Experience"]),
    ("ENOVIA", SkillCategory.PLM, "3DEXPERIENCE", ["ENOVIA"]),
    ("ENOVIA configuration", SkillCategory.PLM, "ENOVIA", ["ENOVIA configuration"]),
    ("CATIA V5/3DX", SkillCategory.PLM, "3DEXPERIENCE", ["CATIA", "CATIA V5", "CATIA V5/3DX"]),
    ("DELMIA", SkillCategory.PLM, "3DEXPERIENCE", ["DELMIA"]),
    ("SIMULIA", SkillCategory.PLM, "3DEXPERIENCE", ["SIMULIA"]),
    ("EKL", SkillCategory.PLM, "3DEXPERIENCE", ["EKL", "Enterprise Knowledge Language"]),
    ("MQL", SkillCategory.PLM, "3DEXPERIENCE", ["MQL", "Matrix Query Language"]),
    ("JPO", SkillCategory.PLM, "3DEXPERIENCE", ["JPO", "Java Program Object"]),
    ("CAA", SkillCategory.PLM, "3DEXPERIENCE", ["CAA", "CAA RADE"]),
    (
        "3DDashboard widgets",
        SkillCategory.PLM,
        "3DEXPERIENCE",
        ["3DDashboard widgets", "3DDashboard widget", "3DDashboard"],
    ),
    ("Data migration", SkillCategory.PRACTICE, None, ["data migration", "PLM migration"]),
    (
        "Migration validation",
        SkillCategory.PRACTICE,
        "Data migration",
        [
            "migration validation",
            "reconciled source and target records",
            "validated migrated data",
        ],
    ),
    ("Test automation", SkillCategory.PRACTICE, None, ["test automation", "automated testing"]),
    ("Python", SkillCategory.BACKEND, None, ["Python"]),
    ("Python automation", SkillCategory.BACKEND, "Python", ["Python automation"]),
    ("Django", SkillCategory.BACKEND, None, ["Django"]),
    (
        "Django REST Framework",
        SkillCategory.BACKEND,
        None,
        ["Django REST Framework", "DRF"],
    ),
    ("SAP", SkillCategory.DATA, None, ["SAP"]),
    ("PostgreSQL", SkillCategory.DATA, None, ["PostgreSQL", "Postgres"]),
    ("AWS", SkillCategory.CLOUD, None, ["AWS", "Amazon Web Services"]),
]


def latest_dictionary():
    return DictionaryVersion.objects.order_by("-number").first()


@transaction.atomic
def load_seed_pack() -> DictionaryVersion:
    """Load the seed pack once. Loading again changes nothing."""
    existing = latest_dictionary()
    if existing is not None:
        return existing
    version = DictionaryVersion.objects.create(number=1)
    nodes = {}
    for name, category, parent, _aliases in SEED_PACK:
        nodes[name] = SkillNode.objects.create(
            canonical_name=name, category=category, parent=nodes.get(parent)
        )
    for name, _category, _parent, aliases in SEED_PACK:
        for text in aliases:
            SkillAlias.objects.create(text=text, skill=nodes[name], dictionary_version=version)
    return version


@transaction.atomic
def add_alias(text, skill, approved_by) -> DictionaryVersion:
    """A change never touches a version a run may have pinned: it creates the next version."""
    current = latest_dictionary()
    next_version = DictionaryVersion.objects.create(number=current.number + 1)
    copies = [
        SkillAlias(
            text=alias.text,
            skill_id=alias.skill_id,
            dictionary_version=next_version,
            approved_by=alias.approved_by,
        )
        for alias in SkillAlias.objects.filter(dictionary_version=current)
    ]
    SkillAlias.objects.bulk_create(copies)
    SkillAlias.objects.create(
        text=text, skill=skill, dictionary_version=next_version, approved_by=approved_by
    )
    return next_version


def resolve_skill(text, dictionary_version=None):
    """Map a typed skill name to its node through the dictionary, ignoring case. None if unknown."""
    version = dictionary_version or latest_dictionary()
    alias = (
        SkillAlias.objects.filter(dictionary_version=version, text__iexact=text.strip())
        .select_related("skill")
        .first()
    )
    if alias:
        return alias.skill
    return SkillNode.objects.filter(canonical_name__iexact=text.strip()).first()

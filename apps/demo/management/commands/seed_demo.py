"""Load the synthetic demo: 2 organisations, 3 projects, 24 fictional profiles."""

import os
from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.ingestion.services import receive_upload, scan_stored_version
from apps.matching.models import EvidenceSpan, Outcome, SkillNode
from apps.matching.services import create_run, decide_span, record_skill_decision
from apps.matching.vocabulary import load_seed_pack
from apps.projects.models import Importance, Project
from apps.projects.services import add_skill, approve_rubric, next_version
from apps.talent.models import DataRequest, ResourceType, TalentProfile
from apps.talent.services import add_form_claim
from apps.tenancy.models import Membership, Organisation, Role

DEMO_PASSWORD_ENV = "DEMO_PASSWORD"  # noqa: S105  # nosec B105
DEFAULT_DEMO_PASSWORD = "demo-only-Plm-2026!"  # noqa: S105  # nosec B105
FIXTURE_DIR = Path(settings.BASE_DIR) / "fixtures" / "pdf"

PROJECTS = [
    (
        "3DEXPERIENCE migration, Pune (fictional)",
        [
            ("ENOVIA configuration", Importance.REQUIRED, 5),
            ("Migration validation", Importance.REQUIRED, 3),
            ("Python automation", Importance.PREFERRED, 2),
        ],
    ),
    (
        "3DEXPERIENCE test automation (fictional)",
        [
            ("Test automation", Importance.REQUIRED, 5),
            ("3DEXPERIENCE", Importance.REQUIRED, 3),
            ("Python", Importance.PREFERRED, 2),
        ],
    ),
    (
        "3DDashboard widget development (fictional)",
        [
            ("3DDashboard widgets", Importance.REQUIRED, 6),
            ("EKL", Importance.PREFERRED, 2),
            ("MQL", Importance.PREFERRED, 2),
        ],
    ),
]
BENCH = [
    ("Bench Consultant Aarav", "ENOVIA Architect", 20, 0, ["ENOVIA configuration", "MQL"]),
    ("Bench Consultant Bela", "CATIA Consultant", 80, 10, ["CATIA V5/3DX"]),
    ("Bench Consultant Chirag", "Test Lead", 50, 40, ["Test automation", "Python"]),
    ("Bench Consultant Divya", "Widget Developer", 0, 0, ["3DDashboard widgets", "EKL"]),
    ("Bench Consultant Esha", "Migration Lead", 60, 20, ["Data migration"]),
    ("Bench Consultant Farhan", "SIMULIA Analyst", 100, 60, ["SIMULIA"]),
    ("Bench Consultant Gauri", "DELMIA Consultant", 30, 5, ["DELMIA"]),
    ("Bench Consultant Harsh", "Solution Architect", 40, 15, ["3DEXPERIENCE", "JPO"]),
]
APPLICANTS = [
    ("Applicant Isha", "Graduate Engineer", 30, ["Python"]),
    ("Applicant Jay", "Graduate Engineer", 0, ["Django", "Python"]),
    ("Applicant Kiran", "PLM Developer", 60, ["MQL", "EKL"]),
    ("Applicant Lata", "QA Engineer", 45, ["Test automation"]),
    ("Applicant Manav", "CATIA Designer", 90, ["CATIA V5/3DX"]),
    ("Applicant Nisha", "ENOVIA Developer", None, ["ENOVIA"]),
    ("Applicant Om", "Data Engineer", 30, ["PostgreSQL", "SAP"]),
    ("Applicant Priya", "Widget Developer", 15, ["3DDashboard widgets"]),
    ("Applicant Rohan", "Cloud Engineer", 60, ["AWS"]),
    ("Applicant Sana", "Automation Engineer", 30, ["Python automation"]),
    ("Applicant Tara", "Graduate Engineer", 0, []),
]


class Command(BaseCommand):
    help = "Load the synthetic demo data. For local use only, and it refuses to run in production."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Run even if DEBUG is off.")

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError("seed_demo creates known logins. Refusing with DEBUG off.")
        if options["force"] and not os.environ.get(DEMO_PASSWORD_ENV):
            raise CommandError(f"--force needs {DEMO_PASSWORD_ENV} set, not the known password.")
        if Organisation.objects.filter(slug="weplm-demo").exists():
            self.stdout.write("Demo data already present; nothing changed.")
            return
        load_seed_pack()
        password = os.environ.get(DEMO_PASSWORD_ENV, DEFAULT_DEMO_PASSWORD)
        with transaction.atomic():
            summary = self._seed(password)
        self._scan_demo_resumes(summary)
        self.stdout.write(self.style.SUCCESS("Demo ready."))
        self.stdout.write(
            "Logins (all synthetic): recruiter, manager, admin, candidate_a, candidate_b, "
            "and other_recruiter in the second organisation."
        )

    def _user(self, username, password, organisation, role):
        user = get_user_model().objects.create_user(username=username, password=password)
        Membership.objects.create(user=user, organisation=organisation, role=role)
        return user

    def _seed(self, password):
        first = Organisation.objects.create(name="We.PLM demo (fictional)", slug="weplm-demo")
        second = Organisation.objects.create(name="Second client (fictional)", slug="second-demo")
        manager = self._user("manager", password, first, Role.DELIVERY_MANAGER)
        recruiter = self._user("recruiter", password, first, Role.RECRUITER)
        self._user("admin", password, first, Role.ADMIN)
        candidate_a = self._user("candidate_a", password, first, Role.CANDIDATE)
        candidate_b = self._user("candidate_b", password, first, Role.CANDIDATE)
        self._user("other_recruiter", password, second, Role.RECRUITER)

        start = date.today() + timedelta(days=30)
        for name, skills in PROJECTS:
            project = Project.objects.create(
                organisation=first, name=name, start_date=start, created_by=manager
            )
            rubric = next_version(project)
            for skill, importance, weight in skills:
                add_skill(rubric, skill, importance, weight)
            if name != PROJECTS[0][0]:
                approve_rubric(rubric, manager)

        profile_a = TalentProfile.objects.create(
            organisation=first,
            owner=candidate_a,
            display_name="Fictional Candidate A",
            title="ENOVIA Consultant",
            resource_type=ResourceType.EXTERNAL,
            notice_days=30,
        )
        add_form_claim(profile_a, "Migration validation")
        profile_b = TalentProfile.objects.create(
            organisation=first,
            owner=candidate_b,
            display_name="Fictional Candidate B",
            title="Senior PLM Consultant",
            resource_type=ResourceType.EXTERNAL,
            notice_days=30,
        )
        for name, title, allocation, days, claims in BENCH:
            profile = TalentProfile.objects.create(
                organisation=first,
                display_name=name,
                title=title,
                resource_type=ResourceType.INTERNAL,
                allocation_pct=allocation,
                available_from=date.today() + timedelta(days=days),
            )
            for claim in claims:
                add_form_claim(profile, claim)
        for name, title, notice, claims in APPLICANTS:
            profile = TalentProfile.objects.create(
                organisation=first,
                display_name=name,
                title=title,
                resource_type=ResourceType.EXTERNAL,
                notice_days=notice,
            )
            for claim in claims:
                add_form_claim(profile, claim)
        second_profile = TalentProfile.objects.create(
            organisation=second,
            display_name="Second Client Consultant",
            title="CATIA Consultant",
            resource_type=ResourceType.EXTERNAL,
        )
        add_form_claim(second_profile, "CATIA V5/3DX")
        TalentProfile.objects.create(
            organisation=second,
            display_name="Second Client Applicant",
            title="Graduate Engineer",
            resource_type=ResourceType.EXTERNAL,
        )
        banner = TalentProfile.objects.create(
            organisation=first,
            display_name="Honest Banner Candidate",
            title="PLM Consultant",
            resource_type=ResourceType.EXTERNAL,
            notice_days=30,
        )
        return {
            "organisation": first,
            "reviewer": recruiter,
            "profile_a": profile_a,
            "profile_b": profile_b,
            "banner": banner,
        }

    def _upload(self, summary, profile, fixture):
        data = (FIXTURE_DIR / f"{fixture}.pdf").read_bytes()
        uploaded = SimpleUploadedFile(f"{fixture}.pdf", data, content_type="application/pdf")
        version = receive_upload(uploaded, profile, summary["organisation"], summary["reviewer"])
        # Scan now, whatever the queue is doing, so evidence exists before it is reviewed below.
        # A later delivery of the queued job finds the version scanned and does nothing.
        scan_stored_version(version.pk)
        return version

    def _accept(self, summary, profile, skills):
        spans = EvidenceSpan.objects.filter(profile=profile, skill__canonical_name__in=skills)
        for span in spans:
            decide_span(
                span,
                Outcome.ACCEPT,
                "Passage reviewed against the project work described.",
                summary["reviewer"],
                summary["organisation"],
            )

    def _scan_demo_resumes(self, summary):
        """Scans run inline in dev settings, so the shortlist is ready as soon as this returns."""
        self._upload(summary, summary["profile_a"], "demo_candidate_a")
        self._upload(summary, summary["profile_b"], "demo_candidate_b")
        self._upload(summary, summary["banner"], "ben_01_white_on_dark_banner")
        self._accept(summary, summary["profile_a"], ["ENOVIA configuration"])
        self._accept(summary, summary["profile_b"], ["ENOVIA configuration", "Python automation"])
        self._seed_review_states(summary)

    def _seed_review_states(self, summary):
        """Give the shortlist a convincing example in every review group."""
        organisation = summary["organisation"]
        reviewer = summary["reviewer"]

        def named(name):
            return TalentProfile.objects.get(organisation=organisation, display_name=name)

        aarav = named("Bench Consultant Aarav")
        self._upload(summary, aarav, "demo_bench_aarav")
        self._accept(
            summary, aarav, ["ENOVIA configuration", "Migration validation", "Python automation"]
        )
        chirag = named("Bench Consultant Chirag")
        self._upload(summary, chirag, "demo_bench_chirag")
        self._accept(summary, chirag, ["Test automation", "3DEXPERIENCE", "Python"])
        divya = named("Bench Consultant Divya")
        self._upload(summary, divya, "demo_bench_divya")
        self._accept(summary, divya, ["3DDashboard widgets", "EKL"])
        # Left unreviewed on purpose, so the next action on the shortlist is visible.
        self._upload(summary, named("Bench Consultant Harsh"), "demo_bench_harsh")
        record_skill_decision(
            named("Applicant Manav"),
            SkillNode.objects.get(canonical_name="ENOVIA configuration"),
            Outcome.UNMET,
            "Confirmed with the candidate: no ENOVIA configuration work so far.",
            reviewer,
            organisation,
        )
        DataRequest.objects.create(
            organisation=organisation,
            profile=named("Applicant Rohan"),
            kind=DataRequest.Kind.CORRECTION,
        )
        for project in Project.objects.for_org(organisation):
            rubric = project.latest_rubric()
            if rubric.is_approved:
                create_run(project, f"seed-{project.pk}", {}, reviewer, organisation)

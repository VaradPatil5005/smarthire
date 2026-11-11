from django.core.management.base import BaseCommand

from apps.ingestion.services import sweep_stuck_versions


class Command(BaseCommand):
    help = "Move versions stuck in quarantine after a killed worker to FAILED."

    def handle(self, *args, **options):
        self.stdout.write(f"Moved {sweep_stuck_versions()} versions to FAILED.")

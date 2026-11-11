from django.db import migrations, models


def backfill(apps, schema_editor):
    """Existing results take the profile's values as the best record of what was run."""
    MatchResult = apps.get_model("matching", "MatchResult")
    for result in MatchResult.objects.select_related("profile").iterator():
        result.name_snapshot = result.profile.display_name
        result.resource_type_snapshot = result.profile.resource_type
        result.save(update_fields=["name_snapshot", "resource_type_snapshot"])


class Migration(migrations.Migration):
    dependencies = [("matching", "0002_initial")]

    operations = [
        migrations.AddField(
            model_name="matchresult",
            name="name_snapshot",
            field=models.CharField(default="", max_length=200),
        ),
        migrations.AddField(
            model_name="matchresult",
            name="resource_type_snapshot",
            field=models.CharField(
                choices=[("EXTERNAL", "External applicant"), ("INTERNAL", "Internal consultant")],
                default="",
                max_length=10,
            ),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]

"""Protect approved rubric skills against inserts and moves as well as edits."""

import importlib

from django.db import migrations

FORWARD = """
CREATE OR REPLACE FUNCTION refuse_approved_rubric_change() RETURNS trigger AS $$
DECLARE
    parent_status varchar;
BEGIN
    IF TG_TABLE_NAME = 'projects_rubricversion' THEN
        IF OLD.status = 'APPROVED' THEN
            RAISE EXCEPTION 'approved rubric version is immutable';
        END IF;
    ELSE
        IF TG_OP <> 'INSERT' THEN
            SELECT status INTO parent_status FROM projects_rubricversion
            WHERE id = OLD.rubric_id FOR UPDATE;
            IF parent_status = 'APPROVED' THEN
                RAISE EXCEPTION 'approved rubric version is immutable';
            END IF;
        END IF;
        IF TG_OP <> 'DELETE' THEN
            SELECT status INTO parent_status FROM projects_rubricversion
            WHERE id = NEW.rubric_id FOR UPDATE;
            IF parent_status = 'APPROVED' THEN
                RAISE EXCEPTION 'approved rubric version is immutable';
            END IF;
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER approved_rubric_skill_immutable ON projects_requirementskill;
CREATE TRIGGER approved_rubric_skill_immutable BEFORE INSERT OR UPDATE OR DELETE
ON projects_requirementskill FOR EACH ROW EXECUTE FUNCTION refuse_approved_rubric_change();
"""


def forward(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        previous = importlib.import_module(
            "apps.projects.migrations.0002_immutable_approved_rubrics"
        )
        schema_editor.execute(previous.REVERSE)
        schema_editor.execute(previous.FORWARD)


class Migration(migrations.Migration):
    dependencies = [("projects", "0002_immutable_approved_rubrics")]
    operations = [migrations.RunPython(forward, reverse)]

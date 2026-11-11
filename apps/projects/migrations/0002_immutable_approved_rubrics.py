"""PostgreSQL refuses changes to approved rubrics, even through raw SQL. Other engines rely on the ORM."""

from django.db import migrations

FORWARD = """
CREATE FUNCTION refuse_approved_rubric_change() RETURNS trigger AS $$
BEGIN
    IF TG_TABLE_NAME = 'projects_rubricversion' THEN
        IF OLD.status = 'APPROVED' THEN
            RAISE EXCEPTION 'approved rubric version is immutable';
        END IF;
    ELSE
        IF EXISTS (
            SELECT 1 FROM projects_rubricversion r
            WHERE r.id = COALESCE(OLD.rubric_id, NEW.rubric_id) AND r.status = 'APPROVED'
        ) THEN
            RAISE EXCEPTION 'approved rubric version is immutable';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER approved_rubric_immutable BEFORE UPDATE OR DELETE ON projects_rubricversion
    FOR EACH ROW EXECUTE FUNCTION refuse_approved_rubric_change();
CREATE TRIGGER approved_rubric_skill_immutable BEFORE UPDATE OR DELETE ON projects_requirementskill
    FOR EACH ROW EXECUTE FUNCTION refuse_approved_rubric_change();
"""
REVERSE = """
DROP TRIGGER approved_rubric_skill_immutable ON projects_requirementskill;
DROP TRIGGER approved_rubric_immutable ON projects_rubricversion;
DROP FUNCTION refuse_approved_rubric_change();
"""


def forward(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE)


class Migration(migrations.Migration):
    dependencies = [("projects", "0001_initial")]
    operations = [migrations.RunPython(forward, reverse)]

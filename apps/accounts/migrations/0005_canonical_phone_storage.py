"""Expand storage without changing authentication or rewriting any username.

This is an installed migration, not a test-owned shadow table. The PostgreSQL
transaction locks the user and deletion audit tables before a redacted preflight.
Never apply to a live database without the documented maintenance/backup approval.
"""
from django.core.validators import MaxLengthValidator
from django.db import migrations, models
from django.db.models.functions import Concat, Substr


def require_legacy_compatible_rows(apps, schema_editor):
    User = apps.get_model("accounts", "CustomUser")
    Deletion = apps.get_model("accounts", "AccountDeletionRequest")
    connection = schema_editor.connection
    alias = connection.alias
    if connection.vendor == "postgresql":
        # Names come from frozen model metadata, not input.
        tables = ", ".join(schema_editor.quote_name(model._meta.db_table)
                           for model in (User, Deletion))
        with connection.cursor() as cursor:
            cursor.execute(f"LOCK TABLE {tables} IN ACCESS EXCLUSIVE MODE")
    elif connection.vendor != "sqlite":
        raise RuntimeError("Canonical phone migration: unsupported database.")

    legacy = (
        models.Q(mobile_number__regex=r"^09[0-9]{9}$")
        & ~models.Q(mobile_number__regex=r"[^0-9]")
    )
    deletion_evidence = Deletion.objects.using(alias).filter(
        user_id=models.OuterRef("pk"),
        original_user_id=models.OuterRef("pk"),
        status__in=("anonymized", "completed"),
        anonymized_at__isnull=False,
    )
    tombstone = (
        models.Q(mobile_number__regex=r"^9[4-8][0-9]{9}$",
                 is_active=False, password__startswith="!")
        & ~models.Q(mobile_number__regex=r"[^0-9]")
        & models.Q(models.Exists(deletion_evidence))
    )
    # Distinct exact ASCII legacy usernames map injectively to E.164.
    # All aliases, ambiguous rows, unknown placeholders and foreign values
    # are refused before DDL. The existing unique username and exclusive lock
    # make a collision among the accepted legacy rows impossible.
    unresolved = User.objects.using(alias).exclude(legacy | tombstone).count()
    if unresolved:
        raise RuntimeError(
            "Canonical phone migration blocked: unresolved account rows="
            + str(unresolved)
        )


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("accounts", "0004_userworkspacepreference")]
    operations = [
        migrations.RunPython(require_legacy_compatible_rows, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="customuser", name="mobile_number",
            field=models.CharField(
                max_length=16, unique=True, validators=[MaxLengthValidator(11)],
                verbose_name="شماره موبایل",
            ),
        ),
        migrations.AddField(
            model_name="customuser", name="canonical_mobile_number",
            field=models.GeneratedField(
                expression=models.Case(
                    models.When(
                        models.Q(mobile_number__regex=r"^09[0-9]{9}$")
                        & ~models.Q(mobile_number__regex=r"[^0-9]"),
                        then=Concat(models.Value("+98"), Substr("mobile_number", 2)),
                    ),
                    models.When(
                        models.Q(mobile_number__regex=r"^\+989[0-9]{9}$")
                        & ~models.Q(mobile_number__regex=r"[^+0-9]"),
                        then=models.F("mobile_number"),
                    ),
                    models.When(
                        models.Q(mobile_number__regex=r"^\+[1-9][0-9]{7,14}$")
                        & ~models.Q(mobile_number__regex=r"[^+0-9]")
                        & ~models.Q(mobile_number__startswith="+98"),
                        then=models.F("mobile_number"),
                    ),
                    default=models.Value(None),
                    output_field=models.CharField(max_length=16),
                ),
                output_field=models.CharField(max_length=16),
                db_persist=True,
                null=True,
                unique=True,
            ),
        ),
        # On reverse, the preflight runs BEFORE removing the generated field
        # or shrinking the username; never truncate a foreign identifier.
        migrations.RunPython(migrations.RunPython.noop, require_legacy_compatible_rows),
    ]

from django.db import migrations, models

import loomera.globalization.calendar_time


class Migration(migrations.Migration):
    dependencies = [
        ("salons", "0005_salon_city_zone_label"),
    ]

    # Additive only: no RunPython, RunSQL, or appointment/date/time rewrites.
    # Blank is an explicit legacy sentinel and does NOT use deployment defaults.
    operations = [
        migrations.AddField(
            model_name="salon",
            name="timezone_name",
            field=models.CharField(
                max_length=64,
                blank=True,
                default="",
                validators=[loomera.globalization.calendar_time.validate_iana_timezone_name],
                verbose_name="منطقه زمانی مجموعه (IANA)",
                help_text=(
                    "خالی یعنی رفتار زمانی قدیمی تهران؛ مقدار صریح مانند Europe/Berlin "
                    "فعلاً فقط به عنوان داده ثبت می‌شود و زمان نوبت‌های قبلی را تغییر نمی‌دهد."
                ),
            ),
        ),
    ]

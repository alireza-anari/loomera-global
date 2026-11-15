from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

from apps.main.cache_preflight import (
    assess_cache_configuration,
    assess_redis_url,
    probe_cache_backend,
)


class Command(BaseCommand):
    help = "Run a lightweight Loomera readiness check before beta/staging releases."

    def _ok(self, message):
        self.stdout.write(self.style.SUCCESS(f"✓ {message}"))

    def _warn(self, message):
        self.stdout.write(self.style.WARNING(f"⚠ {message}"))

    def _fail(self, message):
        self.stdout.write(self.style.ERROR(f"✗ {message}"))
        self.failures += 1

    def _environment(self) -> str:
        return str(getattr(settings, "LOOMERA_ENVIRONMENT", "local") or "local").lower()

    def _is_deployed_environment(self) -> bool:
        return self._environment() in {"staging", "production"}

    def _check_core_security(self):
        if getattr(settings, "DEBUG", False):
            if self._is_deployed_environment():
                self._fail("DEBUG در staging/production باید False باشد.")
            else:
                self._warn("DEBUG فعال است؛ فقط برای local قابل قبول است.")
        else:
            self._ok("DEBUG غیرفعال است.")

        if not getattr(settings, "ALLOWED_HOSTS", []):
            self._warn("ALLOWED_HOSTS خالی است؛ فقط برای local قابل قبول است.")
        elif "*" in getattr(settings, "ALLOWED_HOSTS", []):
            self._fail("ALLOWED_HOSTS در staging/production نباید wildcard باشد.")
        else:
            self._ok("ALLOWED_HOSTS تنظیم شده است.")

        if self._is_deployed_environment() and not getattr(
            settings, "CSRF_TRUSTED_ORIGINS", []
        ):
            self._fail("CSRF_TRUSTED_ORIGINS برای staging/production باید تنظیم شود.")
        else:
            self._ok("CSRF_TRUSTED_ORIGINS بررسی شد.")

        if not getattr(settings, "DEBUG", False):
            installed_apps = set(getattr(settings, "INSTALLED_APPS", []))
            middleware = set(getattr(settings, "MIDDLEWARE", []))
            if "debug_toolbar" in installed_apps:
                self._fail(
                    "debug_toolbar نباید در محیط غیر DEBUG داخل INSTALLED_APPS باشد."
                )
            else:
                self._ok("debug_toolbar در INSTALLED_APPS production لود نشده است.")

            if "debug_toolbar.middleware.DebugToolbarMiddleware" in middleware:
                self._fail("DebugToolbarMiddleware نباید در محیط غیر DEBUG لود شود.")
            else:
                self._ok("DebugToolbarMiddleware در production لود نشده است.")

        if getattr(settings, "SERVE_MEDIA_INSECURELY", False) and not getattr(
            settings, "DEBUG", False
        ):
            self._fail("SERVE_MEDIA_INSECURELY در محیط غیر DEBUG نباید فعال باشد.")
        else:
            self._ok("تنظیم سرو media ناامن نیست.")

    def _check_feature_flags(self):
        flags = [
            "BETA_MODE",
            "COMMISSION_ENABLED",
            "ONLINE_PAYMENT_ENABLED",
            "DEPOSIT_ENABLED",
            "BNPL_ENABLED",
            "DEBT_ENFORCEMENT_ENABLED",
            "SALON_VERIFICATION_ENFORCED",
            "SALON_WITHDRAWAL_ENABLED",
            "AUTOMATIC_REFUND_ENABLED",
            "MESSAGING_ENABLED",
            "MESSAGING_OUTBOUND_ENABLED",
            "MESSAGING_ACTIONS_ENABLED",
            "USE_S3_MEDIA",
            "LOOMERA_REQUIRE_OBJECT_STORAGE",
        ]
        for flag in flags:
            self._ok(f"{flag} = {getattr(settings, flag, None)}")

        if getattr(settings, "ONLINE_PAYMENT_ENABLED", False):
            self._fail("برای لانچ بتا ONLINE_PAYMENT_ENABLED باید False باشد.")
        else:
            self._ok("پرداخت آنلاین برای بتا خاموش است.")

        if getattr(settings, "MESSAGING_ACTIONS_ENABLED", False):
            self._ok("اکشن‌های ربات بله فعال هستند.")
        else:
            self._ok("اکشن‌های ربات بله خاموش هستند.")

        if getattr(settings, "AUTOMATIC_REFUND_ENABLED", False):
            self._fail("برای شروع بتا بازگشت وجه خودکار نباید فعال باشد.")
        else:
            self._ok("بازگشت وجه خودکار خاموش است.")

    def _check_email_sms_map_bale(self):
        email_backend = getattr(settings, "EMAIL_BACKEND", "")
        if getattr(settings, "BETA_MODE", True) and "dummy" not in email_backend:
            self._fail(
                "در بتا EMAIL_BACKEND باید dummy باشد تا ایمیل واقعی ارسال نشود."
            )
        else:
            self._ok(f"EMAIL_BACKEND = {email_backend}")

        if getattr(settings, "SMS_OTP_ENABLED", False):
            if not getattr(settings, "SMSIR_API_KEY", "") and not getattr(
                settings, "SMSIR_SANDBOX_API_KEY", ""
            ):
                self._fail("SMS_OTP_ENABLED=True اما SMS.ir API key تنظیم نشده است.")
            else:
                self._ok("SMS.ir API key برای OTP تنظیم شده است.")

            if not getattr(settings, "SMSIR_SIGNUP_TEMPLATE_ID", ""):
                self._fail("SMSIR_SIGNUP_TEMPLATE_ID برای OTP ثبت‌نام لازم است.")
            else:
                self._ok("SMSIR_SIGNUP_TEMPLATE_ID تنظیم شده است.")

            if not getattr(settings, "SMSIR_RESET_TEMPLATE_ID", ""):
                self._fail("SMSIR_RESET_TEMPLATE_ID برای فراموشی رمز لازم است.")
            else:
                self._ok("SMSIR_RESET_TEMPLATE_ID تنظیم شده است.")
        else:
            self._warn("SMS_OTP_ENABLED خاموش است؛ قبل از staging عمومی باید روشن شود.")

        if not getattr(settings, "MAPIR_API_KEY", ""):
            self._warn("MAPIR_API_KEY تنظیم نشده است.")
        else:
            self._ok("MAPIR_API_KEY تنظیم شده است.")

        if getattr(settings, "BALE_BOT_ENABLED", False):
            if not getattr(settings, "BALE_BOT_TOKEN", ""):
                self._fail("BALE_BOT_ENABLED=True اما BALE_BOT_TOKEN تنظیم نشده است.")
            else:
                self._ok("BALE_BOT_TOKEN تنظیم شده است.")

            if not getattr(settings, "BALE_WEBHOOK_SECRET", ""):
                self._fail("BALE_WEBHOOK_SECRET برای webhook لازم است.")
            else:
                self._ok("BALE_WEBHOOK_SECRET تنظیم شده است.")

            if not getattr(settings, "BALE_WEBHOOK_REQUIRE_SECRET", True):
                self._fail(
                    "BALE_WEBHOOK_REQUIRE_SECRET باید در staging/production روشن باشد."
                )
            else:
                self._ok("BALE_WEBHOOK_REQUIRE_SECRET روشن است.")

            if getattr(
                settings,
                "BALE_WEBHOOK_ALLOW_QUERY_SECRET",
                False,
            ):
                environment = self._environment()

                if environment == "production":
                    self._fail(
                        "BALE_WEBHOOK_ALLOW_QUERY_SECRET "
                        "در production نباید روشن باشد."
                    )
                elif environment == "staging":
                    self._warn(
                        "BALE_WEBHOOK_ALLOW_QUERY_SECRET در staging "
                        "به‌عنوان fallback موقت بله فعال است."
                    )
                else:
                    self._warn(
                        "BALE_WEBHOOK_ALLOW_QUERY_SECRET " "در محیط local فعال است."
                    )
            else:
                self._ok("BALE_WEBHOOK_ALLOW_QUERY_SECRET خاموش است.")

            if not getattr(settings, "MESSAGING_PUBLIC_BASE_URL", ""):
                self._fail("MESSAGING_PUBLIC_BASE_URL برای لینک‌های ربات لازم است.")
            else:
                self._ok("MESSAGING_PUBLIC_BASE_URL تنظیم شده است.")
        else:
            self._warn(
                "BALE_BOT_ENABLED خاموش است؛ برای تست ربات در staging باید روشن شود."
            )

    def _check_database_and_cache(self):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            self._ok("اتصال دیتابیس سالم است.")
        except Exception as exc:
            self._fail(f"اتصال دیتابیس خطا دارد: {exc.__class__.__name__}")

        engine = settings.DATABASES.get("default", {}).get("ENGINE", "")
        if self._is_deployed_environment() and "postgis" not in engine:
            self._fail("در staging/production باید از PostGIS engine استفاده شود.")
        else:
            self._ok(f"Database engine: {engine}")

        cache_config = settings.CACHES.get("default", {})
        assessment = assess_cache_configuration(
            cache_config,
            deployed=self._is_deployed_environment(),
            debug=bool(getattr(settings, "DEBUG", False)),
        )
        for error in assessment.errors:
            self._fail(f"Cache configuration: {error}")
        for warning in assessment.warnings:
            self._warn(f"Cache configuration: {warning}")

        if assessment.ok:
            try:
                probe_cache_backend(scope="pre_beta")
                self._ok("Cache add/read probe succeeded.")
            except Exception as exc:
                self._fail(f"Cache probe failed: {exc.__class__.__name__}")

        cache_backend = str(cache_config.get("BACKEND", "") or "")
        if cache_backend:
            self._ok(f"Cache backend: {cache_backend}")

    def _check_media_storage(self):
        use_s3_media = bool(getattr(settings, "USE_S3_MEDIA", False))
        require_object_storage = bool(
            getattr(settings, "LOOMERA_REQUIRE_OBJECT_STORAGE", False)
        )
        default_backend = settings.STORAGES.get("default", {}).get("BACKEND", "")

        if use_s3_media:
            self._ok(f"Media storage: {default_backend}")
            for setting_name in [
                "AWS_ACCESS_KEY_ID",
                "AWS_SECRET_ACCESS_KEY",
                "AWS_STORAGE_BUCKET_NAME",
                "AWS_S3_ENDPOINT_URL",
            ]:
                if not getattr(settings, setting_name, ""):
                    self._fail(f"{setting_name} برای Object Storage لازم است.")
                else:
                    self._ok(f"{setting_name} تنظیم شده است.")
        elif self._is_deployed_environment() or require_object_storage:
            self._fail("برای staging/production باید USE_S3_MEDIA=True باشد.")
        else:
            self._warn("Media روی فایل‌سیستم local است؛ فقط برای local قابل قبول است.")

    def _check_celery_policy(self):
        if getattr(settings, "LOOMERA_ENABLE_CELERY", False):
            broker = str(getattr(settings, "CELERY_BROKER_URL", "") or "")
            if not broker:
                self._fail("Celery فعال است اما CELERY_BROKER_URL تنظیم نشده.")
            elif self._is_deployed_environment():
                assessment = assess_redis_url(broker)
                for error in assessment.errors:
                    self._fail(f"Celery broker configuration: {error}")
                for warning in assessment.warnings:
                    self._warn(f"Celery broker configuration: {warning}")
                if not assessment.errors:
                    self._ok("Celery broker تنظیم شده است.")
            else:
                self._ok("Celery broker تنظیم شده است.")
        else:
            self._warn(
                "Celery غیرفعال است؛ برای beta با cron + management command قابل قبول است."
            )

    def handle(self, *args, **options):
        self.failures = 0

        self._check_core_security()
        self._check_feature_flags()
        self._check_email_sms_map_bale()
        self._check_database_and_cache()
        self._check_media_storage()
        self._check_celery_policy()

        if not getattr(settings, "SENTRY_DSN", ""):
            self._warn(
                "SENTRY_DSN تنظیم نشده؛ برای beta بهتر است error monitoring فعال شود."
            )
        else:
            self._ok("Sentry تنظیم شده است.")

        if self.failures:
            raise SystemExit(1)

        self.stdout.write(self.style.SUCCESS("Loomera pre-beta check completed."))

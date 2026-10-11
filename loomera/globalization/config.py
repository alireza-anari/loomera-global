from __future__ import annotations

from dataclasses import dataclass as _dataclass

from django.conf import settings as _settings

__all__ = (
    "DeploymentGlobalizationConfig",
    "get_deployment_globalization_config",
)


@_dataclass(frozen=True, slots=True)
class DeploymentGlobalizationConfig:
    default_language: str
    enabled_languages: tuple[str, ...]
    default_country: str
    default_currency: str
    default_timezone: str
    default_calendar: str


def get_deployment_globalization_config() -> DeploymentGlobalizationConfig:
    return DeploymentGlobalizationConfig(
        default_language=_settings.LOOMERA_DEFAULT_LANGUAGE,
        enabled_languages=tuple(_settings.LOOMERA_ENABLED_LANGUAGES),
        default_country=_settings.LOOMERA_DEFAULT_COUNTRY,
        default_currency=_settings.LOOMERA_DEFAULT_CURRENCY,
        default_timezone=_settings.LOOMERA_DEFAULT_TIMEZONE,
        default_calendar=_settings.LOOMERA_DEFAULT_CALENDAR,
    )

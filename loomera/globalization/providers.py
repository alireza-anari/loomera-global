from __future__ import annotations

from dataclasses import dataclass as _dataclass

from django.conf import settings as _settings

__all__ = (
    "DeploymentProviderConfig",
    "get_deployment_provider_config",
)


@_dataclass(frozen=True, slots=True)
class DeploymentProviderConfig:
    map_provider: str
    sms_provider: str
    payment_provider: str
    messaging_allowed_providers: tuple[str, ...]


def get_deployment_provider_config() -> DeploymentProviderConfig:
    return DeploymentProviderConfig(
        map_provider=(getattr(_settings, "MAP_PROVIDER", "mapir") or "mapir").strip().lower(),
        sms_provider=_settings.SMS_PROVIDER,
        payment_provider=_settings.PAYMENT_PROVIDER,
        messaging_allowed_providers=tuple(_settings.MESSAGING_ALLOWED_PROVIDERS),
    )

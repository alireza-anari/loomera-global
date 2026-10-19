"""Immutable deployment-level brand configuration."""

from __future__ import annotations

from dataclasses import dataclass as _dataclass

from django.conf import settings as _settings

__all__ = (
    "DeploymentBrandConfig",
    "get_deployment_brand_config",
)


@_dataclass(frozen=True, slots=True)
class DeploymentBrandConfig:
    name: str
    display_name: str
    domain: str
    public_base_url: str
    site_url: str
    email_sender_name: str
    default_from_email: str
    support_email: str
    partner_email: str
    marketing_email: str
    calendar_prodid: str
    calendar_name: str
    display_name_fa: str


def get_deployment_brand_config() -> DeploymentBrandConfig:
    return DeploymentBrandConfig(
        name=_settings.BRAND_NAME,
        display_name=_settings.BRAND_DISPLAY_NAME,
        domain=_settings.BRAND_DOMAIN,
        public_base_url=_settings.PUBLIC_BASE_URL,
        site_url=_settings.SITE_URL,
        email_sender_name=_settings.LOOMERA_EMAIL_SENDER_NAME,
        default_from_email=_settings.DEFAULT_FROM_EMAIL,
        support_email=_settings.LOOMERA_SUPPORT_EMAIL,
        partner_email=_settings.LOOMERA_PARTNER_EMAIL,
        marketing_email=_settings.LOOMERA_MARKETING_EMAIL,
        calendar_prodid=_settings.LOOMERA_CALENDAR_PRODID,
        calendar_name=_settings.LOOMERA_CALENDAR_NAME,
        display_name_fa=_settings.BRAND_DISPLAY_NAME_FA,
    )

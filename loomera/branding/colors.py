"""Deployment-level brand color configuration snapshots."""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings as _settings

__all__ = (
    "DeploymentBrandColorConfig",
    "get_deployment_brand_color_config",
)


def _hex_to_rgb_triplet(value: str) -> str:
    return " ".join(str(int(value[index : index + 2], 16)) for index in (1, 3, 5))


@dataclass(frozen=True, slots=True)
class DeploymentBrandColorConfig:
    primary_color: str
    primary_hover_color: str
    primary_active_color: str
    primary_soft_color: str
    secondary_color: str
    accent_color: str
    background_color: str
    surface_color: str
    text_primary_color: str
    text_on_primary_color: str
    browser_theme_dark_color: str

    @property
    def primary_rgb(self) -> str:
        return _hex_to_rgb_triplet(self.primary_color)

    @property
    def primary_hover_rgb(self) -> str:
        return _hex_to_rgb_triplet(self.primary_hover_color)

    @property
    def primary_active_rgb(self) -> str:
        return _hex_to_rgb_triplet(self.primary_active_color)

    @property
    def primary_soft_rgb(self) -> str:
        return _hex_to_rgb_triplet(self.primary_soft_color)

    @property
    def secondary_rgb(self) -> str:
        return _hex_to_rgb_triplet(self.secondary_color)

    @property
    def accent_rgb(self) -> str:
        return _hex_to_rgb_triplet(self.accent_color)

    @property
    def background_rgb(self) -> str:
        return _hex_to_rgb_triplet(self.background_color)

    @property
    def surface_rgb(self) -> str:
        return _hex_to_rgb_triplet(self.surface_color)

    @property
    def text_primary_rgb(self) -> str:
        return _hex_to_rgb_triplet(self.text_primary_color)

    @property
    def text_on_primary_rgb(self) -> str:
        return _hex_to_rgb_triplet(self.text_on_primary_color)


def get_deployment_brand_color_config() -> DeploymentBrandColorConfig:
    return DeploymentBrandColorConfig(
        primary_color=_settings.BRAND_PRIMARY_COLOR,
        primary_hover_color=_settings.BRAND_PRIMARY_HOVER_COLOR,
        primary_active_color=_settings.BRAND_PRIMARY_ACTIVE_COLOR,
        primary_soft_color=_settings.BRAND_PRIMARY_SOFT_COLOR,
        secondary_color=_settings.BRAND_SECONDARY_COLOR,
        accent_color=_settings.BRAND_ACCENT_COLOR,
        background_color=_settings.BRAND_BACKGROUND_COLOR,
        surface_color=_settings.BRAND_SURFACE_COLOR,
        text_primary_color=_settings.BRAND_TEXT_PRIMARY_COLOR,
        text_on_primary_color=_settings.BRAND_TEXT_ON_PRIMARY_COLOR,
        browser_theme_dark_color=_settings.BRAND_BROWSER_THEME_DARK_COLOR,
    )

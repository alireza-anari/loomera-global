"""Immutable deployment-level brand asset configuration."""

from __future__ import annotations

from dataclasses import dataclass as _dataclass

from django.conf import settings as _settings

__all__ = (
    "DeploymentBrandAssetConfig",
    "get_deployment_brand_asset_config",
)


@_dataclass(frozen=True, slots=True)
class DeploymentBrandAssetConfig:
    logo_glyph_path: str
    app_icon_path: str
    logo_header_path: str
    logo_primary_path: str

    favicon_svg_path: str
    favicon_ico_path: str
    favicon_16_path: str
    favicon_32_path: str
    favicon_48_path: str
    apple_touch_icon_path: str
    mask_icon_path: str
    webmanifest_path: str

    social_image_path: str
    quick_link_mirror_label_art_path: str
    quick_link_business_card_front_art_path: str
    quick_link_business_card_back_art_path: str
    quick_link_table_stand_art_path: str
    quick_link_qr_glyph_path: str
    login_hero_path: str
    customer_signup_hero_path: str
    stylist_signup_hero_path: str
    manager_signup_hero_path: str
    social_image_width: int
    social_image_height: int


def get_deployment_brand_asset_config() -> DeploymentBrandAssetConfig:
    return DeploymentBrandAssetConfig(
        logo_glyph_path=_settings.BRAND_LOGO_GLYPH_STATIC_PATH,
        app_icon_path=_settings.BRAND_APP_ICON_STATIC_PATH,
        logo_header_path=_settings.BRAND_LOGO_HEADER_STATIC_PATH,
        logo_primary_path=_settings.BRAND_LOGO_PRIMARY_STATIC_PATH,
        favicon_svg_path=_settings.BRAND_FAVICON_SVG_STATIC_PATH,
        favicon_ico_path=_settings.BRAND_FAVICON_ICO_STATIC_PATH,
        favicon_16_path=_settings.BRAND_FAVICON_16_STATIC_PATH,
        favicon_32_path=_settings.BRAND_FAVICON_32_STATIC_PATH,
        favicon_48_path=_settings.BRAND_FAVICON_48_STATIC_PATH,
        apple_touch_icon_path=_settings.BRAND_APPLE_TOUCH_ICON_STATIC_PATH,
        mask_icon_path=_settings.BRAND_MASK_ICON_STATIC_PATH,
        webmanifest_path=_settings.BRAND_WEBMANIFEST_STATIC_PATH,
        social_image_path=_settings.BRAND_SOCIAL_IMAGE_STATIC_PATH,
        quick_link_mirror_label_art_path=_settings.BRAND_QUICK_LINK_MIRROR_LABEL_ART_STATIC_PATH,
        quick_link_business_card_front_art_path=_settings.BRAND_QUICK_LINK_BUSINESS_CARD_FRONT_ART_STATIC_PATH,
        quick_link_business_card_back_art_path=_settings.BRAND_QUICK_LINK_BUSINESS_CARD_BACK_ART_STATIC_PATH,
        quick_link_table_stand_art_path=_settings.BRAND_QUICK_LINK_TABLE_STAND_ART_STATIC_PATH,
        quick_link_qr_glyph_path=_settings.BRAND_QUICK_LINK_QR_GLYPH_STATIC_PATH,
        login_hero_path=_settings.BRAND_LOGIN_HERO_STATIC_PATH,
        customer_signup_hero_path=_settings.BRAND_CUSTOMER_SIGNUP_HERO_STATIC_PATH,
        stylist_signup_hero_path=_settings.BRAND_STYLIST_SIGNUP_HERO_STATIC_PATH,
        manager_signup_hero_path=_settings.BRAND_MANAGER_SIGNUP_HERO_STATIC_PATH,
        social_image_width=_settings.BRAND_SOCIAL_IMAGE_WIDTH,
        social_image_height=_settings.BRAND_SOCIAL_IMAGE_HEIGHT,
    )

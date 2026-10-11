"""Template context for deployment-level brand configuration."""

from __future__ import annotations

from loomera.branding.assets import get_deployment_brand_asset_config
from loomera.branding.colors import get_deployment_brand_color_config
from loomera.branding.config import get_deployment_brand_config

__all__ = ("deployment_brand",)


def deployment_brand(request):
    return {
        "deployment_brand": get_deployment_brand_config(),
        "deployment_brand_assets": get_deployment_brand_asset_config(),
        "deployment_brand_colors": get_deployment_brand_color_config(),
    }

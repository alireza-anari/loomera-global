"""Template context for deployment-level brand identity."""

from __future__ import annotations

from loomera.branding.config import get_deployment_brand_config

__all__ = ("deployment_brand",)


def deployment_brand(request):
    return {"deployment_brand": get_deployment_brand_config()}

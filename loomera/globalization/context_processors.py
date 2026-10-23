"""Request-local presentation language/direction for templates."""
from __future__ import annotations

from loomera.globalization.locale import get_deployment_locale_context


def deployment_locale(request):
    return {"deployment_locale": get_deployment_locale_context(request)}

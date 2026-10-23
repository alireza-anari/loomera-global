"""LocaleMiddleware-compatible deployment language selection.

URL prefix negotiation is intentionally deferred to the SEO URL policy.
"""
from __future__ import annotations

from django.middleware.locale import LocaleMiddleware
from django.utils import translation

from loomera.globalization.locale import resolve_request_locale


class DeploymentLocaleMiddleware(LocaleMiddleware):
    def process_request(self, request):
        language = resolve_request_locale(request)
        translation.activate(language)
        request.LANGUAGE_CODE = language

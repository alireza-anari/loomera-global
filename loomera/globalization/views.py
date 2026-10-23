"""CSRF-protected, presentation-only language selection endpoint."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpResponseBadRequest, HttpResponseRedirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from loomera.globalization.locale import LANGUAGE_SESSION_KEY


def _safe_local_return_path(request) -> str:
    """Only relative URLs rooted on this site; never redirect to another host."""
    path = str(request.POST.get("next", "") or "").strip()
    if not path.startswith("/") or path.startswith("//"):
        return "/"
    if not url_has_allowed_host_and_scheme(
        path, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return "/"
    return path


@require_POST
def set_deployment_language(request):
    raw_language = request.POST.get("language", "")
    if not isinstance(raw_language, str):
        return HttpResponseBadRequest("Unsupported language")
    language = raw_language.strip().lower()
    if (
        not language
        or len(language) > 16
        or language not in settings.LOOMERA_ENABLED_LANGUAGES
    ):
        # Invalid or disabled values must not touch session/cookie state.
        return HttpResponseBadRequest("Unsupported language")

    return_path = _safe_local_return_path(request)
    request.session[LANGUAGE_SESSION_KEY] = language
    response = HttpResponseRedirect(return_path)
    response.set_cookie(
        settings.LANGUAGE_COOKIE_NAME,
        language,
        max_age=settings.LANGUAGE_COOKIE_AGE,
        path=settings.LANGUAGE_COOKIE_PATH,
        domain=settings.LANGUAGE_COOKIE_DOMAIN,
        secure=settings.LANGUAGE_COOKIE_SECURE,
        httponly=True,
        samesite=settings.LANGUAGE_COOKIE_SAMESITE,
    )
    response["Cache-Control"] = "no-store"
    return response

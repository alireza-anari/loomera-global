"""Deployment-enabled request locale and bidirectional presentation contract.

This layer only controls language selection and shell direction. It does not
change the compatibility Django LANGUAGE_CODE, calendar, timezone or money.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from django.conf import settings

__all__ = (
    "DeploymentLocaleContext",
    "get_deployment_locale_context",
    "resolve_request_locale",
    "LANGUAGE_SESSION_KEY",
)

# A future authenticated-user preference can be added ahead of this priority.
LANGUAGE_SESSION_KEY = "loomera_language"
_LANGUAGE_NAME = {"en": "English", "ar": "العربية", "fa": "فارسی"}
_RTL_LANGUAGES = frozenset(("ar", "fa"))
_LOCALE_RE = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$")
_Q_RE = re.compile(r"^(?:0(?:\.[0-9]{0,3})?|1(?:\.0{0,3})?)$")


@dataclass(frozen=True, slots=True)
class DeploymentLocaleContext:
    language_code: str
    direction: str
    enabled_languages: tuple[str, ...]

    @property
    def is_rtl(self) -> bool:
        return self.direction == "rtl"


def _match_enabled(raw: object, enabled: tuple[str, ...]) -> str | None:
    if not isinstance(raw, str):
        return None
    candidate = raw.strip().lower().replace("_", "-")
    if not _LOCALE_RE.fullmatch(candidate):
        return None
    if candidate in enabled:
        return candidate
    base = candidate.split("-", 1)[0]
    return base if base in enabled else None


def _from_accept_language(header: object, enabled: tuple[str, ...]) -> str | None:
    if not isinstance(header, str):
        return None
    choices: list[tuple[float, int, str]] = []
    # Only a bounded number of header items may influence the result.
    for index, item in enumerate(header[:512].split(",")[:20]):
        components = item.strip().split(";")
        if len(components) > 2:
            continue
        language = _match_enabled(components[0], enabled)
        if language is None:
            continue
        quality = 1.0
        if len(components) == 2:
            weight = components[1].strip().lower()
            if not weight.startswith("q=") or not _Q_RE.fullmatch(weight[2:]):
                continue
            quality = float(weight[2:])
        if quality > 0:
            choices.append((-quality, index, language))
    if not choices:
        return None
    choices.sort()
    return choices[0][2]


def resolve_request_locale(request) -> str:
    """Session -> Django language cookie -> Accept-Language -> configured default.

    Only explicitly enabled languages may win. Unsupported, malformed or
    q=0 choices do not override the deployment default.
    """
    enabled = tuple(settings.LOOMERA_ENABLED_LANGUAGES)
    fallback = settings.LOOMERA_DEFAULT_LANGUAGE
    if not enabled or fallback not in enabled:
        # Settings import rejects these; fail closed under invalid runtime overrides.
        raise ValueError("Deployment default locale must be enabled")

    session = getattr(request, "session", None)
    if session is not None:
        chosen = _match_enabled(session.get(LANGUAGE_SESSION_KEY), enabled)
        if chosen is not None:
            return chosen

    cookies = getattr(request, "COOKIES", {})
    chosen = _match_enabled(cookies.get(settings.LANGUAGE_COOKIE_NAME), enabled)
    if chosen is not None:
        return chosen

    headers = getattr(request, "headers", {})
    chosen = _from_accept_language(headers.get("Accept-Language", ""), enabled)
    return chosen or fallback


def get_deployment_locale_context(request) -> DeploymentLocaleContext:
    enabled = tuple(settings.LOOMERA_ENABLED_LANGUAGES)
    language = _match_enabled(
        getattr(request, "LANGUAGE_CODE", None), enabled
    )
    if language is None:
        language = resolve_request_locale(request)
    return DeploymentLocaleContext(
        language_code=language,
        direction="rtl" if language.split("-", 1)[0] in _RTL_LANGUAGES else "ltr",
        enabled_languages=enabled,
    )

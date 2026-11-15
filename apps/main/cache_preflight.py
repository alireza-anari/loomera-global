"""Shared, non-destructive cache and Redis deployment preflight helpers.

These checks validate configured connection shape without exposing credentials.
The runtime probe uses a random add-only key with a short TTL; it never
overwrites or deletes a fixed application key.
"""
from __future__ import annotations

from dataclasses import dataclass
import secrets
from urllib.parse import parse_qs, urlsplit

from django.core.cache import caches


@dataclass(frozen=True, slots=True)
class RedisURLAssessment:
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CacheConfigurationAssessment:
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


class CacheProbeError(RuntimeError):
    """A cache probe failed without exposing its key or value."""


def assess_redis_url(value: str) -> RedisURLAssessment:
    """Validate a deployed Redis URL without returning or logging credentials."""
    errors: list[str] = []
    warnings: list[str] = []
    raw = str(value or "").strip()
    if not raw:
        return RedisURLAssessment(("redis_url_required",))

    try:
        parsed = urlsplit(raw)
        port = parsed.port
        query = parse_qs(parsed.query)
    except ValueError:
        return RedisURLAssessment(("redis_url_invalid",))

    if parsed.scheme not in {"redis", "rediss"}:
        errors.append("redis_url_scheme_must_be_redis_or_rediss")
    if not parsed.hostname:
        errors.append("redis_url_host_required")
    elif parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}:
        errors.append("deployed_redis_url_must_not_use_localhost")
    if port is not None and not 1 <= port <= 65535:
        errors.append("redis_url_port_invalid")

    database = parsed.path.lstrip("/")
    if database and not database.isdigit():
        errors.append("redis_url_database_invalid")

    if not parsed.password:
        errors.append("deployed_redis_password_required")

    if parsed.scheme == "redis":
        warnings.append("redis_transport_tls_not_enabled")
    if not parsed.username:
        warnings.append("redis_named_acl_username_not_configured")
    elif parsed.username.lower() == "default":
        warnings.append("redis_default_acl_username_in_use")

    cert_requirements = {
        item.strip().lower() for item in query.get("ssl_cert_reqs", [])
    }
    if cert_requirements.intersection({"none", "optional"}):
        errors.append("redis_tls_certificate_verification_not_required")

    return RedisURLAssessment(tuple(errors), tuple(warnings))


def assess_cache_configuration(
    cache_config: dict,
    *,
    deployed: bool,
    debug: bool,
) -> CacheConfigurationAssessment:
    """Validate Django's default cache backend for local or deployed runtime."""
    config = cache_config if isinstance(cache_config, dict) else {}
    backend = str(config.get("BACKEND", "") or "")
    location = str(config.get("LOCATION", "") or "")
    errors: list[str] = []
    warnings: list[str] = []

    if not backend:
        errors.append("cache_backend_required")
    if "LocMemCache" in backend and not debug:
        errors.append("non_debug_cache_must_not_use_locmem")

    if deployed:
        if "django_redis.cache.RedisCache" not in backend:
            errors.append("deployed_cache_backend_must_be_django_redis")
        assessment = assess_redis_url(location)
        errors.extend(assessment.errors)
        warnings.extend(assessment.warnings)

    return CacheConfigurationAssessment(
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def probe_cache_backend(*, scope: str) -> None:
    """Prove add/read on a unique expiring key without clobbering shared state.

    The key and marker are random per invocation. No delete is attempted: the
    30-second TTL bounds residue even if the write acknowledgement is ambiguous.
    """
    if scope not in {"infrastructure", "pre_beta"}:
        raise ValueError("unsupported_cache_probe_scope")

    backend = caches["default"]
    key = f"loomera:preflight:{scope}:{secrets.token_hex(16)}"
    marker = secrets.token_hex(32)

    try:
        added = backend.add(key, marker, timeout=30)
    except Exception as exc:
        raise CacheProbeError("cache_probe_add_failed") from exc
    if added is not True:
        raise CacheProbeError("cache_probe_add_not_confirmed")

    try:
        observed = backend.get(key)
    except Exception as exc:
        raise CacheProbeError("cache_probe_read_failed") from exc
    if observed != marker:
        raise CacheProbeError("cache_probe_mismatch")

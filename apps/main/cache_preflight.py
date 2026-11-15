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
    elif parsed.hostname.lower() in {"localhost", "127.0.0.1", "0.0.0.0", "::1", "::"}:
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
        if backend != "django_redis.cache.RedisCache":
            errors.append("deployed_cache_backend_must_be_django_redis")
        assessment = assess_redis_url(location)
        errors.extend(assessment.errors)
        warnings.extend(assessment.warnings)

    return CacheConfigurationAssessment(
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def probe_cache_backend(*, scope: str, alias: str = "default") -> None:
    """Prove add/read on a unique expiring key without clobbering shared state.

    The key and marker are random per invocation. No delete is attempted: the
    30-second TTL bounds residue even if the write acknowledgement is ambiguous.
    """
    if scope not in {"infrastructure", "pre_beta", "otp", "pre_beta_otp"}:
        raise ValueError("unsupported_cache_probe_scope")
    if alias not in {"default", "otp"}:
        raise ValueError("unsupported_cache_alias")

    backend = caches[alias]
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



def build_redis_role_inventory(settings_obj=None) -> dict:
    """Return a redacted settings-only Redis role map; never opens connections."""
    if settings_obj is None:
        from django.conf import settings as settings_obj

    caches_config = getattr(settings_obj, "CACHES", {}) or {}
    default_config = caches_config.get("default", {}) or {}
    otp_alias = str(
        getattr(settings_obj, "LOOMERA_API_AUTH_OTP_CACHE_ALIAS", "default")
        or "default"
    ).strip().lower()
    otp_config = (
        caches_config.get("otp", {}) if otp_alias == "otp" else default_config
    ) or {}

    celery_enabled = bool(getattr(settings_obj, "LOOMERA_ENABLE_CELERY", False))
    role_sources = (
        ("general_cache", default_config.get("LOCATION", ""), "configured"),
        ("api_otp", otp_config.get("LOCATION", ""), "configured"),
        ("infrastructure_preflight", default_config.get("LOCATION", ""), "configured"),
        (
            "celery_broker",
            getattr(settings_obj, "CELERY_BROKER_URL", "") if celery_enabled else "",
            "configured" if celery_enabled else "disabled",
        ),
        (
            "celery_result",
            getattr(settings_obj, "CELERY_RESULT_BACKEND", "") if celery_enabled else "",
            "configured" if celery_enabled else "disabled",
        ),
    )

    endpoint_groups: dict[tuple, str] = {}
    principal_groups: dict[tuple, str] = {}
    roles: dict[str, dict] = {}

    for role, raw_location, default_status in role_sources:
        location = str(raw_location or "").strip()
        if not location:
            roles[role] = {"status": default_status if default_status != "configured" else "unconfigured"}
            continue
        try:
            parsed = urlsplit(location)
            parsed_port = parsed.port
            port = parsed_port if parsed_port is not None else 6379
            database_text = parsed.path.lstrip("/")
            if database_text and ("/" in database_text or not database_text.isdigit()):
                roles[role] = {"status": "invalid"}
                continue
            database = int(database_text) if database_text else 0
            if not 1 <= port <= 65535:
                roles[role] = {"status": "invalid"}
                continue
        except ValueError:
            roles[role] = {"status": "invalid"}
            continue
        if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
            roles[role] = {"status": "non_redis_or_invalid"}
            continue

        endpoint = (parsed.hostname.lower(), port)
        principal = (
            parsed.hostname.lower(),
            port,
            parsed.username or "default",
        )
        if endpoint not in endpoint_groups:
            endpoint_groups[endpoint] = f"endpoint_{len(endpoint_groups) + 1}"
        if principal not in principal_groups:
            principal_groups[principal] = f"principal_{len(principal_groups) + 1}"
        roles[role] = {
            "status": "configured",
            "scheme": parsed.scheme,
            "database_index": database,
            "endpoint_group": endpoint_groups[endpoint],
            "principal_group": principal_groups[principal],
            "named_acl_user": bool(
                parsed.username and parsed.username.lower() != "default"
            ),
            "tls_requested": parsed.scheme == "rediss",
        }

    warnings: list[str] = []
    general_principal = roles.get("general_cache", {}).get("principal_group")
    otp_principal = roles.get("api_otp", {}).get("principal_group")
    broker_principal = roles.get("celery_broker", {}).get("principal_group")
    result_principal = roles.get("celery_result", {}).get("principal_group")

    if otp_alias == "default":
        warnings.append("api_otp_shares_general_cache_alias")
        if getattr(settings_obj, "LOOMERA_API_AUTH_OTP_CACHE_LOCATION", ""):
            warnings.append("api_otp_dedicated_location_configured_but_alias_default")
    elif otp_principal and otp_principal == general_principal:
        warnings.append("api_otp_shares_general_cache_principal")

    if celery_enabled and broker_principal:
        if broker_principal == general_principal:
            warnings.append("celery_broker_shares_general_cache_principal")
        if broker_principal == otp_principal:
            warnings.append("celery_broker_shares_api_otp_principal")
    if celery_enabled and result_principal:
        if result_principal == broker_principal:
            warnings.append("celery_result_shares_celery_broker_principal")
        if result_principal == general_principal:
            warnings.append("celery_result_shares_general_cache_principal")
        if result_principal == otp_principal:
            warnings.append("celery_result_shares_api_otp_principal")
    if any(
        role.get("status") == "configured" and not role.get("tls_requested")
        for role in roles.values()
    ):
        warnings.append("one_or_more_redis_roles_do_not_request_tls")
    if any(
        role.get("status") == "configured" and not role.get("named_acl_user")
        for role in roles.values()
    ):
        warnings.append("one_or_more_redis_roles_use_default_or_missing_acl_user")

    return {
        "environment": str(getattr(settings_obj, "LOOMERA_ENVIRONMENT", "unknown")),
        "api_otp_cache_alias": otp_alias,
        "roles": roles,
        "warnings": list(dict.fromkeys(warnings)),
        "redis_connections_opened": False,
        "database_connections_opened": False,
        "secrets_emitted": False,
        "logical_database_isolation_is_security_boundary": False,
        "server_side_acl_verified": False,
        "global_ingress_fenced": False,
        "production_release_authorized": False,
    }

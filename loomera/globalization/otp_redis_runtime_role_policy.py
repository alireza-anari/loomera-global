"""Phase 7.31 read-only inventory of runtime Redis role separation.

This module parses configuration only. It never opens a Redis/PostgreSQL
connection, reads secrets into its output, changes settings, or grants release
approval. Logical Redis DB numbers are deliberately excluded from principal
identity because SELECT DB is not an ACL/security boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class _Target:
    status: str
    scheme: str | None = None
    host: str | None = field(default=None, repr=False)
    port: int | None = None
    database: int | None = None
    username: str | None = field(default=None, repr=False)
    password_present: bool = False

    @property
    def endpoint_key(self):
        if not self.host or self.port is None:
            return None
        return self.host.lower(), self.port

    @property
    def principal_key(self):
        endpoint = self.endpoint_key
        if endpoint is None:
            return None
        # Redis logical DBs are not an isolation boundary.
        return endpoint + (self.username or "default",)

    @property
    def local(self) -> bool:
        return (self.host or "").lower() in {
            "localhost", "127.0.0.1", "::1",
        }


@dataclass(frozen=True, slots=True)
class _Role:
    name: str
    source: str
    alias: str | None
    active: bool
    target: _Target


def _parse_target(value: Any) -> _Target:
    if not isinstance(value, str) or not value.strip():
        return _Target(status="missing")
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"redis", "rediss"}:
            return _Target(
                status="non_redis", scheme=parsed.scheme or None,
            )
        host = parsed.hostname
        port = parsed.port or 6379
        path = parsed.path.lstrip("/")
        if not host or (path and ("/" in path or not path.isdigit())):
            return _Target(status="invalid", scheme=parsed.scheme)
        database = int(path) if path else 0
        if database < 0:
            return _Target(status="invalid", scheme=parsed.scheme)
        return _Target(
            status="configured",
            scheme=parsed.scheme,
            host=host,
            port=port,
            database=database,
            username=parsed.username,
            password_present=parsed.password is not None and bool(parsed.password),
        )
    except (TypeError, ValueError):
        return _Target(status="invalid")


def _role(
    name: str, source: str, alias: str | None, active: bool, value: Any,
) -> _Role:
    return _Role(
        name=name, source=source, alias=alias, active=active,
        target=_parse_target(value),
    )


def audit_runtime_redis_roles(settings_obj: Any) -> dict[str, Any]:
    """Return a redacted, configuration-only role inventory and release gate."""
    environment = str(
        getattr(settings_obj, "LOOMERA_ENVIRONMENT", "local") or "local"
    ).strip().lower()
    deployed = environment in {"staging", "production"}
    caches = getattr(settings_obj, "CACHES", {})
    if not isinstance(caches, dict):
        caches = {}
    default_config = caches.get("default", {})
    if not isinstance(default_config, dict):
        default_config = {}
    otp_alias = str(
        getattr(settings_obj, "LOOMERA_API_AUTH_OTP_CACHE_ALIAS", "default")
        or "default"
    ).strip()
    otp_config = caches.get(otp_alias, {})
    if not isinstance(otp_config, dict):
        otp_config = {}

    celery_enabled = bool(getattr(settings_obj, "LOOMERA_ENABLE_CELERY", False))
    roles = [
        _role(
            "django_cache_default", "CACHES.default.LOCATION", "default", True,
            default_config.get("LOCATION"),
        ),
        _role(
            "api_otp", "LOOMERA_API_AUTH_OTP_CACHE_ALIAS", otp_alias, True,
            otp_config.get("LOCATION"),
        ),
        _role(
            "infrastructure_preflight", "django.core.cache.cache", "default",
            deployed, default_config.get("LOCATION"),
        ),
        _role(
            "celery_broker", "CELERY_BROKER_URL", None, celery_enabled,
            getattr(settings_obj, "CELERY_BROKER_URL", ""),
        ),
        _role(
            "celery_result", "CELERY_RESULT_BACKEND", None, celery_enabled,
            getattr(settings_obj, "CELERY_RESULT_BACKEND", ""),
        ),
    ]

    endpoint_groups: dict[tuple, str] = {}
    principal_groups: dict[tuple, str] = {}
    for role in roles:
        target = role.target
        if target.endpoint_key is not None:
            endpoint_groups.setdefault(
                target.endpoint_key, f"endpoint-{len(endpoint_groups) + 1}",
            )
        if target.principal_key is not None:
            principal_groups.setdefault(
                target.principal_key, f"principal-{len(principal_groups) + 1}",
            )

    principal_members: dict[tuple, list[str]] = {}
    for role in roles:
        if role.target.principal_key is not None:
            principal_members.setdefault(role.target.principal_key, []).append(
                role.name
            )

    role_output = []
    for role in roles:
        target = role.target
        shared = (
            principal_members.get(target.principal_key, [])
            if target.principal_key is not None else []
        )
        role_output.append({
            "name": role.name,
            "source": role.source,
            "cache_alias": role.alias,
            "active": role.active,
            "status": target.status,
            "scheme": target.scheme,
            "tls_enabled": target.scheme == "rediss",
            "named_acl_user_present": bool(
                target.username and target.username != "default"
            ),
            "password_present": target.password_present,
            "logical_database": target.database,
            "local_endpoint": target.local,
            "endpoint_group": endpoint_groups.get(target.endpoint_key),
            "principal_group": principal_groups.get(target.principal_key),
            "shares_principal_with": [
                name for name in shared if name != role.name
            ],
        })

    findings: list[str] = []
    assurance_gaps = [
        "REDIS_SERVER_ACL_RULES_NOT_READ_OR_VERIFIED",
        "ALL_REDIS_NODES_AND_NETWORK_INGRESS_NOT_INVENTORIED",
        "PRIVILEGED_ADMIN_CREDENTIALS_AND_REVOCATION_NOT_VERIFIED",
        "EXISTING_AUTHENTICATED_SOCKET_REVOCATION_NOT_VERIFIED",
        "LIVE_OTP_CONSUME_IS_NOT_PROVEN_ATOMIC",
        "SYNTHETIC_OUTBOX_IS_NOT_CONNECTED_TO_LIVE_OTP",
        "CROSS_STORE_ATOMIC_DELIVERY_AND_EXTERNAL_SMS_RECEIPT_NOT_PROVEN",
    ]

    if otp_alias == "default":
        findings.append("OTP_SHARES_DEFAULT_DJANGO_CACHE_ALIAS")
    elif otp_alias not in caches:
        findings.append("OTP_CACHE_ALIAS_IS_NOT_CONFIGURED")
    if otp_alias == "default":
        findings.append("OTP_HAS_NO_DEDICATED_REDIS_PRINCIPAL_BOUNDARY")

    if deployed:
        for role in roles:
            if not role.active:
                continue
            target = role.target
            if role.name in {"django_cache_default", "api_otp"} and (
                "redis" not in str(
                    (caches.get(role.alias or "", {}) or {}).get("BACKEND", "")
                ).lower()
            ):
                findings.append(role.name.upper() + "_DEPLOYED_BACKEND_NOT_REDIS")
            if target.status == "missing":
                findings.append(role.name.upper() + "_REDIS_ENDPOINT_MISSING")
            elif target.status == "invalid":
                findings.append(role.name.upper() + "_REDIS_ENDPOINT_INVALID")
            elif target.status == "configured":
                if not target.scheme == "rediss":
                    findings.append(role.name.upper() + "_REDIS_TLS_REQUIRED")
                if not target.username or target.username == "default":
                    findings.append(role.name.upper() + "_NAMED_REDIS_ACL_USER_REQUIRED")
                if not target.password_present:
                    findings.append(role.name.upper() + "_REDIS_PASSWORD_REQUIRED")
                if target.local:
                    findings.append(role.name.upper() + "_LOCAL_REDIS_ENDPOINT_FORBIDDEN")

    by_name = {role.name: role for role in roles}
    cache_target = by_name["django_cache_default"].target
    otp_target = by_name["api_otp"].target
    broker_target = by_name["celery_broker"].target
    result_target = by_name["celery_result"].target

    if otp_alias != "default" and (
        otp_target.principal_key is not None
        and otp_target.principal_key == cache_target.principal_key
    ):
        findings.append("OTP_AND_GENERAL_CACHE_REUSE_REDIS_PRINCIPAL")
    if celery_enabled and (
        broker_target.principal_key is not None
        and broker_target.principal_key == cache_target.principal_key
    ):
        findings.append("CELERY_BROKER_REUSES_GENERAL_CACHE_REDIS_PRINCIPAL")
    if celery_enabled and (
        result_target.principal_key is not None
        and result_target.principal_key == broker_target.principal_key
    ):
        findings.append("CELERY_RESULT_REUSES_BROKER_REDIS_PRINCIPAL")

    findings.extend(assurance_gaps)
    return {
        "schema_version": 1,
        "phase": "7.31",
        "environment": environment,
        "deployed_environment": deployed,
        "roles": role_output,
        "findings": findings,
        "assurance_gaps": assurance_gaps,
        "configuration_only": True,
        "redis_connections_opened": False,
        "database_connections_opened": False,
        "secrets_emitted": False,
        "server_side_acl_verified": False,
        "global_redis_ingress_fenced": False,
        "live_otp_atomic_consume_proven": False,
        "outbox_connected_to_live_otp": False,
        "production_release_authorized": False,
        "release_gate": "BLOCKED",
    }

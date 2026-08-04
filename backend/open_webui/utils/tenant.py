"""Multi-tenancy: tenant context, IAM broker client, and WorkOS verification.

This is the schat (data-plane) consumer of the in-house IAM control-plane
service described in ``IAM_INTEGRATION_GUIDE.md``. It owns:

* the request-scoped ``TenantContext`` (a ``ContextVar``) that the DB engine
  registry, Qdrant client, and storage provider read to stay tenant-scoped;
* the Pydantic mirror of the IAM ``/resolve`` contract (the integration
  boundary — treat these shapes as fixed);
* ``IAMClient`` — the s2s HTTP client for ``/resolve``, ``/me/tenants`` and
  ``/tenants/{slug}/connection``;
* ``WorkOSVerifier`` — local RS256/JWKS verification of the WorkOS session
  token (so entitlement is a cache-miss hop, not a per-request one);
* ``TenantResolver`` — ties verify + entitle + broker together, with a
  per-tenant bundle cache.

Everything here is inert unless ``ENABLE_MULTI_TENANCY`` is true.

Fail-closed is the top safety property: any missing/invalid token, missing
tenant, absent membership, or IAM error must surface as an error — never a
fall-back to a default/shared store. Connection secrets (DB password, Qdrant
api_key, storage keys) are Confidential (ISMS A.5.12) and must never be logged.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict

from open_webui.env import (
    IAM_BASE_URL,
    IAM_CLIENT_ID,
    IAM_CLIENT_SECRET,
    IAM_HTTP_TIMEOUT,
    IAM_VERIFY_SSL,
    TENANT_BUNDLE_CACHE_TTL,
    WORKOS_AUDIENCE,
    WORKOS_CLAIM_EMAIL,
    WORKOS_CLAIM_NAME,
    WORKOS_CLAIM_ORG_ID,
    WORKOS_CLAIM_USER_ID,
    WORKOS_ISSUER,
    WORKOS_JWKS_URL,
)

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# IAM /resolve contract mirror  (see IAM_INTEGRATION_GUIDE.md §5.1)
#
# `extra='ignore'` so additive changes on the IAM side don't break schat.
# ─────────────────────────────────────────────────────────────────────


class Identity(BaseModel):
    # Per IAM_INTEGRATION_GUIDE.md §4.1, entitlement is keyed on **email** and
    # the /resolve identity block no longer carries a WorkOS user id. email is
    # therefore required (a resolve without one is unusable → fail closed at the
    # parse boundary). `workos_user_id` is retired from the contract but kept as
    # an optional field for tolerance if any caller still sends it.
    model_config = ConfigDict(extra='ignore')
    email: str
    name: Optional[str] = None
    workos_user_id: Optional[str] = None


class TenantInfo(BaseModel):
    model_config = ConfigDict(extra='ignore')
    id: str
    slug: str
    status: str


class DatabaseConnection(BaseModel):
    model_config = ConfigDict(extra='ignore')
    host: str
    port: int = 5432
    db_name: str
    username: str
    password: str


class QdrantConnection(BaseModel):
    model_config = ConfigDict(extra='ignore')
    url: str
    collection_prefix: str
    api_key: Optional[str] = None


class StorageConnection(BaseModel):
    # Every field is nullable on the IAM side — schat must validate and fail
    # closed (a None bucket/provider is an error, not a default).
    model_config = ConfigDict(extra='ignore')
    provider: Optional[str] = None
    endpoint: Optional[str] = None
    access_key: Optional[str] = None
    secret_key: Optional[str] = None
    bucket: Optional[str] = None
    prefix: Optional[str] = None


class ConnectionBundle(BaseModel):
    model_config = ConfigDict(extra='ignore')
    database: DatabaseConnection
    qdrant: QdrantConnection
    storage: StorageConnection


class ResolveResponse(BaseModel):
    # §5.1 — WorkOS-token all-in-one (retained as a fallback; the primary path is
    # the IAM-JWT flow: POST /token → POST /connection).
    model_config = ConfigDict(extra='ignore')
    identity: Identity
    tenant: TenantInfo
    role: str
    connection: ConnectionBundle


class TenantSummary(BaseModel):
    # A BU as it appears in an IAM JWT / introspection. Keyed on slug + role;
    # `name` and `id` are optional (the /token and /token/verify shapes omit id).
    model_config = ConfigDict(extra='ignore')
    slug: str
    role: str
    name: Optional[str] = None
    id: Optional[str] = None


class ConnectionResponse(BaseModel):
    """§5.0c — ``POST /connection`` response (the primary cred-fetch, keyed on
    the IAM JWT). There is **no** identity block here — identity comes from the
    IAM JWT. ``tenant_id`` echoes the BU **slug**, not a UUID."""

    model_config = ConfigDict(extra='ignore')
    tenant_id: str
    role: str
    connection: ConnectionBundle


class TokenExchangeResponse(BaseModel):
    """§5.0 — ``POST /token`` / ``/token/refresh`` response. WorkOS token
    exchanged for an IAM JWT that carries identity + the user's BUs. An
    authenticated user with no memberships still gets a token with empty
    ``tenants`` (the frontend treats that as 'no access').

    ``refresh_token`` is the revocable half of the session: IAM stores its digest
    in ``user_sessions``, so revoking that row ends the session within one access
    TTL. IAM sets no cookies — schat converts this into the httpOnly
    ``iam_refresh`` cookie and never lets it reach a browser-readable response.

    It is ``None`` **only** on the reuse-grace path of ``/token/refresh``, where a
    racing tab has already rotated and the browser's cookie holds the live
    successor. There, callers MUST leave the existing cookie alone — overwriting it
    with a spent token would break the session at the next refresh."""

    model_config = ConfigDict(extra='ignore')
    token: str
    token_type: str = 'bearer'
    expires_in: Optional[int] = None
    refresh_token: Optional[str] = None
    refresh_expires_in: Optional[int] = None
    identity: Identity
    tenants: list[TenantSummary] = []


class TokenVerifyResponse(BaseModel):
    """§5.0b — ``POST /token/verify`` introspection. ``active`` is false for an
    invalid/expired token (still HTTP 200)."""

    model_config = ConfigDict(extra='ignore')
    active: bool
    identity: Optional[Identity] = None
    tenants: list[TenantSummary] = []


class MemberRead(BaseModel):
    # IAM identifies members by email (the entitlement key); the member API no
    # longer returns a WorkOS user id. See IAM_INTEGRATION_GUIDE.md §4.1.
    model_config = ConfigDict(extra='ignore')
    id: str
    email: str
    role: str
    status: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────
# Request-scoped tenant context
# ─────────────────────────────────────────────────────────────────────


@dataclass
class TenantContext:
    """The resolved tenant for the current request/task."""

    tenant_id: str  # engine-registry key; the BU slug under the IAM-JWT flow
    slug: str  # business-unit slug == X-Tenant-Id
    role: str  # 'admin' | 'user' (from IAM membership)
    status: str
    identity: Identity
    connection: ConnectionBundle

    @classmethod
    def from_resolve(cls, r: ResolveResponse) -> 'TenantContext':
        return cls(
            tenant_id=r.tenant.id,
            slug=r.tenant.slug,
            role=r.role,
            status=r.tenant.status,
            identity=r.identity,
            connection=r.connection,
        )

    @classmethod
    def from_connection(cls, c: 'ConnectionResponse', identity: Identity) -> 'TenantContext':
        """Build from a ``POST /connection`` response (primary path). ``tenant_id``
        is the slug IAM echoes back; identity is sourced from the IAM JWT. A 200
        from /connection implies an active BU (suspended ⇒ 409), so status='active'."""
        return cls(
            tenant_id=c.tenant_id,
            slug=c.tenant_id,
            role=c.role,
            status='active',
            identity=identity,
            connection=c.connection,
        )


_current_tenant: ContextVar[Optional[TenantContext]] = ContextVar('current_tenant', default=None)

# Escape hatch: mark a code path as intentionally operating on the system /
# default engine (startup config load, Alembic, background maintenance) even
# when multi-tenancy is on and no request tenant is set.
_system_context: ContextVar[bool] = ContextVar('system_context', default=False)


class TenantContextError(RuntimeError):
    """Raised when a tenant-scoped resource is used with no resolved tenant."""


def get_tenant_context() -> Optional[TenantContext]:
    return _current_tenant.get()


def set_tenant_context(ctx: TenantContext) -> Token:
    return _current_tenant.set(ctx)


def reset_tenant_context(token: Token) -> None:
    _current_tenant.reset(token)


def require_tenant_context() -> TenantContext:
    """Return the current tenant or fail closed."""
    ctx = _current_tenant.get()
    if ctx is None:
        raise TenantContextError('No tenant context resolved for this request (fail-closed).')
    return ctx


def is_system_context() -> bool:
    return _system_context.get()


@contextmanager
def system_context():
    """Run enclosed code against the system/default engine (startup, migrations,
    background jobs) when multi-tenancy is enabled."""
    token = _system_context.set(True)
    try:
        yield
    finally:
        _system_context.reset(token)


def enter_system_context() -> Token:
    """Manual counterpart to ``system_context`` for spans that straddle a
    ``yield`` (e.g. an app lifespan). Pair with ``exit_system_context``."""
    return _system_context.set(True)


def exit_system_context(token: Token) -> None:
    _system_context.reset(token)


# ─────────────────────────────────────────────────────────────────────
# Errors + secret-safe logging
# ─────────────────────────────────────────────────────────────────────


class TenantResolutionError(Exception):
    """A failure to resolve/entitle/broker a tenant. ``status_code`` mirrors the
    IAM error contract so the middleware can return it verbatim (fail closed)."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f'{status_code}: {detail}')


def safe_bundle_summary(bundle: ConnectionBundle) -> dict:
    """A log-safe view of a connection bundle — NEVER includes secrets."""
    return {
        'database': {
            'host': bundle.database.host,
            'port': bundle.database.port,
            'db_name': bundle.database.db_name,
            'username': bundle.database.username,
        },
        'qdrant': {
            'url': bundle.qdrant.url,
            'collection_prefix': bundle.qdrant.collection_prefix,
            'api_key': '***' if bundle.qdrant.api_key else None,
        },
        'storage': {
            'provider': bundle.storage.provider,
            'endpoint': bundle.storage.endpoint,
            'bucket': bundle.storage.bucket,
            'prefix': bundle.storage.prefix,
        },
    }


def _safe_detail(resp: httpx.Response) -> str:
    """Extract the IAM error ``{"detail": ...}`` message defensively.

    IAM error bodies carry no secrets, but bound and sanitize anyway."""
    try:
        body = resp.json()
        detail = body.get('detail') if isinstance(body, dict) else None
        if isinstance(detail, str):
            return detail[:200]
    except Exception:
        pass
    return f'IAM returned status {resp.status_code}'


def _token_fingerprint(token: str) -> str:
    """A short, non-reversible key derived from the token for cache keying only.
    Never logged, never stored beyond the in-memory cache."""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────
# WorkOS token verification (local RS256 / JWKS)
# ─────────────────────────────────────────────────────────────────────


@dataclass
class VerifiedClaims:
    user_id: str
    org_id: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None


class WorkOSVerifier:
    """Verifies a WorkOS session JWT locally against the WorkOS JWKS.

    Claim names are read from env (``WORKOS_CLAIM_*``) and MUST match the IAM
    service's config. If ``WORKOS_JWKS_URL`` is unset, verification is disabled
    and the resolver relies on IAM ``/resolve`` (authoritative) instead."""

    def __init__(self, *, jwks_url=None, issuer=None, audience=None):
        self.jwks_url = jwks_url if jwks_url is not None else WORKOS_JWKS_URL
        self.issuer = issuer if issuer is not None else WORKOS_ISSUER
        self.audience = audience if audience is not None else WORKOS_AUDIENCE
        self._jwk_client = None

    @property
    def enabled(self) -> bool:
        return bool(self.jwks_url)

    def _client(self):
        if self._jwk_client is None:
            import jwt

            self._jwk_client = jwt.PyJWKClient(self.jwks_url)
        return self._jwk_client

    def verify(self, token: str) -> VerifiedClaims:
        import jwt

        try:
            signing_key = self._client().get_signing_key_from_jwt(token)
            options = {
                'require': ['exp'],
                'verify_aud': bool(self.audience),
                'verify_iss': bool(self.issuer),
            }
            kwargs = {}
            if self.audience:
                kwargs['audience'] = self.audience
            if self.issuer:
                kwargs['issuer'] = self.issuer
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=['RS256'],
                options=options,
                leeway=30,
                **kwargs,
            )
        except Exception as e:
            # Never log the token or the underlying claim values.
            log.warning('WorkOS token verification failed: %s', type(e).__name__)
            raise TenantResolutionError(401, 'invalid token') from e

        user_id = claims.get(WORKOS_CLAIM_USER_ID)
        if not user_id:
            raise TenantResolutionError(401, 'token missing subject claim')
        return VerifiedClaims(
            user_id=user_id,
            org_id=claims.get(WORKOS_CLAIM_ORG_ID),
            email=claims.get(WORKOS_CLAIM_EMAIL),
            name=claims.get(WORKOS_CLAIM_NAME),
        )


# ─────────────────────────────────────────────────────────────────────
# IAM broker client
# ─────────────────────────────────────────────────────────────────────


class IAMClient:
    """s2s client for the IAM control-plane. All connection secrets returned by
    IAM stay in memory and are never logged."""

    def __init__(
        self,
        *,
        base_url=None,
        client_id=None,
        client_secret=None,
        timeout=None,
        verify=None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.base_url = base_url if base_url is not None else IAM_BASE_URL
        self.client_id = client_id if client_id is not None else IAM_CLIENT_ID
        self.client_secret = client_secret if client_secret is not None else IAM_CLIENT_SECRET
        self.timeout = timeout if timeout is not None else IAM_HTTP_TIMEOUT
        self.verify = verify if verify is not None else IAM_VERIFY_SSL
        self._injected = http_client  # tests pass an httpx.AsyncClient(MockTransport)
        self._client: Optional[httpx.AsyncClient] = None

    def _s2s_headers(self) -> dict:
        if not self.client_id or not self.client_secret:
            raise TenantResolutionError(500, 'IAM service credentials are not configured')
        return {'X-Client-Id': self.client_id, 'X-Client-Secret': self.client_secret}

    def _get_client(self) -> httpx.AsyncClient:
        if self._injected is not None:
            return self._injected
        if self._client is None:
            if not self.base_url:
                raise TenantResolutionError(500, 'IAM_BASE_URL is not configured')
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout, verify=self.verify)
        return self._client

    async def resolve(self, workos_token: str, tenant_slug: str) -> ResolveResponse:
        """POST /resolve — verify + entitle + broker. The one call per tenant."""
        client = self._get_client()
        try:
            resp = await client.post(
                '/resolve',
                headers=self._s2s_headers(),
                # NOTE: field is named tenant_id but the VALUE is the BU slug.
                json={'workos_token': workos_token, 'tenant_id': tenant_slug},
            )
        except httpx.HTTPError as e:
            log.warning('IAM /resolve transport error for tenant=%s: %s', tenant_slug, type(e).__name__)
            raise TenantResolutionError(503, 'IAM service unreachable') from e

        if resp.status_code == 200:
            try:
                return ResolveResponse.model_validate(resp.json())
            except Exception as e:
                log.error('IAM /resolve returned an unparseable body for tenant=%s', tenant_slug)
                raise TenantResolutionError(502, 'invalid IAM response') from e
        detail = _safe_detail(resp)
        if resp.status_code in (401, 403, 404, 409):
            raise TenantResolutionError(resp.status_code, detail)
        log.warning('IAM /resolve unexpected status %s for tenant=%s', resp.status_code, tenant_slug)
        raise TenantResolutionError(502, f'unexpected IAM status {resp.status_code}')

    # --- IAM-JWT flow (primary; see IAM_INTEGRATION_GUIDE.md §1a, §5.0) --------

    async def exchange_token(self, workos_token: str) -> TokenExchangeResponse:
        """POST /token — exchange a WorkOS token for an IAM JWT carrying identity +
        the user's BUs, plus a refresh token. Done server-side at login.

        The ``refresh=True`` variant is gone: /token/refresh no longer takes a WorkOS
        token (it spends a refresh token instead). Use ``refresh_session``."""
        return await self._post_token('/token', {'workos_token': workos_token})

    async def refresh_session(self, refresh_token: str) -> TokenExchangeResponse:
        """POST /token/refresh — spend a refresh token: IAM rotates it, re-reads the
        user's memberships, and mints a fresh access token.

        Rotation is single-use. Presenting a spent token outside IAM's grace window
        is treated as possible theft and revokes every session for that user, so
        callers must never retry this with the same token — single-flight it."""
        return await self._post_token('/token/refresh', {'refresh_token': refresh_token})

    async def revoke_session(self, refresh_token: str, *, all_sessions: bool = True) -> None:
        """POST /token/revoke — end the session server-side. What sign-out calls.

        IAM answers 204 for unknown, live, and already-revoked tokens alike (it must
        not be an oracle), so a 204 does NOT confirm the token existed. Raises only on
        transport failure or an unexpected status; the caller is expected to clear
        cookies regardless — a user must never be trapped in a session because the
        control plane is unreachable."""
        client = self._get_client()
        try:
            resp = await client.post(
                '/token/revoke',
                headers=self._s2s_headers(),
                json={'refresh_token': refresh_token, 'all_sessions': all_sessions},
            )
        except httpx.HTTPError as e:
            log.warning('IAM /token/revoke transport error: %s', type(e).__name__)
            raise TenantResolutionError(503, 'IAM service unreachable') from e
        if resp.status_code in (200, 204):
            return
        raise TenantResolutionError(502, f'unexpected IAM status {resp.status_code}')

    async def _post_token(self, path: str, payload: dict) -> TokenExchangeResponse:
        client = self._get_client()
        try:
            # s2s creds identify schat on EVERY IAM call — same contract as
            # /resolve and /connection. Omitting them here made the whole
            # IAM-JWT flow 401 at login with no usable diagnostic.
            resp = await client.post(path, headers=self._s2s_headers(), json=payload)
        except httpx.HTTPError as e:
            log.warning('IAM %s transport error: %s', path, type(e).__name__)
            raise TenantResolutionError(503, 'IAM service unreachable') from e
        if resp.status_code == 200:
            try:
                return TokenExchangeResponse.model_validate(resp.json())
            except Exception as e:
                raise TenantResolutionError(502, 'invalid IAM response') from e
        detail = _safe_detail(resp)
        if resp.status_code in (401, 403):
            log.warning('IAM %s rejected the request (%s): %s', path, resp.status_code, detail)
            raise TenantResolutionError(resp.status_code, detail)
        raise TenantResolutionError(502, f'unexpected IAM status {resp.status_code}')

    async def verify_token(self, iam_token: str) -> TokenVerifyResponse:
        """POST /token/verify — introspect an IAM JWT (identity + tenants/roles).
        Returns ``active=False`` for an invalid/expired token (HTTP 200)."""
        client = self._get_client()
        try:
            resp = await client.post('/token/verify', headers=self._s2s_headers(), json={'token': iam_token})
        except httpx.HTTPError as e:
            log.warning('IAM /token/verify transport error: %s', type(e).__name__)
            raise TenantResolutionError(503, 'IAM service unreachable') from e
        if resp.status_code == 200:
            try:
                return TokenVerifyResponse.model_validate(resp.json())
            except Exception as e:
                raise TenantResolutionError(502, 'invalid IAM response') from e
        detail = _safe_detail(resp)
        if resp.status_code in (401, 403):
            raise TenantResolutionError(resp.status_code, detail)
        raise TenantResolutionError(502, f'unexpected IAM status {resp.status_code}')

    async def get_connection_for(self, iam_token: str, tenant_slug: str) -> ConnectionResponse:
        """POST /connection — the primary cred-fetch + authorization gate. s2s
        creds identify schat; the IAM JWT identifies the user. IAM re-checks
        membership live and fails closed (403) if the user isn't in the BU."""
        client = self._get_client()
        try:
            resp = await client.post(
                '/connection',
                headers=self._s2s_headers(),
                # NOTE: field is named tenant_id but the VALUE is the BU slug.
                json={'token': iam_token, 'tenant_id': tenant_slug},
            )
        except httpx.HTTPError as e:
            log.warning('IAM /connection transport error for tenant=%s: %s', tenant_slug, type(e).__name__)
            raise TenantResolutionError(503, 'IAM service unreachable') from e
        if resp.status_code == 200:
            try:
                return ConnectionResponse.model_validate(resp.json())
            except Exception as e:
                log.error('IAM /connection returned an unparseable body for tenant=%s', tenant_slug)
                raise TenantResolutionError(502, 'invalid IAM response') from e
        detail = _safe_detail(resp)
        if resp.status_code in (401, 403, 404, 409):
            raise TenantResolutionError(resp.status_code, detail)
        log.warning('IAM /connection unexpected status %s for tenant=%s', resp.status_code, tenant_slug)
        raise TenantResolutionError(502, f'unexpected IAM status {resp.status_code}')

    async def list_tenants(self, workos_token: str) -> list[TenantSummary]:
        """GET /me/tenants — the user's business units (workspace switcher)."""
        client = self._get_client()
        try:
            resp = await client.get('/me/tenants', headers={'Authorization': f'Bearer {workos_token}'})
        except httpx.HTTPError as e:
            log.warning('IAM /me/tenants transport error: %s', type(e).__name__)
            raise TenantResolutionError(503, 'IAM service unreachable') from e
        if resp.status_code == 200:
            try:
                tenants = resp.json().get('tenants', [])
                return [TenantSummary.model_validate(t) for t in tenants]
            except Exception as e:
                raise TenantResolutionError(502, 'invalid IAM response') from e
        detail = _safe_detail(resp)
        if resp.status_code in (401, 403, 404, 409):
            raise TenantResolutionError(resp.status_code, detail)
        raise TenantResolutionError(502, f'unexpected IAM status {resp.status_code}')

    async def get_connection(self, tenant_slug: str) -> ConnectionBundle:
        """GET /tenants/{slug}/connection — bundle only (cache refresh path)."""
        client = self._get_client()
        try:
            resp = await client.get(f'/tenants/{tenant_slug}/connection', headers=self._s2s_headers())
        except httpx.HTTPError as e:
            log.warning('IAM /connection transport error for tenant=%s: %s', tenant_slug, type(e).__name__)
            raise TenantResolutionError(503, 'IAM service unreachable') from e
        if resp.status_code == 200:
            try:
                return ConnectionBundle.model_validate(resp.json())
            except Exception as e:
                raise TenantResolutionError(502, 'invalid IAM response') from e
        detail = _safe_detail(resp)
        if resp.status_code in (401, 403, 404, 409):
            raise TenantResolutionError(resp.status_code, detail)
        raise TenantResolutionError(502, f'unexpected IAM status {resp.status_code}')

    # --- membership management (admin) ---------------------------------------
    #
    # These proxy IAM's control-plane member API. They authenticate with the
    # END USER's WorkOS token (Bearer), NOT the s2s creds: IAM authorizes the
    # action (BU-admin may manage 'user'-role members of their own BU; only a
    # super-admin may grant 'admin'). ``tenant_id`` is the tenant UUID.

    def _raise_iam_error(self, resp: httpx.Response) -> None:
        detail = _safe_detail(resp)
        if resp.status_code in (400, 401, 403, 404, 409):
            raise TenantResolutionError(resp.status_code, detail)
        raise TenantResolutionError(502, f'unexpected IAM status {resp.status_code}')

    async def list_members(self, workos_token: str, tenant_id: str) -> list[MemberRead]:
        client = self._get_client()
        try:
            resp = await client.get(
                f'/admin/tenants/{tenant_id}/members',
                headers={'Authorization': f'Bearer {workos_token}'},
            )
        except httpx.HTTPError as e:
            raise TenantResolutionError(503, 'IAM service unreachable') from e
        if resp.status_code == 200:
            try:
                return [MemberRead.model_validate(m) for m in resp.json()]
            except Exception as e:
                raise TenantResolutionError(502, 'invalid IAM response') from e
        self._raise_iam_error(resp)

    async def add_member(
        self,
        workos_token: str,
        tenant_id: str,
        *,
        email: str,
        role: str = 'user',
    ) -> MemberRead:
        # IAM identifies members by email only (role defaults to 'user').
        body: dict = {'email': email, 'role': role}
        client = self._get_client()
        try:
            resp = await client.post(
                f'/admin/tenants/{tenant_id}/members',
                headers={'Authorization': f'Bearer {workos_token}'},
                json=body,
            )
        except httpx.HTTPError as e:
            raise TenantResolutionError(503, 'IAM service unreachable') from e
        if resp.status_code in (200, 201):
            try:
                return MemberRead.model_validate(resp.json())
            except Exception as e:
                raise TenantResolutionError(502, 'invalid IAM response') from e
        self._raise_iam_error(resp)

    async def update_member(self, workos_token: str, tenant_id: str, member_email: str, role: str) -> MemberRead:
        client = self._get_client()
        try:
            resp = await client.patch(
                f'/admin/tenants/{tenant_id}/members/{quote(member_email, safe="")}',
                headers={'Authorization': f'Bearer {workos_token}'},
                json={'role': role},
            )
        except httpx.HTTPError as e:
            raise TenantResolutionError(503, 'IAM service unreachable') from e
        if resp.status_code == 200:
            try:
                return MemberRead.model_validate(resp.json())
            except Exception as e:
                raise TenantResolutionError(502, 'invalid IAM response') from e
        self._raise_iam_error(resp)

    async def remove_member(self, workos_token: str, tenant_id: str, member_email: str) -> None:
        client = self._get_client()
        try:
            resp = await client.delete(
                f'/admin/tenants/{tenant_id}/members/{quote(member_email, safe="")}',
                headers={'Authorization': f'Bearer {workos_token}'},
            )
        except httpx.HTTPError as e:
            raise TenantResolutionError(503, 'IAM service unreachable') from e
        if resp.status_code in (200, 204):
            return
        self._raise_iam_error(resp)


# ─────────────────────────────────────────────────────────────────────
# Resolver: verify (local) → cache → broker (IAM)
# ─────────────────────────────────────────────────────────────────────

# key = (iam_token_fingerprint, tenant_slug) -> (expiry_monotonic, TenantContext)
#
# The cache is keyed on a fingerprint of the IAM JWT — NEVER on decoded claims —
# so a forged token cannot collide with a genuine user's cached bundle. A hit
# only happens for the exact token that earned it via a validated /connection.
_bundle_cache: dict[tuple[str, str], tuple[float, TenantContext]] = {}


def clear_bundle_cache() -> None:
    _bundle_cache.clear()


def _iam_jwt_identity(iam_token: str) -> Identity:
    """Read identity (email, name) from an IAM JWT's payload.

    Called ONLY after ``POST /connection`` has validated the token at IAM, so
    trusting the payload here is safe — schat does not verify the signature
    itself (that is IAM's job; see IAM_INTEGRATION_GUIDE.md §1a). Never logs the
    token or its claims."""
    try:
        parts = iam_token.split('.')
        if len(parts) < 2:
            raise ValueError('not a JWT')
        payload_b64 = parts[1]
        payload_b64 += '=' * (-len(payload_b64) % 4)  # restore base64 padding
        claims = json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception as e:
        raise TenantResolutionError(502, 'malformed IAM token claims') from e
    email = claims.get(WORKOS_CLAIM_EMAIL) or claims.get('email')
    if not email:
        raise TenantResolutionError(502, 'IAM token carries no email claim')
    name = claims.get(WORKOS_CLAIM_NAME) or claims.get('name')
    return Identity(email=email, name=name)


class TenantResolver:
    """Resolves a ``TenantContext`` from an **IAM JWT** + BU slug via
    ``POST /connection``, caching the brokered bundle per (token, tenant) for
    ``TENANT_BUNDLE_CACHE_TTL`` seconds. /connection validates the token and
    re-checks membership live, so it — not schat — is the authorization gate."""

    def __init__(self, *, iam_client: Optional[IAMClient] = None):
        self._iam = iam_client or get_iam_client()

    def _now(self) -> float:
        return time.monotonic()

    async def resolve_context(self, iam_token: str, tenant_slug: str) -> TenantContext:
        if not tenant_slug:
            raise TenantResolutionError(400, 'missing tenant id')
        if not iam_token:
            raise TenantResolutionError(401, 'missing token')

        cache_key = (_token_fingerprint(iam_token), tenant_slug)
        now = self._now()
        cached = _bundle_cache.get(cache_key)
        if cached is not None and cached[0] > now:
            return cached[1]

        # Cache miss → POST /connection: validates the IAM JWT and re-checks
        # membership live (fails closed on 401/403/404/409). Identity is then
        # read from the now-validated token.
        conn = await self._iam.get_connection_for(iam_token, tenant_slug)
        identity = _iam_jwt_identity(iam_token)
        ctx = TenantContext.from_connection(conn, identity)
        _bundle_cache[cache_key] = (now + TENANT_BUNDLE_CACHE_TTL, ctx)
        log.debug('Resolved tenant=%s role=%s bundle=%s', ctx.slug, ctx.role, safe_bundle_summary(ctx.connection))
        return ctx


# ─────────────────────────────────────────────────────────────────────
# Module singletons
# ─────────────────────────────────────────────────────────────────────

_iam_client_singleton: Optional[IAMClient] = None
_verifier_singleton: Optional[WorkOSVerifier] = None


def get_iam_client() -> IAMClient:
    global _iam_client_singleton
    if _iam_client_singleton is None:
        _iam_client_singleton = IAMClient()
    return _iam_client_singleton


def get_workos_verifier() -> WorkOSVerifier:
    global _verifier_singleton
    if _verifier_singleton is None:
        _verifier_singleton = WorkOSVerifier()
    return _verifier_singleton


def get_tenant_resolver() -> TenantResolver:
    return TenantResolver(iam_client=get_iam_client())

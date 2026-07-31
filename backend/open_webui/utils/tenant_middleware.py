"""Tenant resolution middleware (pure ASGI).

Resolves the active business unit for each data-plane request and pins it onto
a ``ContextVar`` that the DB engine registry, Qdrant client, and storage
provider read. Fails closed: a tenant-scoped request that can't be resolved is
rejected here, before any store is touched.

Design notes
------------
* **Pure ASGI** (not ``BaseHTTPMiddleware``) to avoid the cancel-scope pitfalls
  documented in ``asgi_middleware.py``.
* Registered *after* ``AuthTokenMiddleware`` in ``main.py``; because
  ``add_middleware`` is LIFO this middleware actually runs BEFORE it on the
  request phase, so it does **not** rely on ``request.state.token`` — it
  extracts the credential itself, exactly like ``AuthTokenMiddleware`` does.
* Only *data-plane* paths (``/api/*``, ``/ollama*``, ``/openai*``) require a
  tenant. The SPA shell, static assets, health probes, the WorkOS/OAuth login
  flow, and the pre-login config/version bootstrap run in a **system context**
  (default/control-plane engine) so login and app-load work without a tenant.
"""

from __future__ import annotations

import logging

from fastapi.responses import JSONResponse
from open_webui.env import TENANT_ID_HEADER
from open_webui.utils.auth import get_http_authorization_cred
from open_webui.utils.tenant import (
    TenantResolutionError,
    get_tenant_resolver,
    reset_tenant_context,
    set_tenant_context,
    system_context,
)
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

log = logging.getLogger(__name__)


# Paths that must work WITHOUT a resolved tenant. They run inside a system
# context so any incidental DB access uses the default/control-plane engine
# instead of failing closed.
_SYSTEM_EXACT_PATHS = {
    '/',
    '/health',
    '/ready',
    '/health/db',
    '/healthz',
    '/api/config',
    '/api/version',
    '/api/version/updates',
    '/manifest.json',
    '/opensearch.xml',
    '/favicon.ico',
    '/favicon.png',
    '/robots.txt',
    # Pre-tenant bootstrap for the workspace gate: returns the user's BUs from
    # their IAM JWT so the frontend can block (empty ⇒ "contact your admin") or
    # switch. It has no tenant yet, so it must NOT require X-Tenant-Id.
    '/api/v1/tenant/me',
    # Renewing the IAM session cannot require a resolved tenant: an expired access
    # token is exactly why resolution just failed, so gating refresh on it would
    # deadlock the session at the first expiry. It also must work for a user with zero
    # memberships (parked on /no-access with no valid X-Tenant-Id).
    # Safe in a system context: the handler touches no tenant DB — it forwards the
    # httpOnly refresh cookie to IAM and rewrites cookies from the reply.
    '/api/v1/tenant/refresh',
    # Signing out must never depend on having a tenant. A user with zero business
    # unit memberships is parked on /no-access and has NO valid X-Tenant-Id to
    # send, so enforcing one here made signout 400 forever — cookies survived and
    # the user could not escape without clearing them by hand (todo.md T1.4).
    # Safe in a system context: the handler's only side effects are the Redis jti
    # blacklist and cookie deletion. Its one DB read is guarded on the
    # `oauth_session_id` cookie, which the multi-tenant sign-in path never sets
    # (utils/oauth.py:1548 returns before that branch).
    '/api/v1/auths/signout',
}

# NOTE: '/api/v1/auths' is deliberately NOT bypassed. Only a few of its endpoints
# are truly pre-login; most (get_session_user '/', '/update/*', '/api_key',
# '/admin/*') read or write the user record, which under multi-tenancy lives in
# the PER-TENANT DB. Running them in a system context would route them to the
# default DB — a fail-open (wrong-DB read/write). So they must resolve a tenant
# and fail closed if none. Under MT the client selects a business unit before
# signing in, so X-Tenant-Id is present on these requests. '/signout' is the one
# exception, listed individually above — never widen this to the whole prefix.
_SYSTEM_PATH_PREFIXES = (
    '/oauth',  # OAuth provider login/callback redirect flow (pre-tenant)
    '/ws',  # Socket.IO — NOT yet tenant-enforced (deferred; see MULTITENANCY_DEV_SETUP.md)
    '/static',
    '/assets',
    '/_app',  # SvelteKit build assets
    '/cache',
)

# Data-plane prefixes that DO require a resolved tenant.
_ENFORCE_PREFIXES = ('/api/', '/ollama', '/openai')


def _is_system_path(path: str) -> bool:
    if path in _SYSTEM_EXACT_PATHS:
        return True
    # Match on a path-segment boundary ONLY — never a bare prefix substring — so a
    # route like '/oauthx' or '/assetsdata' cannot slip into the bypass set.
    return any(path == p or path.startswith(p + '/') for p in _SYSTEM_PATH_PREFIXES)


def _requires_tenant(path: str) -> bool:
    if _is_system_path(path):
        return False
    return any(path.startswith(p) for p in _ENFORCE_PREFIXES)


class TenantResolutionMiddleware:
    """Resolve ``X-Tenant-Id`` + WorkOS token → ``TenantContext`` (fail closed)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._tenant_header = TENANT_ID_HEADER

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        path = scope.get('path', '')

        # Non-tenant paths (SPA shell, static, auth, health, bootstrap) run
        # against the system/default engine.
        if not _requires_tenant(path):
            with system_context():
                await self.app(scope, receive, send)
            return

        request = Request(scope)

        # Self-extract the IAM JWT — the credential minted at login. The browser
        # holds it in the httpOnly `iam_token` cookie, so the cookie is preferred:
        # the SPA also sends an Authorization bearer carrying the *schat* JWT,
        # which is NOT the IAM token. Non-browser API clients (no cookie) fall
        # back to presenting the IAM JWT as a bearer. Do NOT depend on
        # request.state.token (ordering — see docstring).
        iam_token = request.cookies.get('iam_token')
        if not iam_token:
            cred = get_http_authorization_cred(request.headers.get('Authorization'))
            iam_token = cred.credentials if cred is not None else None
        tenant_slug = request.headers.get(self._tenant_header)

        try:
            if not tenant_slug:
                raise TenantResolutionError(400, f'missing {self._tenant_header} header')
            if not iam_token:
                raise TenantResolutionError(401, 'not authenticated')
            resolver = get_tenant_resolver()
            ctx = await resolver.resolve_context(iam_token, tenant_slug)
        except TenantResolutionError as err:
            log.info('Tenant resolution denied path=%s status=%s detail=%s', path, err.status_code, err.detail)
            response = JSONResponse(status_code=err.status_code, content={'detail': err.detail})
            await response(scope, receive, send)
            return
        except Exception:
            # Fail closed on any unexpected error — never fall through untenanted.
            log.exception('Unexpected error during tenant resolution for path=%s', path)
            response = JSONResponse(status_code=500, content={'detail': 'tenant resolution failed'})
            await response(scope, receive, send)
            return

        token = set_tenant_context(ctx)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_tenant_context(token)

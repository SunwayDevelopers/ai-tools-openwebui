"""Tenant discovery for the workspace gate (pre-tenant bootstrap).

``GET /me`` returns the current user's identity + business units, read from
their IAM JWT via IAM introspection (``POST /token/verify``). The frontend uses
it to gate access:

* **empty ``tenants`` ⇒ block** with a "contact your administrator" screen
  (IAM_INTEGRATION_GUIDE.md §5.5 — a valid login does NOT imply access);
* one tenant ⇒ auto-select; multiple ⇒ show a switcher.

This runs BEFORE a tenant is selected, so it takes the IAM JWT directly (the
httpOnly ``iam_token`` cookie, or an Authorization bearer) and is exempt from
tenant enforcement in ``TenantResolutionMiddleware`` (the ``/api/v1/tenant/me``
path is in its system bypass). Mounted only when ``ENABLE_MULTI_TENANCY`` is on.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response
from open_webui.utils.auth import get_http_authorization_cred
from open_webui.utils.iam_session import (
    clear_iam_cookies,
    get_refresh_token,
    set_iam_cookies,
)
from open_webui.utils.tenant import TenantResolutionError, get_iam_client

log = logging.getLogger(__name__)

router = APIRouter()


def _iam_token(request: Request) -> str:
    """The caller's IAM JWT — httpOnly ``iam_token`` cookie (browser) or bearer."""
    token = request.cookies.get('iam_token')
    if not token:
        cred = get_http_authorization_cred(request.headers.get('Authorization'))
        token = cred.credentials if cred is not None else None
    if not token:
        raise HTTPException(status_code=401, detail='not authenticated')
    return token


@router.get('/me')
async def whoami(request: Request):
    """Identity + BUs from the IAM JWT. ``tenants: []`` ⇒ the frontend blocks
    access (fail-closed: /connection would 403 for a non-member regardless)."""
    token = _iam_token(request)
    try:
        result = await get_iam_client().verify_token(token)
    except TenantResolutionError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    if not result.active:
        raise HTTPException(status_code=401, detail='invalid or expired session')
    return {
        'identity': result.identity.model_dump() if result.identity else None,
        'tenants': [t.model_dump() for t in result.tenants],
    }


@router.post('/refresh')
async def refresh(request: Request, response: Response):
    """Renew the IAM session from the httpOnly refresh cookie.

    The access token is short-lived, so the SPA calls this when a request 401s (and
    proactively before expiry). Both credentials stay httpOnly: the request needs no body
    and **the response contains no token material** — only how long the new access token
    is good for, and the tenants it covers.

    Exempt from tenant enforcement in ``TenantResolutionMiddleware``: refresh is what fixes
    a failed tenant resolution, so it cannot require one. It also must work for a user with
    zero memberships, who has no valid ``X-Tenant-Id`` to send.

    On failure the cookies are cleared, so the SPA gets a clean 401 and can redirect to
    /auth instead of retrying against a session that is definitively gone.
    """
    refresh_token = get_refresh_token(request)
    if not refresh_token:
        raise HTTPException(status_code=401, detail='no refresh session')

    try:
        result = await get_iam_client().refresh_session(refresh_token)
    except TenantResolutionError as e:
        # 401/403 = the session is over (expired, revoked, replayed, de-provisioned).
        # 5xx = IAM is unwell; keep the cookies so a retry can still succeed once it
        # recovers, rather than logging everyone out over a transient blip (todo.md T1.5).
        if e.status_code in (401, 403):
            clear_iam_cookies(response)
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    set_iam_cookies(
        response,
        access_token=result.token,
        refresh_token=result.refresh_token,
        session_seconds=result.refresh_expires_in,
    )
    return {
        'expires_in': result.expires_in,
        'tenants': [t.model_dump() for t in result.tenants],
    }

"""Tenant membership management — a thin proxy to the IAM control-plane.

Lets a **BU admin** manage the members of the *active* tenant (incl. a bulk
add-by-email) and a **super-admin** grant the `admin` role. Authorization is
enforced by IAM from the caller's IAM JWT; this router only forwards it and
applies a first-line `get_admin_user` guard. Membership is the invite/allowlist
that gates all tenant access — there is no auto-provisioning of access here.

Mounted at ``/api/v1/tenant/members`` only when ``ENABLE_MULTI_TENANCY`` is on.
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from open_webui.utils.auth import get_admin_user, get_http_authorization_cred
from open_webui.utils.tenant import (
    TenantResolutionError,
    get_iam_client,
    require_tenant_context,
)
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter()

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _caller_token(request: Request) -> str:
    """The caller's IAM JWT — the httpOnly `iam_token` cookie (browser), or an
    Authorization bearer (non-browser). IAM authorizes the admin action from it."""
    token = request.cookies.get('iam_token')
    if not token:
        cred = get_http_authorization_cred(request.headers.get('Authorization'))
        token = cred.credentials if cred is not None else None
    if not token:
        raise HTTPException(status_code=401, detail='not authenticated')
    return token


def _iam_error(err: TenantResolutionError) -> HTTPException:
    return HTTPException(status_code=err.status_code, detail=err.detail)


class BulkAddForm(BaseModel):
    emails: list[str]
    role: str = 'user'


class UpdateRoleForm(BaseModel):
    role: str


@router.get('/')
async def list_members(request: Request, user=Depends(get_admin_user)):
    ctx = require_tenant_context()
    token = _caller_token(request)
    try:
        return await get_iam_client().list_members(token, ctx.tenant_id)
    except TenantResolutionError as e:
        raise _iam_error(e)


@router.post('/bulk')
async def bulk_add_members(form: BulkAddForm, request: Request, user=Depends(get_admin_user)):
    """Add many members by email in one call. Returns a per-email outcome so the
    UI can show a summary; one bad address never aborts the batch."""
    ctx = require_tenant_context()
    token = _caller_token(request)
    iam = get_iam_client()

    results: list[dict] = []
    seen: set[str] = set()
    for raw in form.emails:
        email = (raw or '').strip().lower()
        if not email:
            continue
        if not _EMAIL_RE.match(email):
            results.append({'email': raw, 'status': 'invalid'})
            continue
        if email in seen:
            results.append({'email': email, 'status': 'duplicate'})
            continue
        seen.add(email)
        try:
            await iam.add_member(token, ctx.tenant_id, email=email, role=form.role)
            results.append({'email': email, 'status': 'added'})
        except TenantResolutionError as e:
            if e.status_code == 409:
                results.append({'email': email, 'status': 'already_member'})
            elif e.status_code in (401, 403):
                # Authorization failures are not per-email — surface immediately.
                raise _iam_error(e)
            else:
                results.append({'email': email, 'status': 'error', 'detail': e.detail})

    added = sum(1 for r in results if r['status'] == 'added')
    return {'added': added, 'total': len(results), 'results': results}


@router.patch('/{member_email}')
async def update_member(member_email: str, form: UpdateRoleForm, request: Request, user=Depends(get_admin_user)):
    ctx = require_tenant_context()
    token = _caller_token(request)
    try:
        return await get_iam_client().update_member(token, ctx.tenant_id, member_email, form.role)
    except TenantResolutionError as e:
        raise _iam_error(e)


@router.delete('/{member_email}')
async def remove_member(member_email: str, request: Request, user=Depends(get_admin_user)):
    ctx = require_tenant_context()
    token = _caller_token(request)
    try:
        await get_iam_client().remove_member(token, ctx.tenant_id, member_email)
    except TenantResolutionError as e:
        raise _iam_error(e)
    return {'success': True}

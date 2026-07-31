"""Membership management: IAM client member methods + the bulk-add router (Phase 6B)."""

from __future__ import annotations

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

import open_webui.routers.tenant_members as R
from open_webui.test.conftest import run
from open_webui.utils import tenant as T
from open_webui.utils.tenant import TenantResolutionError


# ── IAMClient member methods (MockTransport) ──────────────────────────


def test_add_member_created(make_iam_client):
    def handler(req):
        assert req.url.path == '/admin/tenants/tid/members'
        assert req.headers['authorization'] == 'Bearer usertok'
        return httpx.Response(201, json={'id': 'm1', 'email': 'x@y.com', 'role': 'user', 'status': 'active'})

    iam = make_iam_client(handler)
    m = run(iam.add_member('usertok', 'tid', email='x@y.com', role='user'))
    assert m.email == 'x@y.com'
    assert m.role == 'user'


def test_add_member_conflict_raises_409(make_iam_client):
    def handler(req):
        return httpx.Response(409, json={'detail': 'membership already exists'})

    iam = make_iam_client(handler)
    with pytest.raises(TenantResolutionError) as ei:
        run(iam.add_member('usertok', 'tid', email='x@y.com'))
    assert ei.value.status_code == 409


def test_update_member_by_email_path(make_iam_client):
    def handler(req):
        assert req.method == 'PATCH'
        # email is identified in the path and URL-encoded on the wire ('@' -> '%40').
        assert req.url.raw_path == b'/admin/tenants/tid/members/x%40y.com'
        return httpx.Response(200, json={'id': 'm1', 'email': 'x@y.com', 'role': 'admin', 'status': 'active'})

    iam = make_iam_client(handler)
    m = run(iam.update_member('usertok', 'tid', 'x@y.com', 'admin'))
    assert m.role == 'admin'


def test_remove_member_by_email_path(make_iam_client):
    def handler(req):
        assert req.method == 'DELETE'
        assert req.url.raw_path == b'/admin/tenants/tid/members/x%40y.com'
        return httpx.Response(204)

    iam = make_iam_client(handler)
    run(iam.remove_member('usertok', 'tid', 'x@y.com'))  # no raise == success


def test_list_members(make_iam_client):
    def handler(req):
        assert req.method == 'GET'
        return httpx.Response(200, json=[{'id': 'm1', 'email': 'a@x.com', 'role': 'admin', 'status': 'active'}])

    iam = make_iam_client(handler)
    members = run(iam.list_members('usertok', 'tid'))
    assert len(members) == 1 and members[0].role == 'admin'


# ── bulk-add router ───────────────────────────────────────────────────


class _FakeIAM:
    def __init__(self):
        self.added = []

    async def add_member(self, token, tenant_id, *, email, role='user'):
        if email == 'dup@x.com':
            raise TenantResolutionError(409, 'membership already exists')
        self.added.append(email)


class _ForbiddenIAM:
    async def add_member(self, *a, **k):
        raise TenantResolutionError(403, 'super-admin required')


def _request():
    return Request({'type': 'http', 'headers': [(b'authorization', b'Bearer usertok')]})


def test_bulk_add_reports_per_email_outcomes(monkeypatch, make_context):
    ctx = make_context()
    tok = T.set_tenant_context(ctx)
    monkeypatch.setattr(R, 'get_iam_client', lambda: _FakeIAM())
    try:
        form = R.BulkAddForm(emails=['a@x.com', 'dup@x.com', 'bad', 'A@X.com', '  '], role='user')
        out = run(R.bulk_add_members(form, _request(), user=object()))
    finally:
        T.reset_tenant_context(tok)

    seq = [(r['email'], r['status']) for r in out['results']]
    assert ('a@x.com', 'added') in seq
    assert ('dup@x.com', 'already_member') in seq
    assert ('bad', 'invalid') in seq
    assert ('a@x.com', 'duplicate') in seq  # 'A@X.com' normalizes to a dup
    assert out['added'] == 1
    assert out['total'] == 4  # blank entry skipped


def test_bulk_add_auth_failure_aborts(monkeypatch, make_context):
    ctx = make_context()
    tok = T.set_tenant_context(ctx)
    monkeypatch.setattr(R, 'get_iam_client', lambda: _ForbiddenIAM())
    try:
        with pytest.raises(HTTPException) as ei:
            run(R.bulk_add_members(R.BulkAddForm(emails=['a@x.com']), _request(), user=object()))
        assert ei.value.status_code == 403
    finally:
        T.reset_tenant_context(tok)

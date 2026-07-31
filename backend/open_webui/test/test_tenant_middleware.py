"""TenantResolutionMiddleware: fail-closed denials, system passthrough, context set/reset."""

from __future__ import annotations

import open_webui.utils.tenant_middleware as MW
from open_webui.utils import tenant as T
from open_webui.utils.tenant import TenantResolutionError
from open_webui.test.conftest import run


class _Downstream:
    def __init__(self):
        self.called = False
        self.saw_system = None
        self.saw_tenant = None

    async def __call__(self, scope, receive, send):
        self.called = True
        self.saw_system = T.is_system_context()
        self.saw_tenant = T.get_tenant_context()
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'ok'})


async def _drive(mw, path, headers=None):
    scope = {
        'type': 'http',
        'path': path,
        'method': 'GET',
        'headers': [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
    }
    messages = []

    async def receive():
        return {'type': 'http.request', 'body': b'', 'more_body': False}

    async def send(m):
        messages.append(m)

    await mw(scope, receive, send)
    return messages


def _status(messages):
    for m in messages:
        if m['type'] == 'http.response.start':
            return m['status']
    return None


class _FakeResolver:
    def __init__(self, ctx=None, error=None):
        self._ctx = ctx
        self._error = error

    async def resolve_context(self, token, slug):
        if self._error:
            raise self._error
        return self._ctx


def test_enforced_path_missing_tenant_header_fails_closed():
    down = _Downstream()
    mw = MW.TenantResolutionMiddleware(down)
    messages = run(_drive(mw, '/api/v1/chats/', headers={'Authorization': 'Bearer tok'}))
    assert _status(messages) == 400
    assert down.called is False


def test_enforced_path_missing_token_fails_closed():
    down = _Downstream()
    mw = MW.TenantResolutionMiddleware(down)
    messages = run(_drive(mw, '/api/v1/chats/', headers={'X-Tenant-Id': 'acme-sales'}))
    assert _status(messages) == 401
    assert down.called is False


def test_system_path_bypasses_in_system_context():
    down = _Downstream()
    mw = MW.TenantResolutionMiddleware(down)
    messages = run(_drive(mw, '/api/config'))
    assert _status(messages) == 200
    assert down.called is True
    assert down.saw_system is True
    assert down.saw_tenant is None


def test_spa_path_bypasses_in_system_context():
    down = _Downstream()
    mw = MW.TenantResolutionMiddleware(down)
    messages = run(_drive(mw, '/'))
    assert _status(messages) == 200
    assert down.called is True
    assert down.saw_system is True


def test_authenticated_auth_endpoint_requires_tenant():
    # /api/v1/auths/* is NOT blanket-bypassed: endpoints that touch the (per-tenant)
    # user record must resolve a tenant and fail closed, never run against the
    # system DB. Without X-Tenant-Id this is a 400, not a system-context passthrough.
    down = _Downstream()
    mw = MW.TenantResolutionMiddleware(down)
    messages = run(_drive(mw, '/api/v1/auths/update/password', headers={'Authorization': 'Bearer tok'}))
    assert _status(messages) == 400
    assert down.called is False


def test_prefix_substring_does_not_bypass():
    # A route that merely shares a prefix string with a system prefix (e.g.
    # '/oauthx') must NOT slip into the bypass set — matching is on a
    # path-segment boundary only.
    assert MW._is_system_path('/oauth') is True
    assert MW._is_system_path('/oauth/callback') is True
    assert MW._is_system_path('/oauthx') is False
    assert MW._is_system_path('/assetsdata') is False


def test_success_sets_and_resets_context(monkeypatch, make_context):
    ctx = make_context(slug='acme-sales')
    monkeypatch.setattr(MW, 'get_tenant_resolver', lambda: _FakeResolver(ctx=ctx))
    down = _Downstream()
    mw = MW.TenantResolutionMiddleware(down)
    messages = run(
        _drive(mw, '/api/v1/chats/', headers={'Authorization': 'Bearer tok', 'X-Tenant-Id': 'acme-sales'})
    )
    assert _status(messages) == 200
    assert down.called is True
    assert down.saw_tenant is ctx  # context visible to the route
    assert down.saw_system is False
    assert T.get_tenant_context() is None  # reset after the request


def test_resolution_error_propagates_status(monkeypatch):
    monkeypatch.setattr(
        MW,
        'get_tenant_resolver',
        lambda: _FakeResolver(error=TenantResolutionError(403, 'no membership for that business unit')),
    )
    down = _Downstream()
    mw = MW.TenantResolutionMiddleware(down)
    messages = run(
        _drive(mw, '/api/v1/chats/', headers={'Authorization': 'Bearer tok', 'X-Tenant-Id': 'nope'})
    )
    assert _status(messages) == 403
    assert down.called is False

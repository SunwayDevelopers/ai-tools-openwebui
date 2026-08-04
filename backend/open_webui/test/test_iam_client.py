"""IAMClient: contract parsing, error mapping, transport failures, s2s auth."""

from __future__ import annotations

import httpx
import pytest

from open_webui.utils.tenant import IAMClient, TenantResolutionError
from open_webui.test.conftest import run, sample_connection_body, sample_resolve_body


def test_resolve_success_parses_contract(make_iam_client):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured['url'] = str(request.url)
        captured['headers'] = request.headers
        import json

        captured['body'] = json.loads(request.content)
        return httpx.Response(200, json=sample_resolve_body())

    client = make_iam_client(handler)
    res = run(client.resolve('the-workos-token', 'acme-sales'))

    assert res.tenant.slug == 'acme-sales'
    assert res.role == 'admin'
    assert res.identity.email == 'a@acme.com'
    assert res.connection.database.db_name == 'schat_acme_sales'
    assert res.connection.qdrant.collection_prefix == 'acme_sales_'
    assert res.connection.storage.bucket == 'schat-acme'

    # s2s headers present; body uses tenant_id=slug per the contract.
    assert captured['url'].endswith('/resolve')
    assert captured['headers']['X-Client-Id'] == 'schat'
    assert captured['headers']['X-Client-Secret'] == 'svc-secret'
    assert captured['body'] == {'workos_token': 'the-workos-token', 'tenant_id': 'acme-sales'}


@pytest.mark.parametrize(
    'status,detail',
    [
        (401, 'invalid token'),
        (403, 'no membership for that business unit'),
        (404, 'unknown business unit'),
        (409, 'business unit suspended'),
    ],
)
def test_resolve_maps_documented_errors(make_iam_client, status, detail):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={'detail': detail})

    client = make_iam_client(handler)
    with pytest.raises(TenantResolutionError) as ei:
        run(client.resolve('t', 'acme-sales'))
    assert ei.value.status_code == status
    assert ei.value.detail == detail


def test_resolve_transport_error_fails_closed_503(make_iam_client):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError('connection refused')

    client = make_iam_client(handler)
    with pytest.raises(TenantResolutionError) as ei:
        run(client.resolve('t', 'acme-sales'))
    assert ei.value.status_code == 503


def test_resolve_unexpected_status_maps_502(make_iam_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={'detail': 'boom'})

    client = make_iam_client(handler)
    with pytest.raises(TenantResolutionError) as ei:
        run(client.resolve('t', 'acme-sales'))
    assert ei.value.status_code == 502


def test_resolve_unparseable_body_maps_502(make_iam_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={'identity': {}})  # missing required fields

    client = make_iam_client(handler)
    with pytest.raises(TenantResolutionError) as ei:
        run(client.resolve('t', 'acme-sales'))
    assert ei.value.status_code == 502


def test_missing_s2s_credentials_fails_closed_500(monkeypatch):
    # Force the env fallback to be empty so this is hermetic even when the local
    # .env defines IAM_CLIENT_ID/SECRET (IAMClient() falls back to those).
    monkeypatch.setattr('open_webui.utils.tenant.IAM_CLIENT_ID', None)
    monkeypatch.setattr('open_webui.utils.tenant.IAM_CLIENT_SECRET', None)
    client = IAMClient(client_id=None, client_secret=None, http_client=httpx.AsyncClient())
    with pytest.raises(TenantResolutionError) as ei:
        run(client.resolve('t', 'acme-sales'))
    assert ei.value.status_code == 500


def test_list_tenants_success(make_iam_client):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers['Authorization'] == 'Bearer jwt-abc'
        return httpx.Response(
            200,
            json={'tenants': [
                {'id': 'u1', 'slug': 'acme-sales', 'name': 'Acme Sales', 'role': 'admin'},
                {'id': 'u2', 'slug': 'beta', 'name': 'Beta', 'role': 'user'},
            ]},
        )

    client = make_iam_client(handler)
    tenants = run(client.list_tenants('jwt-abc'))
    assert [t.slug for t in tenants] == ['acme-sales', 'beta']
    assert tenants[1].role == 'user'


def test_get_connection_only(make_iam_client):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == '/tenants/acme-sales/connection'
        return httpx.Response(200, json=sample_resolve_body()['connection'])

    client = make_iam_client(handler)
    bundle = run(client.get_connection('acme-sales'))
    assert bundle.database.host == 'db.internal'
    assert bundle.storage.prefix == 'acme-sales/'


# ── IAM-JWT flow: /token, /token/verify, /connection ──────────────────


def test_exchange_token_success(make_iam_client):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured['path'] = request.url.path
        captured['body'] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                'token': 'iam-jwt-xyz',
                'token_type': 'bearer',
                'expires_in': 900,
                'identity': {'email': 'a@acme.com', 'name': 'Ada'},
                'tenants': [{'slug': 'acme-sales', 'name': 'Acme Sales', 'role': 'admin'}],
            },
        )

    client = make_iam_client(handler)
    res = run(client.exchange_token('the-workos-token'))
    assert res.token == 'iam-jwt-xyz'
    assert res.expires_in == 900
    assert res.identity.email == 'a@acme.com'
    assert [t.slug for t in res.tenants] == ['acme-sales']
    assert captured['path'] == '/token'
    assert captured['body'] == {'workos_token': 'the-workos-token'}


def test_exchange_token_empty_tenants_is_ok(make_iam_client):
    # A valid login with no memberships → 200 with tenants:[] (the frontend gates).
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={'token': 't', 'identity': {'email': 'x@y.com'}, 'tenants': []})

    client = make_iam_client(handler)
    res = run(client.exchange_token('w'))
    assert res.tenants == []


def test_refresh_session_spends_the_refresh_token(make_iam_client):
    """/token/refresh takes a REFRESH token, not a WorkOS one. The old
    ``exchange_token(refresh=True)`` re-exchanged an IdP credential and gave IAM nothing
    to revoke; rotation replaced it."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured['path'] = request.url.path
        captured['body'] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                'token': 't2',
                'expires_in': 300,
                'refresh_token': 'r2',
                'refresh_expires_in': 250000,
                'identity': {'email': 'a@acme.com'},
                'tenants': [],
            },
        )

    client = make_iam_client(handler)
    res = run(client.refresh_session('r1'))
    assert captured['path'] == '/token/refresh'
    assert captured['body'] == {'refresh_token': 'r1'}
    assert (res.token, res.refresh_token) == ('t2', 'r2')


def test_refresh_grace_response_carries_no_refresh_token(make_iam_client):
    """IAM omits refresh_token on its reuse-grace path, meaning "keep the one you have".
    Treating a missing value as an error (or as empty) would break the racing-tab case."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={'token': 't3', 'expires_in': 300, 'identity': {'email': 'a@acme.com'}, 'tenants': []},
        )

    res = run(make_iam_client(handler).refresh_session('r1'))
    assert res.token == 't3'
    assert res.refresh_token is None


def test_revoke_session_posts_all_sessions_by_default(make_iam_client):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured['path'] = request.url.path
        captured['body'] = json.loads(request.content)
        return httpx.Response(204)

    run(make_iam_client(handler).revoke_session('r1'))
    assert captured['path'] == '/token/revoke'
    assert captured['body'] == {'refresh_token': 'r1', 'all_sessions': True}


def test_verify_token_active(make_iam_client):
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        assert request.url.path == '/token/verify'
        assert json.loads(request.content) == {'token': 'iam-jwt'}
        return httpx.Response(
            200,
            json={'active': True, 'identity': {'email': 'a@acme.com'}, 'tenants': [{'slug': 'acme-sales', 'role': 'admin'}]},
        )

    client = make_iam_client(handler)
    res = run(client.verify_token('iam-jwt'))
    assert res.active is True
    assert res.identity.email == 'a@acme.com'
    assert res.tenants[0].slug == 'acme-sales'


def test_verify_token_inactive(make_iam_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={'active': False})

    client = make_iam_client(handler)
    res = run(client.verify_token('bad'))
    assert res.active is False
    assert res.tenants == []


def test_get_connection_for_success(make_iam_client):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured['path'] = request.url.path
        captured['headers'] = request.headers
        captured['body'] = json.loads(request.content)
        return httpx.Response(200, json=sample_connection_body(slug='acme-sales'))

    client = make_iam_client(handler)
    res = run(client.get_connection_for('iam-jwt', 'acme-sales'))
    assert res.tenant_id == 'acme-sales'
    assert res.role == 'admin'
    assert res.connection.database.db_name == 'schat_acme_sales'
    # s2s creds identify schat; the IAM JWT + slug identify the user + BU.
    assert captured['path'] == '/connection'
    assert captured['headers']['X-Client-Id'] == 'schat'
    assert captured['body'] == {'token': 'iam-jwt', 'tenant_id': 'acme-sales'}


@pytest.mark.parametrize('status', [401, 403, 404, 409])
def test_get_connection_for_fails_closed(make_iam_client, status):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={'detail': 'denied'})

    client = make_iam_client(handler)
    with pytest.raises(TenantResolutionError) as ei:
        run(client.get_connection_for('iam-jwt', 'acme-sales'))
    assert ei.value.status_code == status

"""TenantResolver: /connection cred-fetch, cache hit/expiry, fail-closed inputs.

The resolver keys its bundle cache on a fingerprint of the IAM JWT and reads
identity from the (IAM-validated) token payload — so the tokens here are real
(unsigned) JWTs built by ``make_iam_jwt``."""

from __future__ import annotations

import pytest

from open_webui.utils import tenant as T
from open_webui.utils.tenant import (
    ConnectionResponse,
    TenantResolver,
    TenantResolutionError,
)
from open_webui.test.conftest import make_iam_jwt, run, sample_connection_body

TOK = make_iam_jwt(email='a@acme.com', name='Ada')


class _FakeIAM:
    """Counts get_connection_for() calls; returns a fixed bundle per slug."""

    def __init__(self):
        self.calls = 0

    async def get_connection_for(self, iam_token, tenant_slug):
        self.calls += 1
        return ConnectionResponse.model_validate(sample_connection_body(slug=tenant_slug))


def _resolver(iam):
    return TenantResolver(iam_client=iam)


def test_resolve_returns_context():
    iam = _FakeIAM()
    ctx = run(_resolver(iam).resolve_context(TOK, 'acme-sales'))
    assert ctx.slug == 'acme-sales'
    assert ctx.role == 'admin'
    assert ctx.identity.email == 'a@acme.com'  # sourced from the IAM JWT payload
    assert iam.calls == 1


def test_cache_hit_within_ttl():
    iam = _FakeIAM()
    r = _resolver(iam)
    run(r.resolve_context(TOK, 'acme-sales'))
    run(r.resolve_context(TOK, 'acme-sales'))
    assert iam.calls == 1  # second call served from cache


def test_different_tenant_not_cached_together():
    iam = _FakeIAM()
    r = _resolver(iam)
    run(r.resolve_context(TOK, 'acme-sales'))
    run(r.resolve_context(TOK, 'beta'))
    assert iam.calls == 2


def test_different_token_not_cached_together():
    iam = _FakeIAM()
    r = _resolver(iam)
    run(r.resolve_context(make_iam_jwt(email='a@acme.com'), 'acme-sales'))
    run(r.resolve_context(make_iam_jwt(email='b@acme.com'), 'acme-sales'))
    assert iam.calls == 2  # distinct tokens -> distinct cache keys


def test_ttl_expiry_refetches(monkeypatch):
    monkeypatch.setattr(T, 'TENANT_BUNDLE_CACHE_TTL', 0)
    iam = _FakeIAM()
    r = _resolver(iam)
    run(r.resolve_context(TOK, 'acme-sales'))
    run(r.resolve_context(TOK, 'acme-sales'))
    assert iam.calls == 2  # TTL=0 -> every call misses


def test_missing_slug_fails_closed():
    with pytest.raises(TenantResolutionError) as ei:
        run(_resolver(_FakeIAM()).resolve_context(TOK, ''))
    assert ei.value.status_code == 400


def test_missing_token_fails_closed():
    with pytest.raises(TenantResolutionError) as ei:
        run(_resolver(_FakeIAM()).resolve_context('', 'acme-sales'))
    assert ei.value.status_code == 401

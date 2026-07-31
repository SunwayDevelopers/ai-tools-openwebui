"""Per-tenant async engine registry: DSN building, fail-closed gate, caching, LRU.

Engine construction is faked so these stay pure unit tests (no DB driver / no
connection)."""

from __future__ import annotations

import pytest

import open_webui.internal.db as db
from open_webui.utils.tenant import (
    TenantContextError,
    reset_tenant_context,
    set_tenant_context,
    system_context,
)


def test_build_tenant_async_url(make_context):
    url = db._build_tenant_async_url(make_context().connection.database)
    assert url == 'postgresql+psycopg://schat_app:sup3r-secret@db.internal:5432/schat_acme_sales'


def test_build_tenant_async_url_encodes_credentials(make_context):
    ctx = make_context(
        **{
            'connection.database.username': 'user name',
            'connection.database.password': 'p@ss/w:rd',
        }
    )
    url = db._build_tenant_async_url(ctx.connection.database)
    assert 'user%20name' in url
    assert 'p%40ss%2Fw%3Ard' in url


def test_resolver_flag_off_returns_default(monkeypatch):
    monkeypatch.setattr(db, 'ENABLE_MULTI_TENANCY', False)
    assert db._resolve_async_sessionmaker() is db.AsyncSessionLocal


def test_resolver_system_context_returns_default(monkeypatch):
    monkeypatch.setattr(db, 'ENABLE_MULTI_TENANCY', True)
    with system_context():
        assert db._resolve_async_sessionmaker() is db.AsyncSessionLocal


def test_resolver_fails_closed_without_context(monkeypatch):
    monkeypatch.setattr(db, 'ENABLE_MULTI_TENANCY', True)
    with pytest.raises(TenantContextError):
        db._resolve_async_sessionmaker()


def _fake_builder():
    """Return (builder, built_ids) where builder yields unique sentinel makers."""
    built = []

    def build(tenant_ctx):
        built.append(tenant_ctx.tenant_id)
        return object(), object()  # (engine, sessionmaker)

    return build, built


def test_resolver_tenant_context_builds_and_caches(monkeypatch, make_context):
    monkeypatch.setattr(db, 'ENABLE_MULTI_TENANCY', True)
    monkeypatch.setattr(db, 'TENANT_ENGINE_CACHE_SIZE', 50)
    db._tenant_sessionmakers.clear()
    build, built = _fake_builder()
    monkeypatch.setattr(db, '_build_tenant_sessionmaker', build)

    tok = set_tenant_context(make_context(slug='acme-sales'))
    try:
        sm1 = db._resolve_async_sessionmaker()
        sm2 = db._resolve_async_sessionmaker()
        assert sm1 is sm2  # cached per tenant
    finally:
        reset_tenant_context(tok)

    tok2 = set_tenant_context(make_context(slug='beta'))
    try:
        sm3 = db._resolve_async_sessionmaker()
        assert sm3 is not sm1  # distinct tenant -> distinct sessionmaker
    finally:
        reset_tenant_context(tok2)

    assert built == ['tenant-acme-sales', 'tenant-beta']


def test_lru_eviction(monkeypatch, make_context):
    monkeypatch.setattr(db, 'ENABLE_MULTI_TENANCY', True)
    monkeypatch.setattr(db, 'TENANT_ENGINE_CACHE_SIZE', 2)
    db._tenant_sessionmakers.clear()
    build, _ = _fake_builder()
    monkeypatch.setattr(db, '_build_tenant_sessionmaker', build)

    for slug in ('bu0', 'bu1', 'bu2'):
        tok = set_tenant_context(make_context(slug=slug))
        try:
            db._resolve_async_sessionmaker()
        finally:
            reset_tenant_context(tok)

    ids = list(db._tenant_sessionmakers.keys())
    assert len(ids) == 2  # cap enforced
    assert 'tenant-bu0' not in ids  # oldest evicted
    assert ids == ['tenant-bu1', 'tenant-bu2']

"""Per-tenant storage: connection→provider factory, proxy resolution, fail-closed."""

from __future__ import annotations

import pytest

import open_webui.storage.provider as P
from open_webui.utils.tenant import (
    TenantContextError,
    reset_tenant_context,
    set_tenant_context,
    system_context,
)


def test_build_provider_from_connection_s3(make_context):
    provider = P.build_provider_from_connection(make_context().connection.storage)
    assert isinstance(provider, P.S3StorageProvider)
    assert provider.bucket_name == 'schat-acme'
    assert provider.key_prefix == 'acme-sales/'


def test_build_provider_missing_bucket_fails_closed(make_context):
    sc = make_context(**{'connection.storage.bucket': None}).connection.storage
    with pytest.raises(RuntimeError):
        P.build_provider_from_connection(sc)


def test_build_provider_missing_provider_fails_closed(make_context):
    sc = make_context(**{'connection.storage.provider': None}).connection.storage
    with pytest.raises(RuntimeError):
        P.build_provider_from_connection(sc)


def test_build_provider_unknown_provider_fails_closed(make_context):
    sc = make_context(**{'connection.storage.provider': 'gcs'}).connection.storage
    with pytest.raises(RuntimeError):
        P.build_provider_from_connection(sc)


def test_proxy_flag_off_uses_default(monkeypatch):
    monkeypatch.setattr(P, 'ENABLE_MULTI_TENANCY', False)
    default = P.LocalStorageProvider()
    assert P._TenantStorageProxy(default)._resolve() is default


def test_proxy_system_context_uses_default(monkeypatch):
    monkeypatch.setattr(P, 'ENABLE_MULTI_TENANCY', True)
    default = P.LocalStorageProvider()
    proxy = P._TenantStorageProxy(default)
    with system_context():
        assert proxy._resolve() is default


def test_proxy_fails_closed_without_context(monkeypatch):
    monkeypatch.setattr(P, 'ENABLE_MULTI_TENANCY', True)
    proxy = P._TenantStorageProxy(P.LocalStorageProvider())
    with pytest.raises(TenantContextError):
        proxy._resolve()


def test_proxy_tenant_context_builds_and_caches(monkeypatch, make_context):
    monkeypatch.setattr(P, 'ENABLE_MULTI_TENANCY', True)
    proxy = P._TenantStorageProxy(P.LocalStorageProvider())
    tok = set_tenant_context(make_context())
    try:
        p1 = proxy._resolve()
        p2 = proxy._resolve()
        assert isinstance(p1, P.S3StorageProvider)
        assert p1 is p2  # cached per tenant
        assert p1.bucket_name == 'schat-acme'
    finally:
        reset_tenant_context(tok)

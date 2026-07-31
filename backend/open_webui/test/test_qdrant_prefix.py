"""Qdrant per-tenant collection prefixing + fail-closed."""

from __future__ import annotations

import pytest

import open_webui.retrieval.vector.dbs.qdrant as Q
from open_webui.utils.tenant import (
    TenantContextError,
    reset_tenant_context,
    set_tenant_context,
)


def _client():
    # __init__ reads QDRANT_URI from config; unset -> self.client is None, which
    # is fine because the prefix helpers under test never touch the client.
    return Q.QdrantClient()


def test_physical_name_flag_off(monkeypatch):
    monkeypatch.setattr(Q, 'ENABLE_MULTI_TENANCY', False)
    client = _client()
    name = client._physical_name('file-1')
    assert name == f'{client.collection_prefix}_file-1'


def test_physical_name_tenant_scoped(monkeypatch, make_context):
    monkeypatch.setattr(Q, 'ENABLE_MULTI_TENANCY', True)
    client = _client()
    tok = set_tenant_context(make_context(slug='acme-sales'))  # prefix 'acme_sales_'
    try:
        assert client._collection_prefix() == 'acme_sales_'
        assert client._physical_name('file-1') == 'acme_sales_file-1'
        assert client._physical_name('user-memory-42') == 'acme_sales_user-memory-42'
    finally:
        reset_tenant_context(tok)


def test_two_tenants_get_distinct_names(monkeypatch, make_context):
    monkeypatch.setattr(Q, 'ENABLE_MULTI_TENANCY', True)
    client = _client()
    tok = set_tenant_context(make_context(slug='acme-sales'))
    try:
        a = client._physical_name('file-1')
    finally:
        reset_tenant_context(tok)
    tok = set_tenant_context(make_context(slug='beta'))
    try:
        b = client._physical_name('file-1')
    finally:
        reset_tenant_context(tok)
    assert a == 'acme_sales_file-1'
    assert b == 'beta_file-1'
    assert a != b


def test_physical_name_fails_closed_without_context(monkeypatch):
    monkeypatch.setattr(Q, 'ENABLE_MULTI_TENANCY', True)
    client = _client()
    with pytest.raises(TenantContextError):
        client._physical_name('file-1')


def test_physical_name_empty_prefix_fails_closed(monkeypatch, make_context):
    monkeypatch.setattr(Q, 'ENABLE_MULTI_TENANCY', True)
    client = _client()
    tok = set_tenant_context(make_context(**{'connection.qdrant.collection_prefix': ''}))
    try:
        with pytest.raises(TenantContextError):
            client._physical_name('file-1')
    finally:
        reset_tenant_context(tok)

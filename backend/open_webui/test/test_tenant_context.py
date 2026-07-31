"""Tenant context accessors, fail-closed semantics, secret-safe logging."""

from __future__ import annotations

import pytest

from open_webui.utils import tenant as T


def test_require_fails_closed_when_empty():
    assert T.get_tenant_context() is None
    with pytest.raises(T.TenantContextError):
        T.require_tenant_context()


def test_set_get_reset(make_context):
    ctx = make_context()
    token = T.set_tenant_context(ctx)
    try:
        assert T.get_tenant_context() is ctx
        assert T.require_tenant_context() is ctx
    finally:
        T.reset_tenant_context(token)
    assert T.get_tenant_context() is None


def test_system_context_toggle():
    assert T.is_system_context() is False
    with T.system_context():
        assert T.is_system_context() is True
    assert T.is_system_context() is False


def test_system_context_manual_enter_exit():
    token = T.enter_system_context()
    assert T.is_system_context() is True
    T.exit_system_context(token)
    assert T.is_system_context() is False


def test_context_maps_fields(make_context):
    ctx = make_context(slug='beta', role='user')
    assert ctx.slug == 'beta'
    assert ctx.role == 'user'
    assert ctx.identity.email == 'a@acme.com'
    assert ctx.connection.qdrant.collection_prefix == 'beta_'


def test_safe_bundle_summary_redacts_secrets(make_context):
    ctx = make_context()
    summary = T.safe_bundle_summary(ctx.connection)
    flat = str(summary)
    # No secret value may appear anywhere in the log-safe summary.
    assert 'sup3r-secret' not in flat  # db password
    assert 'minioadmin' not in flat  # storage access/secret keys
    # Non-secret operational fields are preserved.
    assert summary['database']['username'] == 'schat_app'
    assert summary['database']['db_name'] == 'schat_acme_sales'
    assert summary['storage']['bucket'] == 'schat-acme'
    assert summary['qdrant']['api_key'] is None


def test_safe_bundle_summary_masks_qdrant_api_key(make_context):
    ctx = make_context(**{'connection.qdrant.api_key': 'qdrant-secret-key'})
    summary = T.safe_bundle_summary(ctx.connection)
    assert summary['qdrant']['api_key'] == '***'
    assert 'qdrant-secret-key' not in str(summary)

"""Shared fixtures for the multi-tenancy unit tests.

These are pure unit tests: no Postgres, Qdrant, MinIO, or live IAM. The IAM
HTTP client is exercised with ``httpx.MockTransport`` (in-tree, no respx dep),
and async code is driven from sync tests via ``asyncio.run`` (so pytest-asyncio
is not required).
"""

from __future__ import annotations

# NOTE: set before ANY open_webui import. Importing open_webui.config connects to
# the DB at import time; point it at a throwaway SQLite so these unit tests need
# no Postgres. Also provide a secret key so auth imports don't complain. Multi-
# tenancy defaults off globally; per-module tests flip the flag with monkeypatch.
import os as _os
import tempfile as _tempfile

_os.environ.setdefault('WEBUI_SECRET_KEY', 'test-secret-key')
_os.environ.setdefault('ENABLE_MULTI_TENANCY', 'false')
if 'postgres' in _os.environ.get('DATABASE_URL', '') or 'DATABASE_URL' not in _os.environ:
    _os.environ['DATABASE_URL'] = f'sqlite:///{_os.path.join(_tempfile.mkdtemp(prefix="owui-mt-test-"), "test.db")}'

import asyncio
import base64 as _base64
import json as _json

import httpx
import pytest


def run(coro):
    """Drive a coroutine to completion from a sync test."""
    return asyncio.run(coro)


def make_iam_jwt(email: str = 'a@acme.com', name: str = 'Ada', **extra) -> str:
    """Build a fake IAM JWT (unsigned) whose payload carries the given claims.

    The resolver reads identity from the payload only AFTER /connection has
    validated the token at IAM, so tests never need a real signature."""

    def _seg(obj: dict) -> str:
        raw = _json.dumps(obj).encode()
        return _base64.urlsafe_b64encode(raw).rstrip(b'=').decode()

    payload = {'email': email, 'name': name, **extra}
    return f'{_seg({"alg": "none"})}.{_seg(payload)}.sig'


# A complete, contract-shaped /resolve 200 body for tenant 'acme-sales'.
def sample_resolve_body(slug: str = 'acme-sales', role: str = 'admin') -> dict:
    return {
        'identity': {
            'email': 'a@acme.com',
            'name': 'Ada',
        },
        'tenant': {'id': f'tenant-{slug}', 'slug': slug, 'status': 'active'},
        'role': role,
        'connection': {
            'database': {
                'host': 'db.internal',
                'port': 5432,
                'db_name': f'schat_{slug.replace("-", "_")}',
                'username': 'schat_app',
                'password': 'sup3r-secret',
            },
            'qdrant': {
                'url': 'http://localhost:6333',
                'collection_prefix': f'{slug.replace("-", "_")}_',
                'api_key': None,
            },
            'storage': {
                'provider': 's3',
                'endpoint': 'http://localhost:9000',
                'access_key': 'minioadmin',
                'secret_key': 'minioadmin',
                'bucket': 'schat-acme',
                'prefix': f'{slug}/',
            },
        },
    }


def _sample_connection_bundle(slug: str) -> dict:
    return {
        'database': {
            'host': 'db.internal',
            'port': 5432,
            'db_name': f'schat_{slug.replace("-", "_")}',
            'username': 'schat_app',
            'password': 'sup3r-secret',
        },
        'qdrant': {
            'url': 'http://localhost:6333',
            'collection_prefix': f'{slug.replace("-", "_")}_',
            'api_key': None,
        },
        'storage': {
            'provider': 's3',
            'endpoint': 'http://localhost:9000',
            'access_key': 'minioadmin',
            'secret_key': 'minioadmin',
            'bucket': 'schat-acme',
            'prefix': f'{slug}/',
        },
    }


# A contract-shaped POST /connection 200 body (the primary path — no identity
# block; tenant_id echoes the slug).
def sample_connection_body(slug: str = 'acme-sales', role: str = 'admin') -> dict:
    return {'tenant_id': slug, 'role': role, 'connection': _sample_connection_bundle(slug)}


@pytest.fixture
def resolve_body():
    return sample_resolve_body


@pytest.fixture
def make_iam_client():
    """Return a factory: given a request->httpx.Response handler, build an
    IAMClient wired to an httpx.AsyncClient(MockTransport(handler))."""
    from open_webui.utils.tenant import IAMClient

    def _factory(handler, *, client_id='schat', client_secret='svc-secret'):
        transport = httpx.MockTransport(handler)
        http_client = httpx.AsyncClient(transport=transport, base_url='http://iam.test')
        return IAMClient(client_id=client_id, client_secret=client_secret, http_client=http_client)

    return _factory


@pytest.fixture
def make_context():
    """Factory: build a TenantContext from a resolve body (default acme-sales)."""
    from open_webui.utils.tenant import ResolveResponse, TenantContext

    def _factory(slug: str = 'acme-sales', role: str = 'admin', **overrides):
        body = sample_resolve_body(slug=slug, role=role)
        for path, value in overrides.items():
            # dotted override e.g. connection_storage_bucket -> connection.storage.bucket
            keys = path.split('.')
            node = body
            for k in keys[:-1]:
                node = node[k]
            node[keys[-1]] = value
        return TenantContext.from_resolve(ResolveResponse.model_validate(body))

    return _factory


@pytest.fixture(autouse=True)
def _clear_tenant_state():
    """Reset module-level tenant caches/context between tests."""
    from open_webui.utils import tenant

    tenant.clear_bundle_cache()
    yield
    tenant.clear_bundle_cache()

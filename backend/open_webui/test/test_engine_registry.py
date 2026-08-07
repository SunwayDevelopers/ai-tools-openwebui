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


# ─────────────────────────────────────────────────────────────────────
# Idle eviction. SQLAlchemy's QueuePool never shrinks below pool_size, so an
# untouched tenant pins its resident connections until the engine is disposed.
# ─────────────────────────────────────────────────────────────────────


class _FakePool:
    def __init__(self, checked_out: int = 0):
        self._checked_out = checked_out

    def checkedout(self) -> int:
        return self._checked_out


class _FakeSyncEngine:
    def __init__(self, pool):
        self.pool = pool


class _FakeEngine:
    """Minimal stand-in exposing the one path _engine_in_use walks."""

    def __init__(self, checked_out: int = 0):
        self.sync_engine = _FakeSyncEngine(_FakePool(checked_out))


def _registry_reset():
    db._tenant_sessionmakers.clear()
    db._tenant_last_used.clear()


def _install_registry(monkeypatch, *, checked_out: int = 0):
    """Fake builder yielding _FakeEngine, plus a disposal recorder."""
    disposed: list[str] = []

    def build(tenant_ctx):
        return _FakeEngine(checked_out), object()

    monkeypatch.setattr(db, '_build_tenant_sessionmaker', build)
    monkeypatch.setattr(db, '_dispose_engine', lambda engine, tid: disposed.append(tid))
    monkeypatch.setattr(db, 'ENABLE_MULTI_TENANCY', True)
    monkeypatch.setattr(db, 'TENANT_ENGINE_CACHE_SIZE', 50)
    _registry_reset()
    return disposed


def _resolve_for(make_context, slug: str):
    tok = set_tenant_context(make_context(slug=slug))
    try:
        return db._resolve_async_sessionmaker()
    finally:
        reset_tenant_context(tok)


def _age(tenant_id: str, seconds: float) -> None:
    """Backdate a tenant's last-use stamp instead of mocking the clock."""
    db._tenant_last_used[tenant_id] -= seconds


def test_idle_engine_is_disposed(monkeypatch, make_context):
    disposed = _install_registry(monkeypatch)
    monkeypatch.setattr(db, 'TENANT_ENGINE_IDLE_TIMEOUT', 900)

    _resolve_for(make_context, 'bu0')
    _age('tenant-bu0', 1000)  # idle past the window

    _resolve_for(make_context, 'bu1')  # any request triggers the lazy sweep

    assert disposed == ['tenant-bu0']
    assert 'tenant-bu0' not in db._tenant_sessionmakers
    assert 'tenant-bu0' not in db._tenant_last_used  # no timestamp leak


def test_engine_with_checked_out_connection_is_never_disposed(monkeypatch, make_context):
    """A request outliving the idle window must not have its connection closed
    mid-query — the whole reason the sweep consults the pool."""
    disposed = _install_registry(monkeypatch, checked_out=1)
    monkeypatch.setattr(db, 'TENANT_ENGINE_IDLE_TIMEOUT', 900)

    _resolve_for(make_context, 'bu0')
    _age('tenant-bu0', 1000)

    _resolve_for(make_context, 'bu1')

    assert disposed == []
    assert 'tenant-bu0' in db._tenant_sessionmakers


def test_busy_engine_stamp_is_refreshed_so_it_is_not_rechecked(monkeypatch, make_context):
    disposed = _install_registry(monkeypatch, checked_out=1)
    monkeypatch.setattr(db, 'TENANT_ENGINE_IDLE_TIMEOUT', 900)

    _resolve_for(make_context, 'bu0')
    _age('tenant-bu0', 1000)
    before = db._tenant_last_used['tenant-bu0']

    _resolve_for(make_context, 'bu1')

    assert db._tenant_last_used['tenant-bu0'] > before
    assert disposed == []


def test_active_engine_survives_the_sweep(monkeypatch, make_context):
    disposed = _install_registry(monkeypatch)
    monkeypatch.setattr(db, 'TENANT_ENGINE_IDLE_TIMEOUT', 900)

    sm1 = _resolve_for(make_context, 'bu0')
    sm2 = _resolve_for(make_context, 'bu0')  # still fresh

    assert sm1 is sm2
    assert disposed == []


def test_idle_timeout_zero_disables_idle_eviction(monkeypatch, make_context):
    disposed = _install_registry(monkeypatch)
    monkeypatch.setattr(db, 'TENANT_ENGINE_IDLE_TIMEOUT', 0)

    _resolve_for(make_context, 'bu0')
    _age('tenant-bu0', 100_000)

    _resolve_for(make_context, 'bu1')

    assert disposed == []
    assert 'tenant-bu0' in db._tenant_sessionmakers


def test_lru_eviction_does_not_leak_last_used_stamps(monkeypatch, make_context):
    disposed = _install_registry(monkeypatch)
    monkeypatch.setattr(db, 'TENANT_ENGINE_CACHE_SIZE', 2)
    monkeypatch.setattr(db, 'TENANT_ENGINE_IDLE_TIMEOUT', 900)

    for slug in ('bu0', 'bu1', 'bu2'):
        _resolve_for(make_context, slug)

    assert disposed == ['tenant-bu0']
    assert set(db._tenant_last_used) == set(db._tenant_sessionmakers)


def test_engine_in_use_assumes_busy_when_pool_cannot_be_read():
    """'Cannot tell' must not licence a dispose."""
    assert db._engine_in_use(object()) is True
    assert db._engine_in_use(_FakeEngine(checked_out=0)) is False
    assert db._engine_in_use(_FakeEngine(checked_out=1)) is True


def test_engine_in_use_is_false_for_nullpool(monkeypatch):
    """NullPool has no checkedout(). Answering 'busy' there would silently disable
    idle eviction in the DEFAULT configuration, so it must be special-cased."""
    engine = _FakeEngine()
    engine.sync_engine.pool = db.NullPool.__new__(db.NullPool)  # no __init__ needed
    assert db._engine_in_use(engine) is False


# ─────────────────────────────────────────────────────────────────────
# Pool mode. Default (TENANT_DB_POOL_SIZE=0) is NullPool: with many tenants and few
# users each, pooled connections scale with tenant count while NullPool scales with
# actual concurrency.
# ─────────────────────────────────────────────────────────────────────


def _capture_engine_kwargs(monkeypatch):
    captured = {}

    def fake_create_async_engine(url, **kwargs):
        captured.update(kwargs)
        return _FakeEngine()

    monkeypatch.setattr(db, 'create_async_engine', fake_create_async_engine)
    monkeypatch.setattr(db, 'async_sessionmaker', lambda **kw: object())
    return captured


def test_pool_size_zero_selects_nullpool(monkeypatch, make_context):
    captured = _capture_engine_kwargs(monkeypatch)
    monkeypatch.setattr(db, 'TENANT_DB_POOL_SIZE', 0)

    db._build_tenant_sessionmaker(make_context())

    assert captured['poolclass'] is db.NullPool
    # NullPool rejects these, and pre-ping on a brand-new connection is a wasted
    # round trip.
    for rejected in ('pool_size', 'max_overflow', 'pool_timeout', 'pool_pre_ping'):
        assert rejected not in captured


def test_positive_pool_size_selects_queuepool_with_env_values(monkeypatch, make_context):
    captured = _capture_engine_kwargs(monkeypatch)
    monkeypatch.setattr(db, 'TENANT_DB_POOL_SIZE', 2)
    monkeypatch.setattr(db, 'TENANT_DB_MAX_OVERFLOW', 3)

    db._build_tenant_sessionmaker(make_context())

    assert captured['pool_size'] == 2
    assert captured['max_overflow'] == 3
    assert captured['pool_pre_ping'] is True
    assert 'poolclass' not in captured


# ─────────────────────────────────────────────────────────────────────
# Connect timeouts. Without them the OS governs the handshake (~127s of SYN retries
# on Linux), so a tenant pointed at an unreachable host hangs the request instead of
# erroring. pool_timeout does NOT cover this — it bounds waiting for a pool slot.
# ─────────────────────────────────────────────────────────────────────


def test_nullpool_engine_gets_connect_timeout(monkeypatch, make_context):
    captured = _capture_engine_kwargs(monkeypatch)
    monkeypatch.setattr(db, 'TENANT_DB_POOL_SIZE', 0)
    monkeypatch.setattr(db, 'TENANT_DB_CONNECT_TIMEOUT', 10)

    db._build_tenant_sessionmaker(make_context())

    assert captured['connect_args']['connect_timeout'] == 10


def test_pooled_engine_gets_connect_timeout(monkeypatch, make_context):
    captured = _capture_engine_kwargs(monkeypatch)
    monkeypatch.setattr(db, 'TENANT_DB_POOL_SIZE', 1)
    monkeypatch.setattr(db, 'TENANT_DB_CONNECT_TIMEOUT', 7)

    db._build_tenant_sessionmaker(make_context())

    assert captured['connect_args']['connect_timeout'] == 7


def test_keepalives_are_set_so_a_dead_peer_is_detected(monkeypatch, make_context):
    """connect_timeout only bounds establishing a connection; keepalives bound
    detecting one that was healthy and then silently died (blackholed route)."""
    captured = _capture_engine_kwargs(monkeypatch)
    monkeypatch.setattr(db, 'TENANT_DB_POOL_SIZE', 1)
    monkeypatch.setattr(db, 'TENANT_DB_KEEPALIVES_IDLE', 30)
    monkeypatch.setattr(db, 'TENANT_DB_KEEPALIVES_INTERVAL', 10)
    monkeypatch.setattr(db, 'TENANT_DB_KEEPALIVES_COUNT', 3)

    db._build_tenant_sessionmaker(make_context())

    ca = captured['connect_args']
    assert ca['keepalives'] == 1
    assert (ca['keepalives_idle'], ca['keepalives_interval'], ca['keepalives_count']) == (30, 10, 3)

from __future__ import annotations

import json
import logging
import os
import sys
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from open_webui.env import (
    DATABASE_ENABLE_SESSION_SHARING,
    DATABASE_ENABLE_SQLITE_WAL,
    DATABASE_POOL_MAX_OVERFLOW,
    DATABASE_POOL_RECYCLE,
    DATABASE_POOL_SIZE,
    DATABASE_POOL_TIMEOUT,
    DATABASE_SCHEMA,
    DATABASE_SQLITE_PRAGMA_BUSY_TIMEOUT,
    DATABASE_SQLITE_PRAGMA_CACHE_SIZE,
    DATABASE_SQLITE_PRAGMA_JOURNAL_SIZE_LIMIT,
    DATABASE_SQLITE_PRAGMA_MMAP_SIZE,
    DATABASE_SQLITE_PRAGMA_SYNCHRONOUS,
    DATABASE_SQLITE_PRAGMA_TEMP_STORE,
    DATABASE_URL,
    ENABLE_DB_MIGRATIONS,
    ENABLE_MULTI_TENANCY,
    OPEN_WEBUI_DIR,
    TENANT_DB_MAX_OVERFLOW,
    TENANT_DB_POOL_SIZE,
    TENANT_ENGINE_CACHE_SIZE,
    TENANT_ENGINE_IDLE_TIMEOUT,
)
from sqlalchemy import Dialect, MetaData, create_engine, event, types
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, scoped_session, sessionmaker
from sqlalchemy.pool import NullPool, QueuePool
from sqlalchemy.sql.type_api import _T
from typing_extensions import Self

log = logging.getLogger(__name__)


# ── SSL URL normalization (used by sync engine & Alembic migrations) ─
#
# psycopg2 (sync) needs ``sslmode=`` in the connection string (it does
# not recognise the bare ``ssl=`` key that some ORMs emit).  The helpers
# below strip all SSL-related query params, normalise them, and
# reattach them in the canonical libpq form.
#
# The **async** engine now uses psycopg (v3), which speaks libpq
# natively, so it needs no translation at all — the DATABASE_URL is
# passed through as-is.
# ─────────────────────────────────────────────────────────────────────


def _pop_first(params: dict[str, list[str]], key: str) -> str | None:
    """Pop a single-valued query param, returning ``None`` if absent."""
    values = params.pop(key, None)
    return values[0] if values else None


def _is_postgres_url(url: str) -> bool:
    """Return True if *url* looks like a PostgreSQL connection string."""
    return bool(url) and any(url.startswith(p) for p in ('postgresql://', 'postgresql+', 'postgres://'))


def extract_ssl_params_from_url(url: str) -> tuple[str, dict[str, str]]:
    """Strip SSL query-string parameters from a PostgreSQL URL.

    Returns ``(url_without_ssl, ssl_dict)`` where *ssl_dict* maps
    canonical libpq key names (``sslmode``, ``sslrootcert``, …) to
    their values.  Non-PostgreSQL URLs are returned unchanged with an
    empty dict.
    """
    if not _is_postgres_url(url):
        return url, {}

    parsed = urlparse(url)
    qp = parse_qs(parsed.query, keep_blank_values=True)

    # Prefer sslmode (libpq canonical) over the bare ``ssl`` key.
    sslmode_val = _pop_first(qp, 'sslmode')
    ssl_val = _pop_first(qp, 'ssl')
    ssl_mode = sslmode_val or ssl_val

    ssl_dict: dict[str, str] = {}
    if ssl_mode:
        ssl_dict['sslmode'] = ssl_mode
    for key in ('sslrootcert', 'sslcert', 'sslkey', 'sslcrl'):
        val = _pop_first(qp, key)
        if val:
            ssl_dict[key] = val

    if not ssl_dict:
        return url, ssl_dict

    cleaned_query = urlencode(qp, doseq=True)
    return urlunparse(parsed._replace(query=cleaned_query)), ssl_dict


def reattach_ssl_params_to_url(url_without_ssl: str, ssl_dict: dict[str, str]) -> str:
    """Re-append SSL query-string parameters to a cleaned PostgreSQL URL.

    Used for psycopg2/libpq consumers that expect ``sslmode`` and the
    certificate-file keys in the connection string.
    """
    if not ssl_dict:
        return url_without_ssl

    parts = [f'{k}={v}' for k, v in ssl_dict.items() if v]
    if not parts:
        return url_without_ssl

    sep = '&' if '?' in url_without_ssl else '?'
    return f'{url_without_ssl}{sep}{"&".join(parts)}'


# Backwards-compatible aliases for external callers.
extract_ssl_mode_from_url = extract_ssl_params_from_url
reattach_ssl_mode_to_url = reattach_ssl_params_to_url


class JSONField(types.TypeDecorator):  # TEXT-backed JSON storage
    """Store arbitrary Python objects as JSON-encoded TEXT.

    Used instead of native JSON columns for portability across SQLite and
    PostgreSQL.  Values are serialized with ``json.dumps`` on write and
    deserialized with ``json.loads`` on read.
    """

    impl = types.UnicodeText
    cache_ok = True

    def process_bind_param(self, value: _T | None, dialect: Dialect) -> Any:
        return json.dumps(value) if value is not None else None

    def process_result_value(self, value: _T | None, dialect: Dialect) -> Any:
        return json.loads(value) if value is not None else None

    def copy(self, **kwargs: Any) -> Self:
        return JSONField(length=self.impl.length)


# Normalize SSL params from the URL once; the sync engine needs them
# reattached in canonical libpq form for psycopg2.
_url_without_ssl, _ssl_dict = extract_ssl_params_from_url(DATABASE_URL)

# For psycopg2 (sync engine), re-append sslmode + cert-file params.
SQLALCHEMY_DATABASE_URL = reattach_ssl_params_to_url(_url_without_ssl, _ssl_dict) if _ssl_dict else DATABASE_URL


def _make_async_url(url: str) -> str:
    """Convert a sync database URL to its async driver equivalent.

    The async engine uses psycopg (v3) which speaks libpq natively,
    so all standard connection-string parameters (``sslmode``,
    ``options``, ``target_session_attrs``, etc.) are passed through
    without any translation.
    """
    if url.startswith('sqlite+sqlcipher://'):
        raise ValueError(
            'sqlite+sqlcipher:// URLs are not supported with async engine. '
            'Use standard sqlite:// or postgresql:// instead.'
        )
    if url.startswith('sqlite:///') or url.startswith('sqlite://'):
        return url.replace('sqlite://', 'sqlite+aiosqlite://', 1)
    # psycopg v3 — auto-selects async mode with create_async_engine
    if url.startswith('postgresql+psycopg2://'):
        return url.replace('postgresql+psycopg2://', 'postgresql+psycopg://', 1)
    if url.startswith('postgresql://'):
        return url.replace('postgresql://', 'postgresql+psycopg://', 1)
    if url.startswith('postgres://'):
        return url.replace('postgres://', 'postgresql+psycopg://', 1)
    # For other dialects, return as-is and let SQLAlchemy handle it
    return url


# ============================================================
# SYNC ENGINE (used only for: startup migrations, config loading,
#              Alembic, peewee migration, health checks)
# ============================================================

# Handle SQLCipher URLs
if SQLALCHEMY_DATABASE_URL.startswith('sqlite+sqlcipher://'):
    database_password = os.environ.get('DATABASE_PASSWORD')
    if not database_password or database_password.strip() == '':
        raise ValueError('DATABASE_PASSWORD is required when using sqlite+sqlcipher:// URLs')

    # Extract database path from SQLCipher URL
    db_path = SQLALCHEMY_DATABASE_URL.replace('sqlite+sqlcipher://', '')

    # Create a custom creator function that uses sqlcipher3
    def create_sqlcipher_connection():
        import sqlcipher3

        conn = sqlcipher3.connect(db_path, check_same_thread=False)
        conn.execute(f"PRAGMA key = '{database_password}'")
        return conn

    # The dummy "sqlite://" URL would cause SQLAlchemy to auto-select
    # SingletonThreadPool, which non-deterministically closes in-use
    # connections when thread count exceeds pool_size, leading to segfaults
    # in the native sqlcipher3 C library. Use NullPool by default for safety,
    # or QueuePool if DATABASE_POOL_SIZE is explicitly configured.
    if isinstance(DATABASE_POOL_SIZE, int) and DATABASE_POOL_SIZE > 0:
        engine = create_engine(
            'sqlite://',
            creator=create_sqlcipher_connection,
            pool_size=DATABASE_POOL_SIZE,
            max_overflow=DATABASE_POOL_MAX_OVERFLOW,
            pool_timeout=DATABASE_POOL_TIMEOUT,
            pool_recycle=DATABASE_POOL_RECYCLE,
            pool_pre_ping=True,
            poolclass=QueuePool,
            echo=False,
        )
    else:
        engine = create_engine(
            'sqlite://',
            creator=create_sqlcipher_connection,
            poolclass=NullPool,
            echo=False,
        )

    log.info('Connected to encrypted SQLite database using SQLCipher')

elif 'sqlite' in SQLALCHEMY_DATABASE_URL:
    engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={'check_same_thread': False})

    def _apply_sqlite_pragmas(dbapi_connection):
        """Apply all configured SQLite PRAGMAs to a raw DBAPI connection."""
        cursor = dbapi_connection.cursor()
        if DATABASE_ENABLE_SQLITE_WAL:
            cursor.execute('PRAGMA journal_mode=WAL')
        else:
            cursor.execute('PRAGMA journal_mode=DELETE')

        # Each PRAGMA is skipped when its env var is empty, allowing opt-out.
        if DATABASE_SQLITE_PRAGMA_SYNCHRONOUS:
            cursor.execute(f'PRAGMA synchronous={DATABASE_SQLITE_PRAGMA_SYNCHRONOUS}')
        if DATABASE_SQLITE_PRAGMA_BUSY_TIMEOUT:
            cursor.execute(f'PRAGMA busy_timeout={DATABASE_SQLITE_PRAGMA_BUSY_TIMEOUT}')
        if DATABASE_SQLITE_PRAGMA_CACHE_SIZE:
            cursor.execute(f'PRAGMA cache_size={DATABASE_SQLITE_PRAGMA_CACHE_SIZE}')
        if DATABASE_SQLITE_PRAGMA_TEMP_STORE:
            cursor.execute(f'PRAGMA temp_store={DATABASE_SQLITE_PRAGMA_TEMP_STORE}')
        if DATABASE_SQLITE_PRAGMA_MMAP_SIZE:
            cursor.execute(f'PRAGMA mmap_size={DATABASE_SQLITE_PRAGMA_MMAP_SIZE}')
        if DATABASE_SQLITE_PRAGMA_JOURNAL_SIZE_LIMIT:
            cursor.execute(f'PRAGMA journal_size_limit={DATABASE_SQLITE_PRAGMA_JOURNAL_SIZE_LIMIT}')
        cursor.close()

    def on_connect(dbapi_connection, connection_record):
        _apply_sqlite_pragmas(dbapi_connection)

    event.listen(engine, 'connect', on_connect)
else:
    if isinstance(DATABASE_POOL_SIZE, int):
        if DATABASE_POOL_SIZE > 0:
            engine = create_engine(
                SQLALCHEMY_DATABASE_URL,
                pool_size=DATABASE_POOL_SIZE,
                max_overflow=DATABASE_POOL_MAX_OVERFLOW,
                pool_timeout=DATABASE_POOL_TIMEOUT,
                pool_recycle=DATABASE_POOL_RECYCLE,
                pool_pre_ping=True,
                poolclass=QueuePool,
            )
        else:
            engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True, poolclass=NullPool)
    else:
        engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True)


# Sync session — used ONLY for startup config loading (config.py runs at import time)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
metadata_obj = MetaData(schema=DATABASE_SCHEMA)
Base = declarative_base(metadata=metadata_obj)
ScopedSession = scoped_session(SessionLocal)


def get_session():
    """Sync session generator — used ONLY for startup/config operations."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


get_db = contextmanager(get_session)


# ============================================================
# ASYNC ENGINE (used for ALL runtime database operations)
# ============================================================

# psycopg (v3) speaks libpq natively — the full DATABASE_URL is passed
# through as-is.  SSL params, ``options``, ``target_session_attrs``, etc.
# all work without any stripping or translation.
ASYNC_SQLALCHEMY_DATABASE_URL = _make_async_url(SQLALCHEMY_DATABASE_URL)

# psycopg v3 cannot run in async mode under Windows' default
# ProactorEventLoop — switch to SelectorEventLoop before creating
# the async engine.  This runs at import time, which is early enough
# to cover every entry point (workers, reload, direct invocations).
if sys.platform == 'win32' and _is_postgres_url(DATABASE_URL):
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

if 'sqlite' in ASYNC_SQLALCHEMY_DATABASE_URL:
    # Generous default — async coroutines + no session sharing = high connection demand.
    _sqlite_pool_size = DATABASE_POOL_SIZE if isinstance(DATABASE_POOL_SIZE, int) and DATABASE_POOL_SIZE > 0 else 512
    async_engine = create_async_engine(
        ASYNC_SQLALCHEMY_DATABASE_URL,
        connect_args={'check_same_thread': False},
        pool_size=_sqlite_pool_size,
        pool_timeout=DATABASE_POOL_TIMEOUT,
        pool_recycle=DATABASE_POOL_RECYCLE,
        pool_pre_ping=True,
    )

    @event.listens_for(async_engine.sync_engine, 'connect')
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        _apply_sqlite_pragmas(dbapi_connection)
else:
    if isinstance(DATABASE_POOL_SIZE, int):
        if DATABASE_POOL_SIZE > 0:
            async_engine = create_async_engine(
                ASYNC_SQLALCHEMY_DATABASE_URL,
                pool_size=DATABASE_POOL_SIZE,
                max_overflow=DATABASE_POOL_MAX_OVERFLOW,
                pool_timeout=DATABASE_POOL_TIMEOUT,
                pool_recycle=DATABASE_POOL_RECYCLE,
                pool_pre_ping=True,
            )
        else:
            async_engine = create_async_engine(
                ASYNC_SQLALCHEMY_DATABASE_URL,
                pool_pre_ping=True,
                poolclass=NullPool,
            )
    else:
        async_engine = create_async_engine(
            ASYNC_SQLALCHEMY_DATABASE_URL,
            pool_pre_ping=True,
        )


AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


# ============================================================
# PER-TENANT ASYNC ENGINE REGISTRY  (multi-tenancy)
# ============================================================
#
# When ENABLE_MULTI_TENANCY is off (the default), the three async entrypoints
# below use the singleton ``AsyncSessionLocal`` above and behave EXACTLY as the
# single-tenant fork does — zero behaviour change, no registry, no gate.
#
# When it is on, each request's tenant is resolved by TenantResolutionMiddleware
# into a ContextVar (see utils/tenant.py). Here we lazily build one async engine
# per tenant from the brokered ``DatabaseConnection`` and bind the request's
# session to it. This is THE isolation chokepoint: because every one of the ~40
# model files funnels through get_async_db_context()/get_async_db() and every
# router through get_async_session(), making session creation tenant-aware here
# makes the whole data plane tenant-aware without touching model or router code.
#
# Fail closed: a tenant-scoped request with no resolved tenant raises before any
# session is created. Startup/config/background code that legitimately needs the
# system DB must run inside ``open_webui.utils.tenant.system_context()``.

import threading
import time
from collections import OrderedDict

# tenant_id -> (AsyncEngine, async_sessionmaker); LRU-ordered.
_tenant_sessionmakers: 'OrderedDict[str, tuple]' = OrderedDict()
# tenant_id -> time.monotonic() of last use. Kept alongside rather than in the
# tuple above so a cache hit updates one dict write instead of rebuilding the
# entry. MUST be popped wherever _tenant_sessionmakers is, or it leaks keys.
# monotonic, not wall clock: an NTP step must not make every engine look idle.
_tenant_last_used: dict[str, float] = {}
_tenant_registry_lock = threading.Lock()


def _build_tenant_async_url(database) -> str:
    """Build an async DSN from a brokered ``DatabaseConnection`` (tenant DBs are
    Postgres per the IAM contract). Credentials are URL-encoded; never logged."""
    from urllib.parse import quote

    user = quote(str(database.username), safe='')
    pwd = quote(str(database.password), safe='')
    return f'postgresql+psycopg://{user}:{pwd}@{database.host}:{database.port}/{database.db_name}'


def _build_tenant_sessionmaker(tenant_ctx):
    url = _build_tenant_async_url(tenant_ctx.connection.database)
    if TENANT_DB_POOL_SIZE <= 0:
        # NullPool: connect per checkout, close on return. Default — see the
        # TENANT_DB_POOL_SIZE comment in env.py for why this suits many tenants with
        # few users each. No pool_size/max_overflow/pool_timeout (NullPool rejects
        # them) and no pool_pre_ping: every connection is new, so validating it
        # would just add a round trip.
        engine = create_async_engine(url, poolclass=NullPool)
    else:
        engine = create_async_engine(
            url,
            pool_size=TENANT_DB_POOL_SIZE,
            max_overflow=TENANT_DB_MAX_OVERFLOW,
            pool_timeout=DATABASE_POOL_TIMEOUT,
            pool_recycle=DATABASE_POOL_RECYCLE,
            pool_pre_ping=True,
        )
    sessionmaker_ = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    return engine, sessionmaker_


def _dispose_engine(engine, tenant_id: str) -> None:
    """Dispose an evicted tenant engine's pool. Prefer async dispose when a loop
    is running; fall back to the sync engine's dispose otherwise."""
    try:
        import asyncio

        asyncio.get_running_loop().create_task(engine.dispose())
    except RuntimeError:
        try:
            engine.sync_engine.dispose()
        except Exception:
            log.warning('Failed to dispose evicted tenant engine for %s', tenant_id)


def _engine_in_use(engine) -> bool:
    """True if disposing this engine could close a connection under a live query.

    Fails towards "in use" for pool types we cannot interrogate — "cannot tell" must
    never licence a dispose.
    """
    try:
        pool = engine.sync_engine.pool
    except Exception:  # noqa: BLE001 - not an engine we understand, assume busy
        return True
    if isinstance(pool, NullPool):
        # Nothing is pooled. A live connection is owned by its session rather than
        # the pool, and dispose() on a NullPool closes nothing — so dropping the
        # engine can never interrupt a query. Answering "busy" here (which the
        # missing checkedout() would otherwise cause) would disable idle eviction
        # entirely in the default configuration.
        return False
    try:
        return pool.checkedout() > 0
    except Exception:  # noqa: BLE001 - unknown pool type, assume busy
        return True


def _sweep_idle_tenant_engines(now: float) -> None:
    """Dispose tenant engines with no request for TENANT_ENGINE_IDLE_TIMEOUT.

    **Call with ``_tenant_registry_lock`` held.**

    Why this is needed at all: SQLAlchemy's QueuePool never shrinks below
    ``pool_size``. Only *overflow* connections close on return, and ``pool_recycle``
    acts at checkout, not on idle time. So a tenant someone opened once this morning
    still pins TENANT_DB_POOL_SIZE live Postgres connections, and because every
    tenant gets its own pool that idle cost multiplies by tenant count — which is
    what actually pushes a pod towards ``max_connections``.

    Swept lazily from _get_tenant_sessionmaker rather than by a background task: if
    nothing calls that, no tenant is active, and idle pools are not competing for
    connections anyway.

    Only engines with an empty pool are disposed, so unlike the size-based eviction
    below this can never close a connection mid-query (least-recently-used is not
    the same as unused — with more hot tenants than the cache size, the LRU victim
    may well be serving a request).
    """
    if TENANT_ENGINE_IDLE_TIMEOUT <= 0:  # disabled; size-based LRU still applies
        return
    stale = [t for t, seen in _tenant_last_used.items() if now - seen > TENANT_ENGINE_IDLE_TIMEOUT]
    for tenant_id in stale:
        entry = _tenant_sessionmakers.get(tenant_id)
        if entry is None:  # already evicted by size; drop the orphaned timestamp
            _tenant_last_used.pop(tenant_id, None)
            continue
        engine = entry[0]
        if _engine_in_use(engine):
            # A long-running request outlived the idle window. Refresh the stamp so
            # it is not re-examined on every call until that request finishes.
            _tenant_last_used[tenant_id] = now
            continue
        _tenant_sessionmakers.pop(tenant_id, None)
        _tenant_last_used.pop(tenant_id, None)
        _dispose_engine(engine, tenant_id)
        log.info(
            'Disposed idle tenant DB engine tenant=%s (no requests for >%ss), '
            'releasing up to %s pooled connections',
            tenant_id,
            TENANT_ENGINE_IDLE_TIMEOUT,
            TENANT_DB_POOL_SIZE,
        )


def _get_tenant_sessionmaker(tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    now = time.monotonic()
    with _tenant_registry_lock:
        _sweep_idle_tenant_engines(now)

        entry = _tenant_sessionmakers.get(tenant_id)
        if entry is not None:
            _tenant_sessionmakers.move_to_end(tenant_id)
            _tenant_last_used[tenant_id] = now
            return entry[1]
        engine, sessionmaker_ = _build_tenant_sessionmaker(tenant_ctx)
        _tenant_sessionmakers[tenant_id] = (engine, sessionmaker_)
        _tenant_sessionmakers.move_to_end(tenant_id)
        _tenant_last_used[tenant_id] = now
        while len(_tenant_sessionmakers) > TENANT_ENGINE_CACHE_SIZE:
            old_id, (old_engine, _) = _tenant_sessionmakers.popitem(last=False)
            _tenant_last_used.pop(old_id, None)
            _dispose_engine(old_engine, old_id)
        return sessionmaker_


def _resolve_async_sessionmaker():
    """Return the async_sessionmaker for the current request's tenant.

    * multi-tenancy disabled → the singleton system sessionmaker (no change);
    * system context (startup/migrations/background) → system sessionmaker;
    * tenant context set → the per-tenant sessionmaker;
    * tenant-scoped but no context → **fail closed**.
    """
    if not ENABLE_MULTI_TENANCY:
        return AsyncSessionLocal
    from open_webui.utils.tenant import (
        TenantContextError,
        get_tenant_context,
        is_system_context,
    )

    if is_system_context():
        return AsyncSessionLocal
    ctx = get_tenant_context()
    if ctx is None:
        raise TenantContextError('No tenant context for a tenant-scoped DB session (fail-closed).')
    return _get_tenant_sessionmaker(ctx)


async def get_async_session():
    """Async session generator for FastAPI Depends()."""
    async with _resolve_async_sessionmaker()() as db:
        try:
            yield db
        finally:
            await db.close()


@asynccontextmanager
async def get_async_db():
    """Async context manager for use outside of FastAPI dependency injection."""
    async with _resolve_async_sessionmaker()() as db:
        try:
            yield db
        finally:
            await db.close()


@asynccontextmanager
async def get_async_db_context(db: AsyncSession | None = None):
    """Async context manager that reuses an existing session if provided and session sharing is enabled."""
    if isinstance(db, AsyncSession) and DATABASE_ENABLE_SESSION_SHARING:
        yield db
    else:
        async with get_async_db() as session:
            yield session

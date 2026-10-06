"""Minimal persistent Places cache: place ID → coordinates only (D38).

What is stored:
    place_coordinates(place_id TEXT PRIMARY KEY, lat REAL, lng REAL, fetched_at INTEGER)
Nothing else — no names, types, opening hours, addresses or user search text.
Rich details are fetched per operation and stay request-scoped (D37).

Expiry:
    Google permits caching place IDs and temporarily caching lat/lng for up to
    30 consecutive calendar days. A row's ``fetched_at`` is the provider fetch
    time and is never extended by reads. Rows are treated as expired, and are
    deleted by the cleanup task, ``cleanup_seconds`` BEFORE the TTL so that
    physical deletion (which runs every ``cleanup_seconds`` and at startup)
    always happens no later than ``ttl_days`` after fetching while the
    process is running.

Migration from the legacy rich cache (``geocache`` table, keyed by a hash of
query text + city, storing names/types/hours):
    On first use the permitted columns (place_id, lat, lng, cached_at as
    fetched_at) of unexpired legacy rows are copied into place_coordinates,
    the legacy table is dropped, and the database is VACUUMed with
    secure_delete on, so legacy values are not left in free pages of the live
    file. Limitations: this cannot erase copies in backups, snapshots or any
    filesystem-level history made before the migration; those must be handled
    (or allowed to expire) operationally. Physical deletion also depends on
    the process running; on startup the purge runs immediately.

All SQL is parameterised. The DB file is created 0600 in a 0700 directory.

Deployment (decision D-2, 2026-10-06): the file lives in the container's
ephemeral filesystem; every redeploy clears it. The cache is an optimisation
for place selection only — planning re-verifies places with Place Details —
and any missing, unreadable or failing cache is treated as a miss.
"""

import contextlib
import logging
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

from app.core.config import settings

log = logging.getLogger(__name__)

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS place_coordinates (
    place_id    TEXT PRIMARY KEY,
    lat         REAL NOT NULL,
    lng         REAL NOT NULL,
    fetched_at  INTEGER NOT NULL
)
"""
_PLACE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,300}$")


@dataclass(frozen=True)
class CachedCoordinates:
    place_id: str
    lat: float
    lng: float
    fetched_at: int


def expiry_seconds(ttl_days: int, cleanup_seconds: int | None = None) -> int:
    """Age at which a row is expired (and purged) — TTL minus one cleanup interval."""
    interval = settings.cache_cleanup_seconds if cleanup_seconds is None else cleanup_seconds
    return max(0, ttl_days * 86400 - interval)


def _prepare_path(db_path: str) -> None:
    Path(db_path).parent.mkdir(mode=0o700, parents=True, exist_ok=True)


def _secure_file(db_path: str) -> None:
    with contextlib.suppress(FileNotFoundError):
        Path(db_path).chmod(0o600)


async def _migrate(db: aiosqlite.Connection, ttl_days: int) -> bool:
    """Create the minimal table; migrate and destroy the legacy rich table.

    Returns True when a legacy table was migrated (caller then VACUUMs).
    """
    await db.execute(_CREATE_SQL)
    async with db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'geocache'"
    ) as cursor:
        legacy = await cursor.fetchone()
    if legacy is None:
        return False
    cutoff = int(time.time()) - expiry_seconds(ttl_days)
    # Only permitted fields, only unexpired rows; keep the newest fetch per place.
    await db.execute(
        """
        INSERT INTO place_coordinates (place_id, lat, lng, fetched_at)
        SELECT place_id, lat, lng, MAX(cached_at) FROM geocache
        WHERE cached_at > ? GROUP BY place_id
        ON CONFLICT(place_id) DO UPDATE SET
            lat = excluded.lat, lng = excluded.lng, fetched_at = excluded.fetched_at
        WHERE excluded.fetched_at > place_coordinates.fetched_at
        """,
        (cutoff,),
    )
    await db.execute("DROP TABLE geocache")
    return True


async def _open(db_path: str, ttl_days: int) -> aiosqlite.Connection:
    _prepare_path(db_path)
    db = await aiosqlite.connect(db_path)
    _secure_file(db_path)
    await db.execute("PRAGMA secure_delete = ON")
    migrated = await _migrate(db, ttl_days)
    await db.commit()
    if migrated:
        await db.execute("VACUUM")
        log.info("geocache_legacy_migrated")
    return db


async def migrate_legacy(db_path: str, ttl_days: int) -> None:
    """Run the schema migration now (startup). No-op when no DB file exists."""
    if not Path(db_path).exists():
        return
    db = await _open(db_path, ttl_days)
    await db.close()


async def put_coordinates(
    place_id: str,
    lat: float,
    lng: float,
    db_path: str,
    ttl_days: int,
    fetched_at: float | None = None,
) -> None:
    """Persist a provider-confirmed place ID and its coordinates.

    ``fetched_at`` is when the provider returned them (defaults to now). A
    write never replaces a newer fetch with an older one.
    """
    if not _PLACE_ID_RE.fullmatch(place_id) or not (
        math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180
    ):
        return
    ts = int(fetched_at if fetched_at is not None else time.time())
    db = await _open(db_path, ttl_days)
    try:
        await db.execute(
            """
            INSERT INTO place_coordinates (place_id, lat, lng, fetched_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(place_id) DO UPDATE SET
                lat = excluded.lat, lng = excluded.lng, fetched_at = excluded.fetched_at
            WHERE excluded.fetched_at >= place_coordinates.fetched_at
            """,
            (place_id, lat, lng, ts),
        )
        await db.commit()
    finally:
        await db.close()


async def get_coordinates(
    place_id: str, db_path: str, ttl_days: int, now: float | None = None
) -> CachedCoordinates | None:
    """Return unexpired coordinates for a place ID, or None. Reads never extend expiry."""
    if not Path(db_path).exists() or not _PLACE_ID_RE.fullmatch(place_id):
        return None
    try:
        db = await _open(db_path, ttl_days)
    except Exception:
        return None
    try:
        async with db.execute(
            "SELECT place_id, lat, lng, fetched_at FROM place_coordinates WHERE place_id = ?",
            (place_id,),
        ) as cursor:
            row = await cursor.fetchone()
    except Exception as exc:  # the cache is optional: a failed read is a miss
        log.warning("geocache_read_failed exception_type=%s", type(exc).__name__)
        return None
    finally:
        await db.close()
    if row is None:
        return None
    current = time.time() if now is None else now
    if current - row[3] >= expiry_seconds(ttl_days):
        return None
    return CachedCoordinates(row[0], float(row[1]), float(row[2]), int(row[3]))


async def purge_expired(db_path: str, ttl_days: int) -> int:
    """Migrate if needed, then delete expired rows. Returns the number deleted."""
    if not Path(db_path).exists():
        return 0
    _secure_file(db_path)
    cutoff = int(time.time()) - expiry_seconds(ttl_days)
    try:
        db = await _open(db_path, ttl_days)
        try:
            cursor = await db.execute(
                "DELETE FROM place_coordinates WHERE fetched_at <= ?", (cutoff,)
            )
            await db.commit()
            return cursor.rowcount or 0
        finally:
            await db.close()
    except Exception as exc:
        log.warning("geocache_purge_failed exception_type=%s", type(exc).__name__)
        return 0

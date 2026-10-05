"""SQLite cache for geocoded places.

Sits in front of the Places API to avoid burning quota on repeated lookups
for the same stop in the same city. 30-day TTL (configurable via settings).

Design choices:
    - aiosqlite for non-blocking I/O (consistent with async FastAPI codebase)
    - Single table, query_key as PRIMARY KEY → upsert is one statement
    - types stored as JSON string; avoids schema complexity for a string list
    - DB file + table created on first write; no migration tooling needed at v1 scale
    - Cache key normalised (lowercase + strip) so "Trinity College" and
      "trinity college " hit the same row

Schema migration (opening_hours_json column added):
    New databases get the column via CREATE TABLE.  Existing databases are
    migrated lazily: put_cached attempts ALTER TABLE ADD COLUMN on every write;
    the OperationalError that SQLite raises when the column already exists is
    silently ignored (idempotent).  get_cached handles old rows that lack the
    column by catching IndexError and defaulting to opening_hours=None, so
    cache hits for pre-migration entries still work correctly.
"""

import contextlib
import hashlib
import json
import logging
import time
from pathlib import Path

import aiosqlite
import httpx

from app.services.geocoder import (
    GeocodedPlace,
    OpeningPeriod,
    geocode,
    opening_hours_from_json_list,
    opening_hours_to_json_list,
)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS geocache (
    query_key           TEXT PRIMARY KEY,
    place_id            TEXT NOT NULL,
    name                TEXT NOT NULL,
    lat                 REAL NOT NULL,
    lng                 REAL NOT NULL,
    primary_type        TEXT,
    types_json          TEXT NOT NULL,
    cached_at           INTEGER NOT NULL,
    opening_hours_json  TEXT
)
"""

# Idempotent migration for existing databases that pre-date opening_hours.
# SQLite raises OperationalError: "duplicate column name" if column exists —
# we catch and ignore it in put_cached.
_ADD_HOURS_COLUMN_SQL = "ALTER TABLE geocache ADD COLUMN opening_hours_json TEXT"


def _make_key(query: str, city: str) -> str:
    return hashlib.sha256(f"{query.strip().lower()}|{city.strip().lower()}".encode()).hexdigest()


async def get_cached(
    query_key: str,
    db_path: str,
    ttl_days: int,
) -> GeocodedPlace | None:
    """Return a cached GeocodedPlace, or None if missing or expired."""
    try:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM geocache WHERE query_key = ?", (query_key,)
            ) as cursor:
                row = await cursor.fetchone()
    except Exception:
        # DB doesn't exist yet or table missing — treat as cache miss.
        return None

    if row is None:
        return None

    age_seconds = time.time() - row["cached_at"]
    if age_seconds > ttl_days * 86400:
        return None

    # opening_hours_json may be absent on rows written before the migration.
    try:
        hours_json: str | None = row["opening_hours_json"]
    except (IndexError, KeyError):
        hours_json = None

    opening_hours: list[OpeningPeriod] | None = None
    if hours_json is not None:
        try:
            opening_hours = opening_hours_from_json_list(json.loads(hours_json))
        except Exception:
            opening_hours = None

    return GeocodedPlace(
        place_id=row["place_id"],
        name=row["name"],
        lat=row["lat"],
        lng=row["lng"],
        primary_type=row["primary_type"],
        types=json.loads(row["types_json"]),
        opening_hours=opening_hours,
    )


async def put_cached(
    query_key: str,
    place: GeocodedPlace,
    db_path: str,
) -> None:
    """Write a GeocodedPlace to the cache, creating the DB/table if needed."""
    Path(db_path).parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    hours_json: str | None = None
    if place.opening_hours is not None:
        hours_json = json.dumps(opening_hours_to_json_list(place.opening_hours))

    async with aiosqlite.connect(db_path) as db:
        Path(db_path).chmod(0o600)
        await db.execute(_CREATE_TABLE_SQL)
        # Migrate existing databases that pre-date opening_hours_json.
        with contextlib.suppress(Exception):
            await db.execute(_ADD_HOURS_COLUMN_SQL)

        await db.execute(
            """
            INSERT OR REPLACE INTO geocache
                (query_key, place_id, name, lat, lng, primary_type,
                 types_json, cached_at, opening_hours_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                query_key,
                place.place_id,
                place.name,
                place.lat,
                place.lng,
                place.primary_type,
                json.dumps(place.types),
                int(time.time()),
                hours_json,
            ),
        )
        await db.commit()


async def purge_expired(db_path: str, ttl_days: int) -> int:
    """Delete cache rows older than ttl_days. Returns the number deleted.

    Runs opportunistically; safe to call from a background task or startup.
    Silently returns 0 if the database does not exist yet.
    """
    if not Path(db_path).exists():
        return 0
    Path(db_path).chmod(0o600)
    cutoff = int(time.time()) - ttl_days * 86400
    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "DELETE FROM geocache WHERE cached_at < ? OR length(query_key) != 64", (cutoff,)
            )
            await db.commit()
            deleted: int = cursor.rowcount or 0
            return deleted
    except Exception:
        return 0


async def geocode_cached(
    query: str,
    city: str,
    db_path: str,
    ttl_days: int,
    client: httpx.AsyncClient | None = None,
) -> GeocodedPlace:
    """Geocode a stop, returning the cached result when available.

    On a cache miss, calls the Places API then writes the result to cache.
    """
    key = _make_key(query, city)
    cached = await get_cached(key, db_path, ttl_days)
    if cached is not None:
        return cached

    place = await geocode(query, city, client=client)
    try:
        await put_cached(key, place, db_path)
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "cache_write_failed exception_type=%s", type(exc).__name__
        )
    return place

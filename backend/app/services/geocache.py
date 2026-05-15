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
"""

import json
import time

import aiosqlite

from app.services.geocoder import GeocodedPlace, geocode

import httpx

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS geocache (
    query_key   TEXT PRIMARY KEY,
    place_id    TEXT NOT NULL,
    name        TEXT NOT NULL,
    lat         REAL NOT NULL,
    lng         REAL NOT NULL,
    primary_type TEXT,
    types_json  TEXT NOT NULL,
    cached_at   INTEGER NOT NULL
)
"""


def _make_key(query: str, city: str) -> str:
    return f"{query.strip().lower()}|{city.strip().lower()}"


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

    return GeocodedPlace(
        place_id=row["place_id"],
        name=row["name"],
        lat=row["lat"],
        lng=row["lng"],
        primary_type=row["primary_type"],
        types=json.loads(row["types_json"]),
    )


async def put_cached(
    query_key: str,
    place: GeocodedPlace,
    db_path: str,
) -> None:
    """Write a GeocodedPlace to the cache, creating the DB/table if needed."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(_CREATE_TABLE_SQL)
        await db.execute(
            """
            INSERT OR REPLACE INTO geocache
                (query_key, place_id, name, lat, lng, primary_type, types_json, cached_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        await db.commit()


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
    await put_cached(key, place, db_path)
    return place

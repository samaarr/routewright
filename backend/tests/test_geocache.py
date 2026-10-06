"""Tests for the minimal place-ID → coordinates cache (D38).

All tests use tmp_path for the DB. Provider calls are mocked with
httpx.MockTransport.
"""

import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.services import geocache
from app.services.geocache import (
    expiry_seconds,
    geocode_cached,
    get_coordinates,
    migrate_legacy,
    purge_expired,
    put_coordinates,
)

TTL = 30
_TEXT_SEARCH = {
    "places": [
        {
            "id": "ChIJABC123",
            "displayName": {"text": "Guinness Storehouse", "languageCode": "en"},
            "location": {"latitude": 53.3418, "longitude": -6.2867},
            "primaryType": "brewery",
            "types": ["brewery", "tourist_attraction"],
            "regularOpeningHours": {
                "periods": [{"open": {"day": 1, "hour": 9}, "close": {"day": 1, "hour": 17}}]
            },
        }
    ]
}


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "cache" / "places.db")


def _all_text(db_path: str) -> bytes:
    return Path(db_path).read_bytes()


def _columns(db_path: str) -> list[str]:
    with sqlite3.connect(db_path) as db:
        return [r[1] for r in db.execute("PRAGMA table_info(place_coordinates)")]


async def test_only_place_id_and_coordinates_are_stored(db_path: str) -> None:
    await put_coordinates("ChIJABC123", 53.3418, -6.2867, db_path, TTL)
    assert _columns(db_path) == ["place_id", "lat", "lng", "fetched_at"]
    got = await get_coordinates("ChIJABC123", db_path, TTL)
    assert got is not None and (got.lat, got.lng) == (53.3418, -6.2867)


async def test_file_and_directory_permissions(db_path: str) -> None:
    await put_coordinates("ChIJABC123", 53.3, -6.2, db_path, TTL)
    assert Path(db_path).stat().st_mode & 0o777 == 0o600
    assert Path(db_path).parent.stat().st_mode & 0o777 == 0o700


async def test_expiry_boundary_is_before_thirty_days(db_path: str) -> None:
    fetched = time.time() - 10_000
    await put_coordinates("ChIJABC123", 53.3, -6.2, db_path, TTL, fetched_at=fetched)
    limit = expiry_seconds(TTL)
    assert limit <= TTL * 86400
    assert await get_coordinates("ChIJABC123", db_path, TTL, now=fetched + limit - 1)
    assert await get_coordinates("ChIJABC123", db_path, TTL, now=fetched + limit) is None


async def test_reads_do_not_extend_expiry(db_path: str) -> None:
    fetched = int(time.time()) - 5_000
    await put_coordinates("ChIJABC123", 53.3, -6.2, db_path, TTL, fetched_at=fetched)
    for _ in range(3):
        await get_coordinates("ChIJABC123", db_path, TTL)
    with sqlite3.connect(db_path) as db:
        (stored,) = db.execute("SELECT fetched_at FROM place_coordinates").fetchone()
    assert stored == fetched


async def test_older_fetch_never_overwrites_newer(db_path: str) -> None:
    now = time.time()
    await put_coordinates("ChIJABC123", 1.0, 1.0, db_path, TTL, fetched_at=now)
    await put_coordinates("ChIJABC123", 2.0, 2.0, db_path, TTL, fetched_at=now - 100)
    got = await get_coordinates("ChIJABC123", db_path, TTL)
    assert got is not None and got.lat == 1.0


async def test_purge_deletes_expired_rows_physically(db_path: str) -> None:
    old = time.time() - TTL * 86400
    await put_coordinates("ChIJold", 53.3, -6.2, db_path, TTL, fetched_at=old)
    await put_coordinates("ChIJnew", 53.3, -6.2, db_path, TTL)
    assert await purge_expired(db_path, TTL) == 1
    with sqlite3.connect(db_path) as db:
        ids = [r[0] for r in db.execute("SELECT place_id FROM place_coordinates")]
    assert ids == ["ChIJnew"]


async def test_invalid_input_is_not_persisted(db_path: str) -> None:
    await put_coordinates("bad id; DROP TABLE x", 53.3, -6.2, db_path, TTL)
    await put_coordinates("ChIJok", float("nan"), -6.2, db_path, TTL)
    assert not Path(db_path).exists() or await get_coordinates("ChIJok", db_path, TTL) is None


def _legacy_db(db_path: str, rows: list[tuple[Any, ...]]) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as db:
        db.execute(
            """CREATE TABLE geocache (query_key TEXT PRIMARY KEY, place_id TEXT NOT NULL,
            name TEXT NOT NULL, lat REAL NOT NULL, lng REAL NOT NULL, primary_type TEXT,
            types_json TEXT NOT NULL, cached_at INTEGER NOT NULL, opening_hours_json TEXT)"""
        )
        db.executemany("INSERT INTO geocache VALUES (?,?,?,?,?,?,?,?,?)", rows)


async def test_legacy_rich_cache_is_migrated_and_destroyed(db_path: str) -> None:
    now = int(time.time())
    _legacy_db(
        db_path,
        [
            (
                "k1",
                "ChIJfresh",
                "SECRET_VENUE_NAME",
                53.1,
                -6.1,
                "brewery",
                '["SECRET_TYPE"]',
                now - 60,
                '[{"SECRET_HOURS": 1}]',
            ),
            ("k2", "ChIJstale", "OTHER_NAME", 53.2, -6.2, None, "[]", now - TTL * 86400, None),
        ],
    )
    await migrate_legacy(db_path, TTL)
    with sqlite3.connect(db_path) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        rows = db.execute("SELECT * FROM place_coordinates").fetchall()
    assert tables == {"place_coordinates"}
    assert rows == [("ChIJfresh", 53.1, -6.1, now - 60)]  # original fetch time kept
    raw = _all_text(db_path)
    for secret in (b"SECRET_VENUE_NAME", b"SECRET_TYPE", b"SECRET_HOURS", b"OTHER_NAME"):
        assert secret not in raw  # VACUUM + secure_delete left no legacy pages


async def test_startup_purge_migrates_legacy_db(db_path: str) -> None:
    _legacy_db(db_path, [("k", "ChIJx", "N", 1.0, 1.0, None, "[]", int(time.time()), None)])
    await purge_expired(db_path, TTL)
    with sqlite3.connect(db_path) as db:
        assert (
            db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='geocache'").fetchone()[0]
            == 0
        )


async def test_v1_geocode_returns_rich_details_but_persists_only_coordinates(
    db_path: str,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_TEXT_SEARCH)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await geocode_cached("Guinness Storehouse", "Dublin", db_path, TTL, client=client)
        second = await geocode_cached("Guinness Storehouse", "Dublin", db_path, TTL, client=client)

    # The v1 contract is intact: callers still get name/types/hours ...
    assert first.name == "Guinness Storehouse" and first.primary_type == "brewery"
    assert first.opening_hours is not None
    # ... fetched fresh each time (rich details are request-scoped now) ...
    assert calls == 2 and second.place_id == first.place_id
    # ... and only the place ID and coordinates were written.
    raw = _all_text(db_path)
    assert b"ChIJABC123" in raw
    for rich in (b"Guinness", b"brewery", b"Dublin"):
        assert rich not in raw


async def test_failed_query_is_a_cache_miss(db_path: str, monkeypatch: pytest.MonkeyPatch) -> None:
    await put_coordinates("ChIJabc", 53.3, -6.2, db_path, 30)

    class Broken:
        def execute(self, *a: Any, **kw: Any) -> Any:
            raise sqlite3.DatabaseError("disk I/O error")

        async def close(self) -> None:
            return None

    async def broken_open(*a: Any, **kw: Any) -> Broken:
        return Broken()

    monkeypatch.setattr(geocache, "_open", broken_open)
    assert await get_coordinates("ChIJabc", db_path, 30) is None

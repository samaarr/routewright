"""Tests for stay_defaults.lookup_stay_minutes."""

from app.services.stay_defaults import DEFAULT_STAY_MINUTES, lookup_stay_minutes


def test_primary_type_wins_over_array() -> None:
    # A bar/restaurant hybrid: primary says "restaurant" (75) but the array
    # also contains "bar" (90). Primary should win.
    minutes, source = lookup_stay_minutes(
        primary_type="restaurant",
        types=["bar", "restaurant", "food", "establishment"],
    )
    assert minutes == 75
    assert source == "restaurant"


def test_types_array_used_when_no_primary_match() -> None:
    # primary_type isn't in our table; fall through to types.
    minutes, source = lookup_stay_minutes(
        primary_type="thai_restaurant",  # not in table
        types=["thai_restaurant", "restaurant", "food"],
    )
    assert minutes == 75
    assert source == "restaurant"


def test_first_match_in_types_wins() -> None:
    # If both "brewery" and "tourist_attraction" are in the types, brewery
    # comes first (more specific) → 90 min, not 60.
    minutes, source = lookup_stay_minutes(
        primary_type=None,
        types=["brewery", "tourist_attraction", "point_of_interest"],
    )
    assert minutes == 90
    assert source == "brewery"


def test_dublin_pub_gets_pub_duration() -> None:
    minutes, source = lookup_stay_minutes(
        primary_type="pub",
        types=["pub", "bar", "food", "establishment"],
    )
    assert minutes == 90
    assert source == "pub"


def test_default_when_no_match() -> None:
    minutes, source = lookup_stay_minutes(
        primary_type="dog_park",  # not in table
        types=["dog_park"],  # also not in table
    )
    assert minutes == DEFAULT_STAY_MINUTES
    assert source == "default"


def test_handles_missing_primary_type() -> None:
    minutes, source = lookup_stay_minutes(primary_type=None, types=["cafe"])
    assert minutes == 30
    assert source == "cafe"


def test_handles_empty_input() -> None:
    minutes, source = lookup_stay_minutes(primary_type=None, types=None)
    assert minutes == DEFAULT_STAY_MINUTES
    assert source == "default"


def test_transit_station_short_default() -> None:
    minutes, source = lookup_stay_minutes(
        primary_type="train_station",
        types=["train_station", "transit_station", "point_of_interest"],
    )
    assert minutes == 10
    assert source == "train_station"


def test_guinness_storehouse_shape() -> None:
    # Realistic primary/types for Guinness Storehouse.
    # Even if the primary type is "tourist_attraction" (60), the array's
    # "brewery" entry should win once we drop to the array walk.
    minutes, source = lookup_stay_minutes(
        primary_type="tourist_attraction",  # in table at 60
        types=["tourist_attraction", "brewery", "point_of_interest"],
    )
    # primary matches first → 60 min, but this is the wrong answer for
    # Guinness. This test documents the trade-off: primary_type wins by
    # design, even when a later entry is more accurate.
    assert minutes == 60
    assert source == "tourist_attraction"
    # If you want brewery to win for Guinness specifically, the fix is to
    # detect a high-specificity type later in the chain and override.
    # That's a v1.5 refinement, not a v1 blocker.

"""Default stay-duration table by Google Places type.

The table is keyed by Google Places API place types (Table A + Table B,
2026 schema). Lookup order:

    1. primary_type if present (most specific, single value)
    2. each value in the types array, first match wins
    3. fallback default

Numbers come from intuition tuned to first-time tourists on a multi-stop
day trip. They are deliberate guesses. Tune them once we have real usage
data from the first 50 users.

Why these specific numbers:
    - Museum 90 min: average self-guided tour is 60-120 min, 90 is centre
    - Cathedral / church 30 min: most tourists do a walk-through, not Mass
    - Cafe 30 min vs restaurant 75 min: a sit-down meal vs a quick coffee
    - Bar 90 min: enough for two pints and a chat, not a session
    - Park 45 min: a walk-through with a few photos
    - Distillery / brewery 90 min: matches Guinness Storehouse and Jameson
      Distillery actual self-guided tour times
    - Shopping mall 60 min: enough to browse, not a full trip
    - Beach 60 min: a swim or a long walk, not a half-day
    - Default fallback 60 min: roughly what tourists actually spend at an
      unfamiliar "point of interest"
"""

from typing import Final

# Primary lookup: most specific types first.
# When a place returns multiple types, we iterate types in order and pick
# the first one that's in this dict. Google orders types most-specific-first.
DURATION_BY_TYPE: Final[dict[str, int]] = {
    # Major attractions — long visits
    "amusement_park": 240,
    "zoo": 180,
    "aquarium": 120,
    "stadium": 180,
    "casino": 150,
    "ski_resort": 360,
    # Cultural — medium-long visits
    "museum": 90,
    "art_gallery": 75,
    "art_studio": 45,
    "cultural_center": 75,
    "cultural_landmark": 45,
    "performing_arts_theater": 150,
    "concert_hall": 150,
    "auditorium": 120,
    "library": 45,
    "planetarium": 90,
    "convention_center": 120,
    # Historical / tourist sights
    "historical_place": 45,
    "historical_landmark": 30,
    "monument": 20,
    "sculpture": 10,
    "tourist_attraction": 60,
    "observation_deck": 45,
    # Religious sites
    "church": 30,
    "cathedral": 45,
    "mosque": 30,
    "synagogue": 30,
    "hindu_temple": 30,
    "place_of_worship": 30,
    # Food and drink
    "restaurant": 75,
    "fine_dining_restaurant": 120,
    "fast_food_restaurant": 30,
    "cafe": 30,
    "coffee_shop": 30,
    "bakery": 15,
    "bar": 90,
    "pub": 90,  # critical for Dublin
    "wine_bar": 90,
    "night_club": 120,
    "ice_cream_shop": 15,
    "meal_takeaway": 15,
    # Drink / production tours
    "brewery": 90,  # critical for Guinness Storehouse
    "winery": 90,
    "distillery": 90,  # critical for Jameson
    # Nature and outdoor
    "park": 45,
    "national_park": 180,
    "state_park": 120,
    "botanical_garden": 75,
    "garden": 45,
    "beach": 60,
    "hiking_area": 180,
    "marina": 30,
    # Shopping and markets
    "shopping_mall": 60,
    "market": 45,
    "department_store": 60,
    "book_store": 30,
    "clothing_store": 30,
    "gift_shop": 20,
    "store": 20,
    # Accommodation — used as departure anchors, not tourist destinations
    "lodging": 0,
    "hotel": 0,
    # Transit (a stop, not a destination)
    "train_station": 10,
    "subway_station": 10,
    "bus_station": 10,
    "transit_station": 10,
    "airport": 60,
    # Generic catch-alls — used only if nothing more specific matches
    "point_of_interest": 60,
    "establishment": 60,
}

# Final fallback when no type in the array matches the table.
DEFAULT_STAY_MINUTES: Final[int] = 60


def lookup_stay_minutes(
    primary_type: str | None,
    types: list[str] | None,
) -> tuple[int, str]:
    """Find the stay duration for a place.

    Returns (minutes, matched_type). matched_type is "default" if nothing
    matched — useful for logging which places fall through.

    Args:
        primary_type: The `primaryType` field from Places API. Single value.
        types: The `types` array from Places API. Multiple values,
            ordered most-specific-first.
    """
    # 1. Try primary_type first.
    if primary_type and primary_type in DURATION_BY_TYPE:
        return DURATION_BY_TYPE[primary_type], primary_type

    # 2. Walk the types array in order.
    for t in types or []:
        if t in DURATION_BY_TYPE:
            return DURATION_BY_TYPE[t], t

    # 3. Fallback.
    return DEFAULT_STAY_MINUTES, "default"

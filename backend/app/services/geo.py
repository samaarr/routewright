"""Geodesic distance utility.

haversine_km: standard great-circle distance between two lat/lng points.
Used by the route optimiser (app/services/optimise.py).
"""

import math

from app.services.geocoder import GeocodedPlace


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two points, in kilometres."""
    r = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = math.sin(d_lat / 2) ** 2 + (
        math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lng / 2) ** 2
    )
    return r * 2 * math.asin(math.sqrt(a))


def _path_length(places: list[GeocodedPlace], order: list[int]) -> float:
    """Sum of haversine_km for consecutive stops in the given index order."""
    return sum(
        haversine_km(
            places[order[i]].lat,
            places[order[i]].lng,
            places[order[i + 1]].lat,
            places[order[i + 1]].lng,
        )
        for i in range(len(order) - 1)
    )

"""Geocode a city name → a full City object (M11).

Uses Nominatim (OpenStreetMap, free, no key) + timezonefinder for timezone
resolution. Returns None on failure so the caller can show a user-friendly
message without crashing.
"""

from __future__ import annotations

import logging

from events_gen.models import City
from events_gen.registry import slugify

logger = logging.getLogger(__name__)


def geocode_city(name: str) -> City | None:
    """Resolve a city name to a :class:`City` with coords + timezone.

    Returns ``None`` if the name can't be geocoded or the result doesn't look
    like a city/town.
    """
    from geopy.geocoders import Nominatim
    from timezonefinder import TimezoneFinder

    try:
        geolocator = Nominatim(user_agent="events-gen/0.1")
        location = geolocator.geocode(name, exactly_one=True, addressdetails=True)
        if location is None:
            logger.info("geocode returned no result for %r", name)
            return None

        address = location.raw.get("address", {})
        city_name = (
            address.get("city")
            or address.get("town")
            or address.get("municipality")
            or address.get("village")
            or name.strip().title()
        )
        country = address.get("country", "")
        country_code = address.get("country_code", "").upper()

        tf = TimezoneFinder()
        timezone = tf.timezone_at(lat=location.latitude, lng=location.longitude)
        if timezone is None:
            timezone = "UTC"

        return City(
            slug=slugify(city_name),
            name=city_name,
            country=country,
            country_code=country_code,
            timezone=timezone,
            latitude=location.latitude,
            longitude=location.longitude,
        )
    except Exception:  # noqa: BLE001 — geocoding is best-effort
        logger.warning("geocode failed for %r", name, exc_info=True)
        return None

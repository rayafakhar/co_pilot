"""Dependency-free route distance and duration calculations."""

from __future__ import annotations

from dataclasses import dataclass
from math import asin, ceil, cos, radians, sin, sqrt

from tracker.models import AircraftType, Airport

EARTH_RADIUS_KM = 6_371.0088
PRACTICAL_RANGE_FACTOR = 0.90


@dataclass(frozen=True)
class DurationBreakdown:
    taxi_out_minutes: int
    climb_minutes: int
    cruise_minutes: int
    descent_minutes: int
    taxi_in_minutes: int
    variability_minutes: int

    @property
    def total_minutes(self) -> int:
        return sum((self.taxi_out_minutes, self.climb_minutes, self.cruise_minutes,
                    self.descent_minutes, self.taxi_in_minutes, self.variability_minutes))


def haversine_distance_km(origin: Airport, destination: Airport) -> float:
    """Return great-circle distance; airport coordinates must be available."""
    if None in (origin.latitude, origin.longitude, destination.latitude, destination.longitude):
        raise ValueError("Both airports require latitude and longitude for route calculations.")
    lat1, lon1, lat2, lon2 = map(
        radians,
        map(float, (origin.latitude, origin.longitude, destination.latitude, destination.longitude)),
    )
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    value = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(value))


def practical_range_km(aircraft_type: AircraftType) -> float:
    """Reserve ten percent of configured maximum range for a conservative demo limit."""
    return aircraft_type.maximum_range_km * PRACTICAL_RANGE_FACTOR


def calculate_duration(
    distance_km: float,
    aircraft_type: AircraftType,
    *,
    variability_factor: float = 0.04,
) -> DurationBreakdown:
    """Estimate block time from transparent, non-certified simulation assumptions."""
    if distance_km <= 0:
        raise ValueError("Route distance must be positive.")
    if aircraft_type.typical_cruise_speed_kmh <= 0:
        raise ValueError("Aircraft cruise speed must be positive.")
    if distance_km < 1_500:
        taxi_out, climb, descent, taxi_in, efficiency = 14, 18, 17, 9, 0.84
    elif distance_km < 4_000:
        taxi_out, climb, descent, taxi_in, efficiency = 17, 22, 20, 11, 0.90
    else:
        taxi_out, climb, descent, taxi_in, efficiency = 20, 25, 23, 13, 0.94
    cruise_minutes = ceil(distance_km / (aircraft_type.typical_cruise_speed_kmh * efficiency) * 60)
    variability_minutes = max(5, ceil(cruise_minutes * variability_factor))
    return DurationBreakdown(taxi_out, climb, cruise_minutes, descent, taxi_in, variability_minutes)

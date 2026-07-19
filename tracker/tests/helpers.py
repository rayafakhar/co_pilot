"""Small factories for readable aviation-domain tests."""

from datetime import datetime, timedelta, timezone

from tracker.models import Aircraft, AircraftType, Airport, Flight


def airport(
    code: str, *, timezone_name: str = "UTC", latitude: float = 51.0, longitude: float = 0.0
) -> Airport:
    return Airport.objects.create(
        name=f"{code} Test Airport",
        city=f"{code} City",
        country="Testland",
        iata_code=code,
        icao_code=f"T{code}",
        timezone=timezone_name,
        latitude=latitude,
        longitude=longitude,
    )


def aircraft_type(**overrides) -> AircraftType:
    values = {
        "manufacturer": "Test Airframes",
        "model": "T100",
        "icao_type_code": "T100",
        "category": AircraftType.Category.NARROW_BODY,
        "typical_cruise_speed_kmh": 800,
        "maximum_range_km": 6000,
        "minimum_turnaround_minutes": 45,
        "passenger_capacity": 150,
        "crew_count": 6,
    }
    values.update(overrides)
    return AircraftType.objects.create(**values)


def aircraft(base: Airport, kind: AircraftType, registration: str = "N100TS") -> Aircraft:
    return Aircraft.objects.create(
        registration=registration,
        display_name="Test aircraft",
        aircraft_type=kind,
        base_airport=base,
        last_known_airport=base,
    )


def flight(plane: Aircraft, origin: Airport, destination: Airport, **overrides) -> Flight:
    departure = overrides.pop("scheduled_departure", datetime(2026, 7, 19, 12, tzinfo=timezone.utc))
    values = {
        "flight_number": "TS100",
        "aircraft": plane,
        "departure_airport": origin,
        "arrival_airport": destination,
        "scheduled_departure": departure,
        "scheduled_arrival": departure + timedelta(hours=2),
        "distance_km": 1200,
        "planned_duration_minutes": 120,
    }
    values.update(overrides)
    return Flight(**values)

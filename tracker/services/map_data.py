"""Bounded serialization for the live simulated flight-network map."""

from __future__ import annotations

from datetime import datetime, timedelta

from django.urls import reverse

from tracker.models import Flight, SimulationClock

from .presentation import utc_iso
from .status import effective_arrival, effective_departure, estimated_progress, get_flight_status

MAP_CANDIDATE_LIMIT = 500
MAP_LOOKBACK = timedelta(days=2)
MAP_LOOKAHEAD = timedelta(days=1)
MOVING_STATUSES = {
    Flight.Status.DEPARTED,
    Flight.Status.EN_ROUTE,
    Flight.Status.DIVERTED,
}


def _coordinates(airport) -> list[float] | None:
    if airport.latitude is None or airport.longitude is None:
        return None
    return [float(airport.longitude), float(airport.latitude)]


def _airport_data(airport) -> dict[str, object] | None:
    coordinates = _coordinates(airport)
    if coordinates is None:
        return None
    return {
        "code": airport.display_code,
        "name": airport.name,
        "city": airport.city,
        "country": airport.country,
        "coordinates": coordinates,
    }


def _is_active(flight: Flight, status_code: str, simulation_time: datetime) -> bool:
    return (
        flight.status != Flight.Status.CANCELLED
        and status_code in MOVING_STATUSES
        and effective_departure(flight) <= simulation_time < effective_arrival(flight)
        and flight.actual_arrival is None
    )


def serialize_map_flight(
    flight: Flight,
    simulation_time: datetime,
) -> dict[str, object] | None:
    """Serialize one active movement, omitting records with incomplete geometry."""
    status = get_flight_status(flight, simulation_time)
    if not _is_active(flight, status.code, simulation_time):
        return None

    result_airport = flight.diversion_airport or flight.arrival_airport
    origin = _airport_data(flight.departure_airport)
    planned_destination = _airport_data(flight.arrival_airport)
    result_destination = _airport_data(result_airport)
    if not origin or not planned_destination or not result_destination:
        return None

    aircraft_type = flight.aircraft.aircraft_type
    return {
        "flight_number": flight.flight_number,
        "aircraft_registration": flight.aircraft.registration,
        "aircraft_name": flight.aircraft.display_name,
        "aircraft_type": f"{aircraft_type.manufacturer} {aircraft_type.model}",
        "status_code": status.code,
        "status_label": status.label,
        "delay_minutes": flight.delay_minutes,
        "origin": origin,
        "planned_destination": planned_destination,
        "result_destination": result_destination,
        "diverted": flight.diversion_airport_id is not None,
        "effective_departure": utc_iso(effective_departure(flight)),
        "effective_arrival": utc_iso(effective_arrival(flight)),
        "progress": estimated_progress(flight, simulation_time),
        "flight_url": reverse("tracker:flight_detail", args=[flight.flight_number]),
        "aircraft_url": reverse(
            "tracker:aircraft_detail",
            args=[flight.aircraft.registration],
        ),
    }


def _longitude_interval(longitudes: list[float]) -> tuple[float, float]:
    """Return the narrowest longitude interval, allowing an east bound above 180."""
    if len(longitudes) < 2:
        longitude = longitudes[0]
        return longitude, longitude
    if max(longitudes) - min(longitudes) <= 180:
        return min(longitudes), max(longitudes)
    normalized = sorted((longitude + 180) % 360 - 180 for longitude in longitudes)
    gaps = [
        (
            (normalized[(index + 1) % len(normalized)] - normalized[index]) % 360,
            index,
        )
        for index in range(len(normalized))
    ]
    _, gap_index = max(gaps)
    west = normalized[(gap_index + 1) % len(normalized)]
    east = normalized[gap_index]
    if east < west:
        east += 360
    return west, east


def network_bounds(airport_features: list[dict[str, object]]) -> dict[str, list[float]] | None:
    if not airport_features:
        return None
    coordinates = [feature["geometry"]["coordinates"] for feature in airport_features]
    west, east = _longitude_interval([point[0] for point in coordinates])
    latitudes = [point[1] for point in coordinates]
    return {
        "southwest": [west, min(latitudes)],
        "northeast": [east, max(latitudes)],
    }


def _airport_features(flights: list[dict[str, object]]) -> list[dict[str, object]]:
    airports: dict[str, dict[str, object]] = {}
    for flight in flights:
        for key in ("origin", "planned_destination", "result_destination"):
            airport = flight[key]
            airports[airport["code"]] = airport
    return [
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": airport["coordinates"],
            },
            "properties": {
                "code": airport["code"],
                "name": airport["name"],
                "city": airport["city"],
                "country": airport["country"],
            },
        }
        for airport in sorted(airports.values(), key=lambda item: item["code"])
    ]


def build_network_map_payload(
    *,
    simulation_time: datetime,
    generated_at: datetime,
    clock: SimulationClock | None,
) -> dict[str, object]:
    """Query a bounded candidate window and return the versioned public contract."""
    candidates = (
        Flight.objects.filter(
            scheduled_departure__gte=simulation_time - MAP_LOOKBACK,
            scheduled_departure__lte=simulation_time + MAP_LOOKAHEAD,
            scheduled_arrival__gte=simulation_time - MAP_LOOKAHEAD,
        )
        .select_related(
            "aircraft__aircraft_type",
            "departure_airport",
            "arrival_airport",
            "diversion_airport",
        )
        .order_by("scheduled_departure", "flight_number")[:MAP_CANDIDATE_LIMIT]
    )

    flights = []
    omitted_flights = 0
    for candidate in candidates:
        status = get_flight_status(candidate, simulation_time)
        if not _is_active(candidate, status.code, simulation_time):
            continue
        serialized = serialize_map_flight(candidate, simulation_time)
        if serialized is None:
            omitted_flights += 1
            continue
        flights.append(serialized)

    airport_features = _airport_features(flights)
    return {
        "schema_version": 1,
        "generated_at": utc_iso(generated_at),
        "simulation": {
            "active": clock is not None,
            "time": utc_iso(simulation_time),
            "speed_multiplier": (
                format(clock.speed_multiplier, "f") if clock is not None else None
            ),
            "paused": clock.paused if clock is not None else False,
        },
        "summary": {
            "active_flights": len(flights),
            "delayed_flights": sum(flight["delay_minutes"] > 0 for flight in flights),
            "diverted_flights": sum(flight["diverted"] for flight in flights),
            "airports": len(airport_features),
            "omitted_flights": omitted_flights,
        },
        "bounds": network_bounds(airport_features),
        "airports": {
            "type": "FeatureCollection",
            "features": airport_features,
        },
        "flights": flights,
    }

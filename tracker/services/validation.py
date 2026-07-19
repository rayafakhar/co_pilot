"""Structured cross-flight invariant validation for schedules."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta

from tracker.models import Flight, MaintenanceBlock

from .distance import calculate_duration, practical_range_km
from .status import effective_arrival, effective_departure


@dataclass(frozen=True)
class ScheduleViolation:
    code: str
    message: str
    aircraft_registration: str
    flight_number: str = ""


def _violation(code: str, message: str, flight: Flight) -> ScheduleViolation:
    return ScheduleViolation(code, message, flight.aircraft.registration, flight.flight_number)


def validate_schedule(
    flights: Iterable[Flight],
    maintenance_blocks: Iterable[MaintenanceBlock] = (),
) -> list[ScheduleViolation]:
    """Validate timing, range, continuity, movement, and maintenance invariants."""
    grouped: dict[int | None, list[Flight]] = defaultdict(list)
    for flight in flights:
        grouped[flight.aircraft_id].append(flight)
    blocks_by_aircraft: dict[int | None, list[MaintenanceBlock]] = defaultdict(list)
    for block in maintenance_blocks:
        blocks_by_aircraft[block.aircraft_id].append(block)

    violations: list[ScheduleViolation] = []
    for aircraft_id, itinerary in grouped.items():
        itinerary.sort(key=lambda item: (item.scheduled_departure, item.flight_number))
        aircraft = itinerary[0].aircraft
        current_airport_id = aircraft.base_airport_id
        previous_operating: Flight | None = None

        for flight in itinerary:
            if flight.departure_airport_id == flight.arrival_airport_id:
                violations.append(
                    _violation("same_airport", "Departure and arrival match.", flight)
                )
            if flight.scheduled_arrival <= flight.scheduled_departure:
                violations.append(_violation("time_order", "Scheduled times are reversed.", flight))
            if flight.actual_arrival and (
                not flight.actual_departure or flight.actual_arrival <= flight.actual_departure
            ):
                violations.append(
                    _violation("actual_time", "Actual timestamps are incoherent.", flight)
                )
            if flight.status == Flight.Status.CANCELLED and (
                flight.actual_departure or flight.actual_arrival or flight.diversion_airport_id
            ):
                violations.append(
                    _violation("cancelled_movement", "Cancelled flight moves aircraft.", flight)
                )
            if flight.diversion_airport_id in {
                flight.departure_airport_id,
                flight.arrival_airport_id,
            }:
                violations.append(
                    _violation("invalid_diversion", "Diversion airport is not distinct.", flight)
                )

            distance = float(flight.distance_km)
            if distance > practical_range_km(aircraft.aircraft_type):
                violations.append(
                    _violation("range", "Route exceeds practical aircraft range.", flight)
                )
            if distance > 0:
                expected = calculate_duration(distance, aircraft.aircraft_type).total_minutes
                tolerance = max(20, round(expected * 0.20))
                if abs(flight.planned_duration_minutes - expected) > tolerance:
                    violations.append(
                        _violation("duration", "Planned duration is implausible.", flight)
                    )

            if current_airport_id and flight.departure_airport_id != current_airport_id:
                violations.append(
                    _violation(
                        "continuity", "Flight does not start at the aircraft location.", flight
                    )
                )

            cancelled = flight.status == Flight.Status.CANCELLED
            if not cancelled:
                start = effective_departure(flight)
                end = effective_arrival(flight)
                if previous_operating:
                    previous_end = effective_arrival(previous_operating)
                    required = timedelta(minutes=aircraft.aircraft_type.minimum_turnaround_minutes)
                    if start < previous_end:
                        violations.append(
                            _violation("overlap", "Aircraft operations overlap.", flight)
                        )
                    elif start < previous_end + required:
                        violations.append(
                            _violation("turnaround", "Minimum turnaround is not respected.", flight)
                        )
                for block in blocks_by_aircraft.get(aircraft_id, []):
                    if start < block.ends_at and end > block.starts_at:
                        violations.append(
                            _violation("maintenance", "Flight overlaps maintenance.", flight)
                        )
                previous_operating = flight
                current_airport_id = flight.diversion_airport_id or flight.arrival_airport_id

    return violations


def violation_counts(violations: Iterable[ScheduleViolation]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for violation in violations:
        counts[violation.code] += 1
    return dict(counts)

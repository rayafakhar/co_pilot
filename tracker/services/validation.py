"""Structured cross-flight invariant validation for schedules."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta

from tracker.models import CrewMember, Flight, FlightCrew, MaintenanceBlock

from .distance import calculate_duration, practical_range_km
from .status import effective_arrival, effective_departure


@dataclass(frozen=True)
class ScheduleViolation:
    code: str
    message: str
    aircraft_registration: str
    flight_number: str = ""
    crew_member_name: str = ""


def _violation(code: str, message: str, flight: Flight) -> ScheduleViolation:
    return ScheduleViolation(code, message, flight.aircraft.registration, flight.flight_number)


def _crew_violation(
    code: str, message: str, flight: Flight, crew_member: CrewMember
) -> ScheduleViolation:
    return ScheduleViolation(
        code,
        message,
        flight.aircraft.registration,
        flight.flight_number,
        crew_member.full_name(),
    )


def validate_schedule(
    flights: Iterable[Flight],
    maintenance_blocks: Iterable[MaintenanceBlock] = (),
) -> list[ScheduleViolation]:
    """Validate timing, range, continuity, movement, maintenance, and crew invariants."""
    flight_list = list(flights)
    grouped: dict[int | None, list[Flight]] = defaultdict(list)
    for flight in flight_list:
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

    # ── Crew-specific validations ──────────────────────────────────────────
    flights_by_id = {flight.pk: flight for flight in flight_list if flight.pk is not None}
    crew_schedules: dict[int, list[Flight]] = defaultdict(list)
    assignments = FlightCrew.objects.filter(flight_id__in=flights_by_id).values_list(
        "crew_member_id",
        "flight_id",
    )
    for crew_member_id, flight_id in assignments:
        crew_schedules[crew_member_id].append(flights_by_id[flight_id])
    crew_members = CrewMember.objects.in_bulk(crew_schedules)

    for crew_member_id in sorted(crew_schedules):
        crew_member = crew_members.get(crew_member_id)
        if crew_member is None:
            continue
        crew_flights = sorted(
            [f for f in crew_schedules[crew_member_id] if f.status != Flight.Status.CANCELLED],
            key=lambda item: (effective_departure(item), item.flight_number),
        )

        # Rule 1: No Double-Booking
        # Rule 2: 8-Hour Rest Rule
        # We iterate through the crew member's flights and check overlapping time
        # windows plus the 8-hour rest gap between consecutive assignments.
        for i in range(len(crew_flights)):
            flight_a = crew_flights[i]
            start_a = effective_departure(flight_a)
            end_a = effective_arrival(flight_a)

            for j in range(i + 1, len(crew_flights)):
                flight_b = crew_flights[j]
                start_b = effective_departure(flight_b)
                end_b = effective_arrival(flight_b)

                # If the time windows overlap, that's a double-booking
                if start_b < end_a and start_a < end_b:
                    violations.append(
                        _crew_violation(
                            "double_booking",
                            f"{crew_member.full_name()} is scheduled on overlapping flights "
                            f"{flight_a.flight_number} and {flight_b.flight_number}.",
                            flight_b,
                            crew_member,
                        )
                    )
                    break  # One violation per pair is enough

                # Check 8-hour rest between consecutive non-overlapping flights
                # flight_a comes before flight_b (already sorted)
                # end_a <= start_b, so check rest period
                rest_gap = start_b - end_a
                minimum_rest = timedelta(hours=8)
                if rest_gap < minimum_rest:
                    violations.append(
                        _crew_violation(
                            "insufficient_rest",
                            f"{crew_member.full_name()} has less than 8 hours rest between "
                            f"{flight_a.flight_number} and {flight_b.flight_number} "
                            f"(gap: {rest_gap}).",
                            flight_b,
                            crew_member,
                        )
                    )

        # Rule 3: Geographic Continuity
        # When a crew member lands at an airport (diversion_airport_id or arrival_airport_id),
        # their very next flight must originate from that same airport.
        for i in range(len(crew_flights) - 1):
            flight_a = crew_flights[i]
            flight_b = crew_flights[i + 1]

            start_a = effective_departure(flight_a)
            start_b = effective_departure(flight_b)

            # Only check continuity if flight_b is scheduled after flight_a
            if start_b <= start_a:
                continue

            landing_airport = flight_a.diversion_airport or flight_a.arrival_airport

            if flight_b.departure_airport_id != landing_airport.pk:
                violations.append(
                    _crew_violation(
                        "geo_continuity",
                        f"{crew_member.full_name()} lands at {landing_airport.display_code}, but "
                        f"{flight_b.flight_number} departs from "
                        f"{flight_b.departure_airport.display_code}.",
                        flight_b,
                        crew_member,
                    )
                )

    return violations


def violation_counts(violations: Iterable[ScheduleViolation]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for violation in violations:
        counts[violation.code] += 1
    return dict(counts)

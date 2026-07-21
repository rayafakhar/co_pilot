"""Deterministic aircraft-itinerary generation and atomic persistence."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from math import ceil

from django.db import transaction
from django.utils import timezone

from tracker.models import Aircraft, AircraftType, Airport, Flight, MaintenanceBlock

from .clock import initialize_simulation_clock, reset_simulation_clock
from .distance import calculate_duration, haversine_distance_km, practical_range_km
from .fixtures import load_reference_data
from .status import get_flight_status
from .validation import ScheduleViolation, validate_schedule, violation_counts


class ScheduleGenerationError(RuntimeError):
    def __init__(self, violations: list[ScheduleViolation]):
        self.violations = violations
        super().__init__(f"Generated schedule has {len(violations)} violation(s).")


@dataclass(frozen=True)
class GenerationConfig:
    seed: int = 20260719
    aircraft_count: int = 12
    days_back: int = 3
    days_forward: int = 7
    min_flights_per_aircraft: int = 4
    max_flights_per_aircraft: int = 10
    delay_rate: float = 0.18
    cancellation_rate: float = 0.04
    diversion_rate: float = 0.03
    ferry_rate: float = 0.08
    maintenance_rate: float = 0.06
    clear: bool = False
    anchor_time: datetime | None = None

    def validate(self) -> None:
        if self.aircraft_count <= 0:
            raise ValueError("aircraft_count must be positive")
        if self.days_back < 0 or self.days_forward < 0 or not (self.days_back + self.days_forward):
            raise ValueError("generation window must contain at least one day")
        if self.min_flights_per_aircraft <= 0:
            raise ValueError("minimum flights must be positive")
        if self.max_flights_per_aircraft < self.min_flights_per_aircraft:
            raise ValueError("maximum flights must be at least the minimum")
        for name in (
            "delay_rate",
            "cancellation_rate",
            "diversion_rate",
            "ferry_rate",
            "maintenance_rate",
        ):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.anchor_time and timezone.is_naive(self.anchor_time):
            raise ValueError("anchor_time must be timezone-aware")


@dataclass
class GenerationReport:
    seed: int
    anchor_time: datetime
    airports_created: int = 0
    aircraft_types_created: int = 0
    aircraft_created: int = 0
    flights_created: int = 0
    maintenance_blocks_created: int = 0
    completed_flights: int = 0
    active_flights: int = 0
    future_flights: int = 0
    delayed_flights: int = 0
    cancelled_flights: int = 0
    diverted_flights: int = 0
    ferry_flights: int = 0
    violation_totals: dict[str, int] = field(default_factory=dict)


def generation_anchor(config: GenerationConfig) -> datetime:
    """Return a deterministic UTC anchor, preferring a YYYYMMDD seed when supplied."""
    if config.anchor_time:
        return config.anchor_time.astimezone(dt_timezone.utc)
    seed_text = str(abs(config.seed))
    if len(seed_text) == 8:
        try:
            parsed = datetime.strptime(seed_text, "%Y%m%d")
        except ValueError:
            pass
        else:
            return parsed.replace(hour=12, tzinfo=dt_timezone.utc)
    baseline = datetime(2020, 1, 1, 12, tzinfo=dt_timezone.utc)
    return baseline + timedelta(days=abs(config.seed) % 3_653)


def _clear_simulation_data() -> None:
    MaintenanceBlock.objects.all().delete()
    Flight.objects.all().delete()
    Aircraft.objects.all().delete()
    AircraftType.objects.all().delete()
    Airport.objects.all().delete()


def _create_aircraft(
    count: int,
    airports: list[Airport],
    aircraft_types: list[AircraftType],
    rng: random.Random,
) -> list[Aircraft]:
    existing_registrations = set(Aircraft.objects.values_list("registration", flat=True))
    sequence = 1
    fleet: list[Aircraft] = []
    for position in range(count):
        while f"N{sequence:03d}NS" in existing_registrations:
            sequence += 1
        aircraft_type = aircraft_types[position % len(aircraft_types)]
        viable_bases = [
            candidate
            for candidate in airports
            if _valid_destinations(candidate, airports, aircraft_type)
        ]
        if not viable_bases:
            raise RuntimeError(f"No airport pair is suitable for {aircraft_type}.")
        base = viable_bases[rng.randrange(len(viable_bases))]
        aircraft = Aircraft(
            registration=f"N{sequence:03d}NS",
            display_name=f"Northstar {aircraft_type.model}",
            aircraft_type=aircraft_type,
            operator="Northstar Demo Air",
            base_airport=base,
            last_known_airport=base,
            manufactured_year=2017 + sequence % 9,
            serial_number=f"SIM-{sequence:05d}",
        )
        aircraft.full_clean()
        aircraft.save()
        fleet.append(aircraft)
        existing_registrations.add(aircraft.registration)
        sequence += 1
    return fleet


def _valid_destinations(
    origin: Airport, airports: list[Airport], aircraft_type: AircraftType
) -> list[tuple[Airport, float]]:
    routes: list[tuple[Airport, float]] = []
    for destination in airports:
        if destination.pk == origin.pk:
            continue
        distance = haversine_distance_km(origin, destination)
        if distance <= practical_range_km(aircraft_type):
            routes.append((destination, distance))
    return routes


def _flight_number(config: GenerationConfig, aircraft: Aircraft, leg: int, ferry: bool) -> str:
    sequence = int("".join(character for character in aircraft.registration if character.isdigit()))
    prefix = "NF" if ferry else "NS"
    return f"{prefix}{config.seed % 100:02d}{sequence:03d}{leg + 1:02d}"


def _build_itinerary(
    aircraft: Aircraft,
    airports: list[Airport],
    config: GenerationConfig,
    anchor: datetime,
    rng: random.Random,
) -> tuple[list[Flight], list[MaintenanceBlock], Airport]:
    window_start = anchor - timedelta(days=config.days_back)
    window_end = anchor + timedelta(days=config.days_forward)
    flight_count = rng.randint(config.min_flights_per_aircraft, config.max_flights_per_aircraft)
    slot_minutes = max(180, int((window_end - window_start).total_seconds() / 60 / flight_count))
    scheduled_slot = window_start + timedelta(minutes=rng.randint(0, min(360, slot_minutes // 3)))
    effective_ready = window_start
    previous_scheduled_arrival: datetime | None = None
    current_airport = aircraft.base_airport
    last_known_airport = current_airport
    flights: list[Flight] = []
    maintenance_blocks: list[MaintenanceBlock] = []

    for leg in range(flight_count):
        turnaround = timedelta(minutes=aircraft.aircraft_type.minimum_turnaround_minutes)
        if leg and rng.random() < config.maintenance_rate:
            block_start = effective_ready + timedelta(minutes=15)
            block_end = block_start + timedelta(hours=rng.randint(4, 10))
            block = MaintenanceBlock(
                aircraft=aircraft,
                starts_at=block_start,
                ends_at=block_end,
                reason=rng.choice(
                    ("A-check inspection", "Cabin systems inspection", "Planned engineering review")
                ),
                notes="Simulated maintenance window; no real operator data is used.",
            )
            block.full_clean()
            maintenance_blocks.append(block)
            scheduled_slot = max(scheduled_slot, block_end + timedelta(minutes=30))
            effective_ready = block_end + timedelta(minutes=30)

        scheduled_departure = scheduled_slot
        if previous_scheduled_arrival:
            scheduled_departure = max(scheduled_departure, previous_scheduled_arrival + turnaround)
        routes = _valid_destinations(current_airport, airports, aircraft.aircraft_type)
        if not routes:
            raise RuntimeError(
                f"No in-range destination for {aircraft.registration} at {current_airport}."
            )
        destination, route_distance = rng.choice(routes)
        distance_km = round(route_distance)
        duration_minutes = calculate_duration(route_distance, aircraft.aircraft_type).total_minutes
        scheduled_arrival = scheduled_departure + timedelta(minutes=duration_minutes)

        ferry = rng.random() < config.ferry_rate
        cancelled = rng.random() < config.cancellation_rate
        own_delay = 0
        if not cancelled and rng.random() < config.delay_rate:
            own_delay = rng.randint(60, 150) if rng.random() < 0.20 else rng.randint(10, 45)
        propagated_delay = max(
            0, ceil((effective_ready - scheduled_departure).total_seconds() / 60)
        )
        delay_minutes = 0 if cancelled else own_delay + propagated_delay
        estimated_departure = (
            scheduled_departure + timedelta(minutes=delay_minutes) if delay_minutes else None
        )
        estimated_arrival = (
            scheduled_arrival + timedelta(minutes=delay_minutes) if delay_minutes else None
        )
        effective_departure = estimated_departure or scheduled_departure
        effective_arrival = estimated_arrival or scheduled_arrival

        diversion_airport = None
        if not cancelled and effective_departure <= anchor and rng.random() < config.diversion_rate:
            alternatives = [route for route, _ in routes if route.pk != destination.pk]
            if alternatives:
                diversion_airport = rng.choice(alternatives)

        status = Flight.Status.CANCELLED if cancelled else Flight.Status.SCHEDULED
        if diversion_airport:
            status = Flight.Status.DIVERTED
        actual_departure = None
        actual_arrival = None
        if not cancelled and effective_departure <= anchor:
            actual_departure = effective_departure
            if effective_arrival <= anchor:
                actual_arrival = effective_arrival

        flight = Flight(
            flight_number=_flight_number(config, aircraft, leg, ferry),
            aircraft=aircraft,
            departure_airport=current_airport,
            arrival_airport=destination,
            scheduled_departure=scheduled_departure,
            scheduled_arrival=scheduled_arrival,
            estimated_departure=estimated_departure,
            estimated_arrival=estimated_arrival,
            actual_departure=actual_departure,
            actual_arrival=actual_arrival,
            status=status,
            flight_type=Flight.FlightType.FERRY if ferry else Flight.FlightType.PASSENGER,
            distance_km=distance_km,
            planned_duration_minutes=duration_minutes,
            delay_minutes=delay_minutes,
            departure_terminal=str(rng.randint(1, 5)),
            departure_gate=f"{rng.choice('ABCDEFGH')}{rng.randint(1, 42)}",
            arrival_terminal=str(rng.randint(1, 5)),
            arrival_gate=f"{rng.choice('ABCDEFGH')}{rng.randint(1, 42)}",
            cancelled_reason="Simulated operational cancellation" if cancelled else "",
            diversion_airport=diversion_airport,
            notes=(
                "Explicit simulated repositioning flight."
                if ferry
                else "Synthetic passenger operation for the portfolio showcase."
            ),
        )
        if not cancelled and not diversion_airport:
            flight.status = get_flight_status(flight, anchor).code
        flight.full_clean()
        flights.append(flight)

        if cancelled:
            effective_ready = max(effective_ready, scheduled_departure + timedelta(minutes=30))
        else:
            resulting_airport = diversion_airport or destination
            if actual_arrival:
                last_known_airport = resulting_airport
            current_airport = resulting_airport
            effective_ready = effective_arrival + turnaround
        previous_scheduled_arrival = scheduled_arrival
        jitter = rng.randint(-max(1, slot_minutes // 12), max(1, slot_minutes // 12))
        scheduled_slot = scheduled_departure + timedelta(minutes=slot_minutes + jitter)

    return flights, maintenance_blocks, last_known_airport


def _populate_report(
    report: GenerationReport,
    flights: list[Flight],
    blocks: list[MaintenanceBlock],
) -> None:
    report.flights_created = len(flights)
    report.maintenance_blocks_created = len(blocks)
    report.completed_flights = sum(flight.actual_arrival is not None for flight in flights)
    report.active_flights = sum(
        flight.actual_departure is not None and flight.actual_arrival is None for flight in flights
    )
    report.future_flights = sum(
        flight.scheduled_departure > report.anchor_time and flight.status != Flight.Status.CANCELLED
        for flight in flights
    )
    report.delayed_flights = sum(flight.delay_minutes > 0 for flight in flights)
    report.cancelled_flights = sum(flight.status == Flight.Status.CANCELLED for flight in flights)
    report.diverted_flights = sum(flight.status == Flight.Status.DIVERTED for flight in flights)
    report.ferry_flights = sum(flight.flight_type == Flight.FlightType.FERRY for flight in flights)


@transaction.atomic
def generate_schedule(config: GenerationConfig) -> GenerationReport:
    """Build, validate, and persist a complete batch in one transaction."""
    config.validate()
    anchor = generation_anchor(config)
    rng = random.Random(config.seed)
    if config.clear:
        _clear_simulation_data()
    airports, aircraft_types, airport_created, type_created = load_reference_data()
    fleet = _create_aircraft(config.aircraft_count, airports, aircraft_types, rng)
    all_flights: list[Flight] = []
    all_blocks: list[MaintenanceBlock] = []

    for aircraft in fleet:
        flights, blocks, last_known = _build_itinerary(aircraft, airports, config, anchor, rng)
        all_flights.extend(flights)
        all_blocks.extend(blocks)
        aircraft.last_known_airport = last_known
        if any(block.starts_at <= anchor < block.ends_at for block in blocks):
            aircraft.maintenance_status = Aircraft.MaintenanceStatus.IN_MAINTENANCE
        elif any(block.starts_at > anchor for block in blocks):
            aircraft.maintenance_status = Aircraft.MaintenanceStatus.SCHEDULED
        aircraft.save(update_fields=["last_known_airport", "maintenance_status"])

    stored_flights = list(
        Flight.objects.select_related(
            "aircraft__aircraft_type",
            "aircraft__base_airport",
            "departure_airport",
            "arrival_airport",
            "diversion_airport",
        )
    )
    stored_blocks = list(MaintenanceBlock.objects.select_related("aircraft"))
    violations = validate_schedule(
        [*stored_flights, *all_flights],
        [*stored_blocks, *all_blocks],
    )
    if violations:
        raise ScheduleGenerationError(violations)
    Flight.objects.bulk_create(all_flights, batch_size=250)
    MaintenanceBlock.objects.bulk_create(all_blocks, batch_size=100)
    clock_arguments = {
        "seed": config.seed,
        "schedule_anchor": anchor,
        "wall_time": timezone.now(),
    }
    if config.clear:
        reset_simulation_clock(**clock_arguments)
    else:
        initialize_simulation_clock(**clock_arguments)

    report = GenerationReport(
        seed=config.seed,
        anchor_time=anchor,
        airports_created=airport_created,
        aircraft_types_created=type_created,
        aircraft_created=len(fleet),
        violation_totals=violation_counts(violations),
    )
    _populate_report(report, all_flights, all_blocks)
    return report

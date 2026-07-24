"""Deterministic aircraft-itinerary generation and atomic persistence."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from math import ceil
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from tracker.models import Aircraft, AircraftType, Airport, CrewMember, Flight, FlightCrew, MaintenanceBlock

from .clock import initialize_simulation_clock, reset_simulation_clock
from .distance import calculate_duration, haversine_distance_km, practical_range_km
from .fixtures import load_reference_data
from .status import get_flight_status
from .validation import ScheduleViolation, validate_schedule, violation_counts

# Mock crew data pool for generation
MOCK_FIRST_NAMES = [
    "James", "Sarah", "Michael", "Emily", "David", "Jessica",
    "Robert", "Amanda", "Daniel", "Stephanie", "John", "Rebecca",
    "William", "Nicole", "Christopher", "Lauren", "Matthew", "Megan",
    "Andrew", "Rachel", "Mark", "Ashley", "Steven", "Samantha",
    "Brian", "Katie", "Jason", "Laura", "Kevin", "Elizabeth",
]
MOCK_LAST_NAMES = [
    "Smith", "Johnson", "Brown", "Davis", "Wilson", "Clark",
    "Lewis", "Hall", "Young", "King", "Wright", "Scott",
    "Green", "Baker", "Adams", "Nelson", "Hill", "Campbell",
    "Mitchell", "Roberts", "Carter", "Perez", "Robinson", "Turner",
    "Phillips", "Parker", "Evans", "Edwards", "Collins", "Stewart",
]
PILOT_NAMES = MOCK_FIRST_NAMES[:10] + MOCK_LAST_NAMES[:10]  # First 10 of each
FA_NAMES = MOCK_FIRST_NAMES[10:] + MOCK_LAST_NAMES[10:]  # Remaining


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

def _generate_crew_svgs(output_dir: Path) -> None:
    from django.conf import settings
    crew_dir = settings.BASE_DIR / "tracker" / "static" / "tracker" / "images" / "crew"
    crew_dir.mkdir(parents=True, exist_ok=True)

    # 5 Better-aligned minimalist vector hairstyles
    hair_paths = [
        # 1. Short/Parted
        '<path d="M 33 42 C 30 25, 45 15, 60 22 C 67 25, 68 35, 66 42 C 63 32, 55 25, 45 28 C 38 30, 35 38, 33 42 Z" fill="#10202e" stroke="#53c7ed" stroke-width="1.5" stroke-linejoin="round"/>',
        # 2. Bob cut
        '<path d="M 35 30 C 35 15, 65 15, 65 30 L 68 55 C 60 58, 55 50, 50 45 C 45 50, 40 58, 32 55 Z" fill="#10202e" stroke="#53c7ed" stroke-width="1.5" stroke-linejoin="round"/>',
        # 3. Spiky/Textured
        '<path d="M 33 40 L 35 25 L 42 30 L 50 18 L 56 28 L 65 22 L 67 40 C 60 30, 40 30, 33 40 Z" fill="#10202e" stroke="#53c7ed" stroke-width="1.5" stroke-linejoin="round"/>',
        # 4. Top Bun
        '<path d="M 35 35 C 35 15, 65 15, 65 35 C 60 25, 40 25, 35 35 Z" fill="#10202e" stroke="#53c7ed" stroke-width="1.5"/><circle cx="50" cy="18" r="8" fill="#10202e" stroke="#53c7ed" stroke-width="1.5"/>',
        # 5. Clean Fade (Just a hairline accent)
        '<path d="M 33 42 C 35 20, 65 20, 67 42" fill="none" stroke="#53c7ed" stroke-width="1.5" stroke-linecap="round"/>',
    ]

    for i in range(20):
        is_pilot = i < 10
        hair = hair_paths[i % len(hair_paths)]
        has_glasses = (i % 3) == 0
        
        svg = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">',
            # Background circle
            '<circle cx="50" cy="50" r="48" fill="#071019" stroke="#53c7ed" stroke-width="2"/>',
            # Shoulders / Torso
            '<path d="M 20 100 C 20 65, 35 60, 50 60 C 65 60, 80 65, 80 100 Z" fill="#10202e" stroke="#53c7ed" stroke-width="1.5"/>',
        ]
        
        # Attire Overlay
        if is_pilot:
            # White collar shirt V-neck and Tie
            svg.append('<path d="M 50 78 L 40 60 L 45 60 L 50 68 L 55 60 L 60 60 Z" fill="#dce9f1" stroke="#53c7ed" stroke-width="1"/>')
            svg.append('<path d="M 48 68 L 52 68 L 54 85 L 50 92 L 46 85 Z" fill="#10202e" stroke="#53c7ed" stroke-width="1"/>')
        else:
            # Flight Attendant Scarf
            svg.append('<path d="M 43 60 C 43 75, 57 75, 57 60 Z" fill="#dce9f1" stroke="#53c7ed" stroke-width="1"/>')
            svg.append('<path d="M 50 68 C 55 75, 58 85, 55 90 C 50 85, 48 75, 50 68 Z" fill="#10202e" stroke="#53c7ed" stroke-width="1"/>')

        # Neck & Head
        svg.append('<path d="M 45 62 L 45 50 L 55 50 L 55 62 Z" fill="#10202e" stroke="#53c7ed" stroke-width="1.5"/>')
        svg.append('<circle cx="50" cy="40" r="15" fill="#10202e" stroke="#53c7ed" stroke-width="1.5"/>')
        
        # Hair
        svg.append(hair)
        
        # Eyewear (Sleek half-rim glasses)
        if has_glasses:
            svg.append('<path d="M 32 38 L 40 38 Q 44 42 48 38 L 52 38 Q 56 42 60 38 L 68 38" fill="none" stroke="#53c7ed" stroke-width="1.5" stroke-linecap="round"/>')
            svg.append('<path d="M 34 38 A 6 6 0 0 0 46 38" fill="none" stroke="#53c7ed" stroke-width="1.5"/>')
            svg.append('<path d="M 54 38 A 6 6 0 0 0 66 38" fill="none" stroke="#53c7ed" stroke-width="1.5"/>')
            
        svg.append('</svg>')
        
        file_path = crew_dir / f"crew_{i+1:02d}.svg"
        file_path.write_text("\n".join(svg), encoding="utf-8")

def _clear_simulation_data() -> None:
    FlightCrew.objects.all().delete()
    CrewMember.objects.all().delete()
    MaintenanceBlock.objects.all().delete()
    Flight.objects.all().delete()
    Aircraft.objects.all().delete()
    AircraftType.objects.all().delete()
    Airport.objects.all().delete()


def _get_mock_profile_path(index: int) -> str:
    """Return a generic profile image path for mock crew members."""
    return "crew/profiles/default_crew_" + str(index + 1).zfill(2) + ".png"


def _create_crew(count: int = 20, seed: int = 42) -> list[CrewMember]:
    rng = random.Random(seed)
    crew_members: list[CrewMember] = []
    
    _generate_crew_svgs(Path("."))
    
    all_names = list(zip(MOCK_FIRST_NAMES * 2, MOCK_LAST_NAMES * 2))
    rng.shuffle(all_names)
    
    for i in range(count):
        first_name, last_name = all_names[i % len(all_names)]
        role = CrewMember.Role.PILOT if i < 10 else CrewMember.Role.FLIGHT_ATTENDANT
        
        crew_member = CrewMember(
            first_name=first_name,
            last_name=last_name,
            role=role,
            profile_picture=f"tracker/images/crew/crew_{i+1:02d}.svg",
        )
        crew_member.full_clean()
        crew_members.append(crew_member)
    
    CrewMember.objects.bulk_create(crew_members)
    return list(CrewMember.objects.all().order_by("pk"))

class CrewAssignmentError(RuntimeError):
    """Raised when crew cannot be assigned without violating rules."""
    def __init__(self, message: str):
        super().__init__(message)


@dataclass
class _CrewMemberState:
    """Tracks the scheduling state of a crew member for validation."""
    last_flight_effective_arrival: datetime | None = None
    last_flight_arrival_airport: Airport | None = None


def _can_assign_crew_to_flight(
    crew_member: CrewMember,
    flight: Flight,
    crew_states: dict[int, _CrewMemberState],
    all_flights_for_validation: list[Flight],
) -> tuple[bool, str]:
    """Check if a crew member can be assigned to a flight without violating rules.
    
    Returns:
        (can_assign, reason_if_not)
    """
    anchor = flight.scheduled_departure
    
    # Get existing FlightCrew records for this crew member (excluding current flight if updating)
    existing_assignments = FlightCrew.objects.filter(
        crew_member=crew_member
    ).select_related("flight")
    
    # Build temporary list including the flight we're trying to assign
    test_flights = list(all_flights_for_validation)
    test_flight = Flight.objects.get(pk=flight.pk)  # Get fresh copy
    crew_states_copy = dict(crew_states)
    test_state = _CrewMemberState(
        last_flight_effective_arrival=crew_states.get(crew_member.pk, _CrewMemberState()).last_flight_effective_arrival,
        last_flight_arrival_airport=crew_states.get(crew_member.pk, _CrewMemberState()).last_flight_arrival_airport,
    )
    
    # Check against existing FlightCrew assignments
    for fc in existing_assignments:
        other_flight = fc.flight
        if other_flight.pk == flight.pk:
            continue
            
        other_eff_dep = other_flight.estimated_departure or other_flight.scheduled_departure
        other_eff_arr = other_flight.estimated_arrival or other_flight.scheduled_arrival
        
        # Rule 1: No double-booking (overlap check)
        if not (anchor >= other_eff_arr or other_eff_dep >= flight.estimated_arrival or other_eff_arr):
            return False, "Double-booking: schedule overlap with another flight"
    
    # Rule 2: 8-hour rest rule
    if test_state.last_flight_effective_arrival:
        rest_period = anchor - test_state.last_flight_effective_arrival
        if rest_period < timedelta(hours=8):
            return False, f"Insufficient rest: only {rest_period.total_seconds()/3600:.1f} hours since last arrival"
    
    # Rule 3: Geographic continuity
    if test_state.last_flight_arrival_airport:
        if flight.departure_airport.pk != test_state.last_flight_arrival_airport.pk:
            return False, f"Geographic violation: last landed at {test_state.last_flight_arrival_airport}, but next departs from {flight.departure_airport}"
    
    return True, ""


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


def _assign_crew_to_flights(
    flights: list[Flight],
    crew: list[CrewMember],
    rng: random.Random,
    config: GenerationConfig,
) -> None:
    """Assign crew members to flights respecting validation rules.
    
    This function assigns pilots and flight attendants to non-cancelled flights,
    ensuring:
    - No double-booking (crew can't overlap on flights)
    - 8-hour minimum rest between flights
    - Geographic continuity (crew must depart from where they arrived)
    
    Each flight gets at least 2 pilots and 2 flight attendants (based on flight type).
    """
    if not crew:
        return
    
    pilots = [c for c in crew if c.role == CrewMember.Role.PILOT]
    flight_attendants = [c for c in crew if c.role == CrewMember.Role.FLIGHT_ATTENDANT]
    
    # Filter to non-cancelled flights and sort by departure time
    operable_flights = [f for f in flights if f.status != Flight.Status.CANCELLED]
    operable_flights.sort(key=lambda f: (f.scheduled_departure, f.departure_airport.pk))
    
    # Track state for each crew member
    crew_states: dict[int, _CrewMemberState] = {}
    
    for flight in operable_flights:
        eff_departure = flight.estimated_departure or flight.scheduled_departure
        eff_arrival = flight.estimated_arrival or flight.scheduled_arrival
        
        # Determine crew needs based on flight type
        needs_pilots = 2
        needs_fas = 2 if flight.flight_type == Flight.FlightType.PASSENGER else 1
        
        # Track which crew are assigned to this flight for state updates
        assigned_this_flight: list[int] = []
        
        def can_use_crew(crew_member: CrewMember) -> bool:
            """Check if crew member can fly this flight."""
            state = crew_states.get(crew_member.pk)
            if not state:
                state = _CrewMemberState()
            
            # Check 8-hour rest rule
            if state.last_flight_effective_arrival:
                rest_needed = eff_departure - state.last_flight_effective_arrival
                if rest_needed < timedelta(hours=8):
                    return False
            
            # Check geographic continuity
            if state.last_flight_arrival_airport:
                if flight.departure_airport.pk != state.last_flight_arrival_airport.pk:
                    # Allow if this is one of the first few flights for the crew member
                    # (they might be starting their schedule)
                    if state.last_flight_effective_arrival:
                        return False
            
            # Check no overlapping assignments
            for fc in FlightCrew.objects.filter(crew_member=crew_member).select_related("flight"):
                other = fc.flight
                if other.pk == flight.pk:
                    continue
                other_eff_dep = other.estimated_departure or other.scheduled_departure
                other_eff_arr = other.estimated_arrival or other.scheduled_arrival
                # Check overlap
                if not (eff_departure >= other_eff_arr or other_eff_dep >= eff_arrival):
                    return False
            
            return True
        
        def assign_crew_member(crew_member: CrewMember) -> None:
            """Assign crew member to flight and update state."""
            fc = FlightCrew(
                crew_member=crew_member,
                flight=flight,
            )
            fc.full_clean()
            fc.save()
            
            if crew_member.pk not in crew_states:
                crew_states[crew_member.pk] = _CrewMemberState()
            crew_states[crew_member.pk].last_flight_effective_arrival = eff_arrival
            crew_states[crew_member.pk].last_flight_arrival_airport = (
                flight.diversion_airport or flight.arrival_airport
            )
            assigned_this_flight.append(crew_member.pk)
        
        # Assign pilots
        pilots_assigned = 0
        available_pilots = list(pilots)
        rng.shuffle(available_pilots)
        
        for pilot in available_pilots:
            if pilots_assigned >= needs_pilots:
                break
            if can_use_crew(pilot):
                assign_crew_member(pilot)
                pilots_assigned += 1
        
        # Assign flight attendants
        fass_assigned = 0
        available_fas = list(flight_attendants)
        rng.shuffle(available_fas)
        
        for fa in available_fas:
            if fass_assigned >= needs_fas:
                break
            if can_use_crew(fa):
                assign_crew_member(fa)
                fass_assigned += 1
    for crew_member in crew:
            assigned = list(FlightCrew.objects.filter(crew_member=crew_member).select_related("flight").order_by("flight__scheduled_departure"))
            for i in range(len(assigned) - 1):
                f1 = assigned[i].flight
                f2 = assigned[i+1].flight
                
                arr1 = f1.actual_arrival or f1.estimated_arrival or f1.scheduled_arrival
                dep2 = f2.estimated_departure or f2.scheduled_departure
                
                land_ap1 = f1.diversion_airport_id or f1.arrival_airport_id
                dep_ap2 = f2.departure_airport_id

                assert dep2 >= arr1 + timedelta(hours=8), (
                    f"Rest violation for {crew_member.full_name()}: {f2.flight_number} departs "
                    f"less than 8h after {f1.flight_number} arrival."
                )
                assert dep_ap2 == land_ap1, (
                    f"Geographic continuity violation for {crew_member.full_name()}: "
                    f"{f1.flight_number} landed at {land_ap1}, but {f2.flight_number} departs from {dep_ap2}."
                )

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

    # Create crew members
    crew = _create_crew(count=20, seed=config.seed + 1000)
    
    # Load existing database records
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
    
    # Bulk create flights first (so they have PKs for crew assignment)
    Flight.objects.bulk_create(all_flights, batch_size=250)
    MaintenanceBlock.objects.bulk_create(all_blocks, batch_size=100)
    
    # Reload flights from DB to get PKs
    all_flights = list(Flight.objects.filter(
        aircraft__in=[a.pk for a in fleet]
    ).select_related(
        "aircraft__aircraft_type",
        "departure_airport",
        "arrival_airport",
        "diversion_airport",
    ))
    
    # Assign crew to flights after they have PKs
    _assign_crew_to_flights(all_flights, crew, rng, config)
    
    # Validate entire schedule
    violations = validate_schedule(
        [*stored_flights, *all_flights],
        [*stored_blocks, *all_blocks],
    )
    if violations:
        raise ScheduleGenerationError(violations)
    
    # Initialize/reset simulation clock
    clock_arguments = {
        "seed": config.seed,
        "schedule_anchor": anchor,
        "wall_time": timezone.now(),
    }
    if config.clear:
        reset_simulation_clock(**clock_arguments)
    else:
        initialize_simulation_clock(**clock_arguments)

    # Build report
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

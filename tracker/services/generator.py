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

from tracker.models import (
    Aircraft,
    AircraftType,
    Airport,
    CrewMember,
    Flight,
    FlightCrew,
    MaintenanceBlock,
)

from .clock import initialize_simulation_clock, reset_simulation_clock
from .distance import calculate_duration, haversine_distance_km, practical_range_km
from .fixtures import load_reference_data
from .status import get_flight_status
from .validation import ScheduleViolation, validate_schedule, violation_counts


@dataclass(frozen=True)
class _CrewIdentity:
    first_name: str
    last_name: str
    gender: str


@dataclass(frozen=True)
class _CrewProfile:
    identity: _CrewIdentity
    role: str
    slot: int


MOCK_CREW_IDENTITIES = (
    _CrewIdentity("James", "Smith", "male"),
    _CrewIdentity("Sarah", "Johnson", "female"),
    _CrewIdentity("Michael", "Brown", "male"),
    _CrewIdentity("Emily", "Davis", "female"),
    _CrewIdentity("David", "Wilson", "male"),
    _CrewIdentity("Jessica", "Clark", "female"),
    _CrewIdentity("Robert", "Lewis", "male"),
    _CrewIdentity("Amanda", "Hall", "female"),
    _CrewIdentity("Daniel", "Young", "male"),
    _CrewIdentity("Stephanie", "King", "female"),
    _CrewIdentity("John", "Wright", "male"),
    _CrewIdentity("Rebecca", "Scott", "female"),
    _CrewIdentity("William", "Green", "male"),
    _CrewIdentity("Nicole", "Baker", "female"),
    _CrewIdentity("Christopher", "Adams", "male"),
    _CrewIdentity("Lauren", "Nelson", "female"),
    _CrewIdentity("Matthew", "Hill", "male"),
    _CrewIdentity("Megan", "Campbell", "female"),
    _CrewIdentity("Andrew", "Mitchell", "male"),
    _CrewIdentity("Rachel", "Roberts", "female"),
    _CrewIdentity("Mark", "Carter", "male"),
    _CrewIdentity("Ashley", "Perez", "female"),
    _CrewIdentity("Steven", "Robinson", "male"),
    _CrewIdentity("Samantha", "Turner", "female"),
    _CrewIdentity("Brian", "Phillips", "male"),
    _CrewIdentity("Katie", "Parker", "female"),
    _CrewIdentity("Jason", "Evans", "male"),
    _CrewIdentity("Laura", "Edwards", "female"),
    _CrewIdentity("Kevin", "Collins", "male"),
    _CrewIdentity("Elizabeth", "Stewart", "female"),
)

_SKIN_TONES = (
    ("#F0C8A8", "#C89170"),
    ("#D9A17C", "#A96B50"),
    ("#B97858", "#87503D"),
    ("#8B5944", "#613A2E"),
    ("#654033", "#432820"),
)
_HAIR_COLORS = ("#12171B", "#2A201C", "#51362B", "#784631", "#8B735F")
_ACCENTS = ("#53C7ED", "#FFBF47", "#57D99B", "#FF6B63")
_HEAD_SHAPES = ("round", "oval", "angular")
_GLASSES = ("none", "none", "round", "square")

_MALE_HAIR = (
    (
        "side-part",
        "",
        '<path d="M34 43 Q34 24 49 20 Q64 16 69 27 Q75 30 67 43 Q60 32 49 31 Q40 33 34 43Z"/>'
        '<path d="M50 21 Q47 30 38 35" fill="none" stroke="{accent}" stroke-width="1.1"/>',
    ),
    (
        "crew-cut",
        "",
        '<path d="M34 42 Q35 24 50 22 Q66 21 68 42 Q60 33 50 33 Q41 33 34 42Z"/>',
    ),
    (
        "textured",
        "",
        '<path d="M34 42 L35 27 L42 31 L49 19 L55 28 L65 22 L68 42 Q60 32 50 33 Q41 32 34 42Z"/>',
    ),
    (
        "fade",
        "",
        '<path d="M34 43 Q35 25 50 22 Q65 22 68 41 Q58 32 48 33 Q40 34 34 43Z"/>'
        '<path d="M35 34 L35 48" fill="none" stroke="{accent}" stroke-width="1.2"/>',
    ),
    (
        "wave",
        "",
        '<path d="M33 43 Q33 29 42 25 Q48 16 56 24 Q66 24 69 41 Q60 31 50 34 Q42 31 33 43Z"/>',
    ),
    (
        "close-crop",
        "",
        '<path d="M34 42 Q36 27 50 26 Q65 27 68 42" fill="none" stroke-width="4" stroke-linecap="round"/>',
    ),
    (
        "coils",
        "",
        '<g><circle cx="36" cy="35" r="6"/><circle cx="41" cy="27" r="7"/><circle cx="50" cy="24" r="7"/><circle cx="59" cy="26" r="7"/><circle cx="66" cy="34" r="6"/></g>',
    ),
    (
        "shaved",
        "",
        '<path d="M34 42 Q37 27 50 26 Q64 27 68 42" fill="none" stroke-width="2" opacity=".65"/>',
    ),
)

_FEMALE_HAIR = (
    (
        "bob",
        '<path d="M33 35 Q34 18 50 18 Q68 19 68 38 L70 62 Q63 68 58 59 L61 38 Q51 27 41 37 L42 61 Q35 68 30 61Z"/>',
        '<path d="M34 40 Q36 21 50 21 Q64 22 68 39 Q58 30 49 34 Q40 31 34 40Z"/>',
    ),
    (
        "top-bun",
        '<circle cx="53" cy="14" r="8"/><path d="M34 40 Q34 20 50 19 Q67 20 68 41 L62 57 L60 37 Q50 28 40 37 L38 57Z"/>',
        '<path d="M35 40 Q37 22 51 21 Q65 23 67 40 Q58 31 49 34 Q42 31 35 40Z"/>',
    ),
    (
        "long-layer",
        '<path d="M33 37 Q32 17 50 17 Q70 19 69 41 L73 76 Q65 83 59 72 L61 40 Q52 27 41 37 L40 74 Q33 82 27 75Z"/>',
        '<path d="M34 40 Q36 21 51 20 Q66 22 68 40 Q59 30 49 35 Q42 30 34 40Z"/>',
    ),
    (
        "ponytail",
        '<path d="M63 29 Q79 34 73 59 Q69 70 63 60 Q69 44 59 36Z"/><path d="M34 40 Q34 20 50 19 Q67 21 68 41 L62 57 L60 37 Q50 28 40 37 L38 57Z"/>',
        '<path d="M35 40 Q37 22 51 21 Q65 23 67 40 Q58 31 49 34 Q42 31 35 40Z"/>',
    ),
    (
        "pixie",
        "",
        '<path d="M33 43 L35 28 L41 32 L48 20 L53 29 L61 23 L66 31 L69 29 L68 43 Q59 33 49 34 Q41 33 33 43Z"/>',
    ),
    (
        "side-braid",
        '<path d="M34 40 Q33 20 50 19 Q68 21 68 42 L62 57 L60 37 Q50 28 40 37 L38 58Z"/><path d="M66 48 Q76 53 67 62 Q76 68 66 76 Q73 82 64 89" fill="none" stroke-width="7" stroke-linecap="round"/>',
        '<path d="M35 40 Q37 22 51 21 Q65 23 67 40 Q58 31 49 34 Q42 31 35 40Z"/>',
    ),
    (
        "shoulder-wave",
        '<path d="M32 40 Q31 18 50 18 Q70 20 69 43 L71 72 Q65 79 59 69 L61 40 Q51 28 41 38 L40 70 Q33 78 27 70Z"/>',
        '<path d="M34 40 Q36 21 50 20 Q66 22 68 40 Q59 30 50 34 Q41 31 34 40Z"/>',
    ),
    (
        "low-bun",
        '<circle cx="68" cy="48" r="8"/><path d="M34 40 Q34 20 50 19 Q67 21 68 41 L62 57 L60 37 Q50 28 40 37 L38 57Z"/>',
        '<path d="M35 40 Q37 22 51 21 Q65 23 67 40 Q58 31 49 34 Q42 31 35 40Z"/>',
    ),
)


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


@dataclass(frozen=True)
class _PortraitTraits:
    skin: str
    skin_shadow: str
    hair_color: str
    hair_name: str
    hair_back: str
    hair_front: str
    accent: str
    head_shape: str
    glasses: str
    beard: bool
    earrings: bool
    heading: int


def _head_markup(shape: str, skin: str, shadow: str) -> str:
    shapes = {
        "round": '<circle cx="50" cy="42" r="16"/>',
        "oval": '<ellipse cx="50" cy="42" rx="14.5" ry="18"/>',
        "angular": '<path d="M36 31 Q39 24 50 24 Q61 24 65 31 L64 49 Q60 60 50 62 Q40 60 36 49Z"/>',
    }
    return (
        f'<g fill="{skin}" stroke="{shadow}" stroke-width="1.2">{shapes[shape]}</g>'
        f'<path d="M61 31 Q66 40 61 52 Q58 58 52 61 Q63 58 65 48 L65 34Z" '
        f'fill="{shadow}" opacity=".2"/>'
    )


def _glasses_markup(style: str, accent: str) -> str:
    if style == "none":
        return ""
    frames = {
        "round": '<circle cx="43" cy="42" r="6.5"/><circle cx="57" cy="42" r="6.5"/>',
        "square": '<rect x="36" y="36" width="13" height="11" rx="2"/><rect x="51" y="36" width="13" height="11" rx="2"/>',
    }[style]
    return (
        f'<g fill="#071019" fill-opacity=".08" stroke="{accent}" stroke-width="1.2">'
        f'{frames}<path d="M49 40 H51 M36 39 L33 37 M64 39 L67 37" fill="none"/></g>'
    )


def _uniform_markup(role: str, accent: str) -> str:
    torso = (
        f'<path d="M18 100 Q19 69 42 63 L50 70 L58 63 Q81 69 82 100Z" '
        f'fill="#10202E" stroke="{accent}" stroke-width="1.4"/>'
    )
    if role == CrewMember.Role.PILOT:
        return torso + (
            '<path d="M41 64 L50 70 L59 64 L56 91 L44 91Z" fill="#DCE9F1"/>'
            f'<path d="M48 71 H52 L54 87 L50 92 L46 87Z" fill="{accent}"/>'
            '<path d="M24 72 L39 68 M61 68 L76 72" stroke="#FFBF47" stroke-width="2.2"/>'
        )
    return torso + (
        '<path d="M42 64 L50 70 L58 64 L56 88 L44 88Z" fill="#DCE9F1"/>'
        f'<path d="M42 69 Q50 77 58 69 L56 79 Q50 75 44 80Z" fill="{accent}"/>'
        f'<path d="M50 76 Q60 82 57 94 Q51 89 48 80Z" fill="{accent}" opacity=".86"/>'
    )


def _render_crew_svg(profile: _CrewProfile, traits: _PortraitTraits) -> str:
    identity = profile.identity
    hair_back = traits.hair_back.format(hair=traits.hair_color, accent=traits.accent)
    hair_front = traits.hair_front.format(hair=traits.hair_color, accent=traits.accent)
    beard = ""
    if traits.beard:
        beard = (
            f'<path d="M36 45 Q38 61 50 65 Q62 61 64 45 Q59 56 50 58 Q41 56 36 45Z" '
            f'fill="{traits.hair_color}" opacity=".72"/>'
        )
    earrings = ""
    if traits.earrings:
        earrings = (
            f'<g fill="{traits.accent}"><circle cx="35" cy="50" r="1.7"/>'
            '<circle cx="65" cy="50" r="1.7"/></g>'
        )
    return "\n".join(
        [
            (
                '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" '
                f'viewBox="0 0 100 100" role="img" data-name="{identity.first_name} '
                f'{identity.last_name}" data-gender="{identity.gender}" data-role="{profile.role}" '
                f'data-hair="{traits.hair_name}" data-slot="{profile.slot}" '
                'data-style="faceless" data-facial-features="none">'
            ),
            f"<title>{identity.first_name} {identity.last_name} crew profile</title>",
            '<circle cx="50" cy="50" r="48" fill="#071019" stroke="#315166" stroke-width="2"/>',
            f'<circle cx="50" cy="47" r="39" fill="none" stroke="{traits.accent}" stroke-width=".8" opacity=".48"/>',
            '<path d="M11 47 H89 M50 8 V86" stroke="#315166" stroke-width=".65" opacity=".52"/>',
            f'<g transform="rotate({traits.heading} 50 47)"><path d="M50 7 L47 13 H53Z" fill="{traits.accent}"/></g>',
            _uniform_markup(profile.role, traits.accent),
            f'<g fill="{traits.hair_color}" stroke="{traits.hair_color}" stroke-width="1.2" stroke-linejoin="round">{hair_back}</g>',
            f'<path d="M44 65 V54 H56 V65" fill="{traits.skin}" stroke="{traits.skin_shadow}" stroke-width="1.2"/>',
            _head_markup(traits.head_shape, traits.skin, traits.skin_shadow),
            beard,
            f'<g fill="{traits.hair_color}" stroke="{traits.hair_color}" stroke-width="1.2" stroke-linejoin="round">{hair_front}</g>',
            _glasses_markup(traits.glasses, traits.accent),
            earrings,
            f'<path d="M12 86 V91 H17 M83 91 H88 V86" fill="none" stroke="{traits.accent}" stroke-width="1.2"/>',
            "</svg>",
            "",
        ]
    )


def _generate_crew_svgs(
    profiles: list[_CrewProfile],
    output_dir: Path,
    seed: int,
) -> None:
    """Generate faceless, gender-aligned vector portraits during schedule creation."""
    rng = random.Random(f"northstar-crew-portraits:{seed}")
    output_dir.mkdir(parents=True, exist_ok=True)
    used_signatures = set()
    expected_files = set()

    for profile in profiles:
        hair_options = _MALE_HAIR if profile.identity.gender == "male" else _FEMALE_HAIR
        while True:
            hair_name, hair_back, hair_front = rng.choice(hair_options)
            skin_index = rng.randrange(len(_SKIN_TONES))
            hair_color_index = rng.randrange(len(_HAIR_COLORS))
            head_shape = rng.choice(_HEAD_SHAPES)
            glasses = rng.choice(_GLASSES)
            beard = profile.identity.gender == "male" and rng.random() < 0.42
            earrings = profile.identity.gender == "female" and rng.random() < 0.46
            signature = (
                profile.identity.gender,
                hair_name,
                skin_index,
                hair_color_index,
                head_shape,
                glasses,
                beard,
                earrings,
            )
            if signature not in used_signatures:
                used_signatures.add(signature)
                break

        skin, skin_shadow = _SKIN_TONES[skin_index]
        traits = _PortraitTraits(
            skin=skin,
            skin_shadow=skin_shadow,
            hair_color=_HAIR_COLORS[hair_color_index],
            hair_name=hair_name,
            hair_back=hair_back,
            hair_front=hair_front,
            accent=rng.choice(_ACCENTS),
            head_shape=head_shape,
            glasses=glasses,
            beard=beard,
            earrings=earrings,
            heading=(profile.slot * 19 + rng.randrange(19)) % 360,
        )
        file_name = f"crew_{profile.slot:02d}.svg"
        (output_dir / file_name).write_text(
            _render_crew_svg(profile, traits),
            encoding="utf-8",
        )
        expected_files.add(file_name)

    for stale_file in output_dir.glob("crew_*.svg"):
        if stale_file.name not in expected_files:
            stale_file.unlink()


def _clear_simulation_data() -> None:
    FlightCrew.objects.all().delete()
    CrewMember.objects.all().delete()
    MaintenanceBlock.objects.all().delete()
    Flight.objects.all().delete()
    Aircraft.objects.all().delete()
    AircraftType.objects.all().delete()
    Airport.objects.all().delete()


def _crew_profiles(count: int, seed: int) -> list[_CrewProfile]:
    """Select a unique, gender-labelled roster for deterministic SVG generation."""
    if not 0 <= count <= len(MOCK_CREW_IDENTITIES):
        raise ValueError(f"crew count must be between 0 and {len(MOCK_CREW_IDENTITIES)}")

    rng = random.Random(seed)
    identities = list(MOCK_CREW_IDENTITIES)
    rng.shuffle(identities)
    return [
        _CrewProfile(
            identity=identity,
            role=(
                CrewMember.Role.PILOT
                if index < min(10, count)
                else CrewMember.Role.FLIGHT_ATTENDANT
            ),
            slot=index + 1,
        )
        for index, identity in enumerate(identities[:count])
    ]


def _create_crew(
    count: int = 20,
    seed: int = 42,
    output_dir: Path | None = None,
) -> list[CrewMember]:
    """Create unique crew identities and generate their SVG portraits at runtime."""
    crew_members: list[CrewMember] = []
    profiles = _crew_profiles(count, seed)

    if output_dir is None:
        from django.conf import settings

        output_dir = settings.BASE_DIR / "tracker" / "static" / "tracker" / "images" / "crew"
    _generate_crew_svgs(profiles, output_dir, seed)

    for profile in profiles:
        crew_member = CrewMember(
            first_name=profile.identity.first_name,
            last_name=profile.identity.last_name,
            role=profile.role,
            profile_picture=f"tracker/images/crew/crew_{profile.slot:02d}.svg",
        )
        crew_member.full_clean()
        crew_members.append(crew_member)

    CrewMember.objects.bulk_create(crew_members)
    return crew_members


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
    _all_flights_for_validation: list[Flight],
) -> tuple[bool, str]:
    """Check if a crew member can be assigned to a flight without violating rules.

    Returns:
        (can_assign, reason_if_not)
    """
    effective_departure = flight.estimated_departure or flight.scheduled_departure
    effective_arrival = flight.estimated_arrival or flight.scheduled_arrival

    # Get existing FlightCrew records for this crew member (excluding current flight if updating)
    existing_assignments = FlightCrew.objects.filter(crew_member=crew_member).select_related(
        "flight"
    )

    test_state = _CrewMemberState(
        last_flight_effective_arrival=crew_states.get(
            crew_member.pk, _CrewMemberState()
        ).last_flight_effective_arrival,
        last_flight_arrival_airport=crew_states.get(
            crew_member.pk, _CrewMemberState()
        ).last_flight_arrival_airport,
    )

    # Check against existing FlightCrew assignments
    for fc in existing_assignments:
        other_flight = fc.flight
        if other_flight.pk == flight.pk:
            continue

        other_eff_dep = other_flight.estimated_departure or other_flight.scheduled_departure
        other_eff_arr = other_flight.estimated_arrival or other_flight.scheduled_arrival

        # Rule 1: No double-booking (overlap check)
        if not (effective_departure >= other_eff_arr or other_eff_dep >= effective_arrival):
            return False, "Double-booking: schedule overlap with another flight"

    # Rule 2: 8-hour rest rule
    if test_state.last_flight_effective_arrival:
        rest_period = effective_departure - test_state.last_flight_effective_arrival
        if rest_period < timedelta(hours=8):
            return (
                False,
                f"Insufficient rest: only {rest_period.total_seconds() / 3600:.1f} hours since last arrival",
            )

    # Rule 3: Geographic continuity
    if test_state.last_flight_arrival_airport:
        if flight.departure_airport.pk != test_state.last_flight_arrival_airport.pk:
            return (
                False,
                f"Geographic violation: last landed at {test_state.last_flight_arrival_airport}, but next departs from {flight.departure_airport}",
            )

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

        def can_use_crew(
            crew_member: CrewMember,
            current_flight: Flight = flight,
            current_departure: datetime = eff_departure,
            current_arrival: datetime = eff_arrival,
        ) -> bool:
            """Check if crew member can fly this flight."""
            state = crew_states.get(crew_member.pk)
            if not state:
                state = _CrewMemberState()

            # Check 8-hour rest rule
            if state.last_flight_effective_arrival:
                rest_needed = current_departure - state.last_flight_effective_arrival
                if rest_needed < timedelta(hours=8):
                    return False

            # Check geographic continuity
            if state.last_flight_arrival_airport:
                if current_flight.departure_airport.pk != state.last_flight_arrival_airport.pk:
                    # Allow if this is one of the first few flights for the crew member
                    # (they might be starting their schedule)
                    if state.last_flight_effective_arrival:
                        return False

            # Check no overlapping assignments
            for fc in FlightCrew.objects.filter(crew_member=crew_member).select_related("flight"):
                other = fc.flight
                if other.pk == current_flight.pk:
                    continue
                other_eff_dep = other.estimated_departure or other.scheduled_departure
                other_eff_arr = other.estimated_arrival or other.scheduled_arrival
                # Check overlap
                if not (current_departure >= other_eff_arr or other_eff_dep >= current_arrival):
                    return False

            return True

        def assign_crew_member(
            crew_member: CrewMember,
            current_flight: Flight = flight,
            current_arrival: datetime = eff_arrival,
            assigned_ids: list[int] = assigned_this_flight,
        ) -> None:
            """Assign crew member to flight and update state."""
            fc = FlightCrew(
                crew_member=crew_member,
                flight=current_flight,
            )
            fc.full_clean()
            fc.save()

            if crew_member.pk not in crew_states:
                crew_states[crew_member.pk] = _CrewMemberState()
            crew_states[crew_member.pk].last_flight_effective_arrival = current_arrival
            crew_states[crew_member.pk].last_flight_arrival_airport = (
                current_flight.diversion_airport or current_flight.arrival_airport
            )
            assigned_ids.append(crew_member.pk)

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
        assigned = list(
            FlightCrew.objects.filter(crew_member=crew_member)
            .select_related("flight")
            .order_by("flight__scheduled_departure")
        )
        for i in range(len(assigned) - 1):
            f1 = assigned[i].flight
            f2 = assigned[i + 1].flight

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
    all_flights = list(
        Flight.objects.filter(aircraft__in=[a.pk for a in fleet]).select_related(
            "aircraft__aircraft_type",
            "departure_airport",
            "arrival_airport",
            "diversion_airport",
        )
    )

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

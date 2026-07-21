"""Persistent, server-authoritative simulation clock operations."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from tracker.models import SimulationClock

SIMULATION_CLOCK_PK = 1
MAX_SPEED_MULTIPLIER = Decimal("1000.00")


class ClockConfigurationError(RuntimeError):
    """Raised when persisted clock data cannot produce a safe simulation time."""


class ClockNotConfiguredError(ClockConfigurationError):
    """Raised when a clock mutation is requested before schedule generation."""


def _aware(value: datetime | None, label: str) -> datetime:
    if value is None or timezone.is_naive(value):
        raise ClockConfigurationError(f"{label} must be a timezone-aware datetime.")
    return value


def _wall_time(value: datetime | None = None) -> datetime:
    return _aware(value or timezone.now(), "Wall time")


def _speed(value) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ClockConfigurationError("Simulation speed must be a number.") from exc
    if not result.is_finite() or result <= 0 or result > MAX_SPEED_MULTIPLIER:
        raise ClockConfigurationError(
            f"Simulation speed must be greater than 0 and at most {MAX_SPEED_MULTIPLIER}."
        )
    return result.quantize(Decimal("0.01"))


def _validate_clock(clock: SimulationClock) -> SimulationClock:
    _aware(clock.schedule_anchor, "Schedule anchor")
    _aware(clock.wall_clock_started_at, "Wall-clock start")
    _speed(clock.speed_multiplier)
    if clock.paused:
        _aware(clock.paused_simulation_time, "Paused simulation time")
    elif clock.paused_simulation_time is not None:
        raise ClockConfigurationError("A running clock cannot retain a paused simulation time.")
    return clock


def get_simulation_clock() -> SimulationClock | None:
    """Return the configured singleton without creating it on read."""
    clock = SimulationClock.objects.filter(pk=SIMULATION_CLOCK_PK).first()
    return _validate_clock(clock) if clock else None


def simulation_time_for_clock(
    clock: SimulationClock,
    *,
    wall_time: datetime | None = None,
) -> datetime:
    """Calculate simulation time for a validated clock at a deterministic wall instant."""
    clock = _validate_clock(clock)
    if clock.paused:
        return clock.paused_simulation_time
    current_wall_time = _wall_time(wall_time)
    elapsed = current_wall_time - clock.wall_clock_started_at
    return clock.schedule_anchor + elapsed * float(clock.speed_multiplier)


def get_simulation_time(
    *,
    wall_time: datetime | None = None,
    clock: SimulationClock | None = None,
) -> datetime:
    """Return simulation time, falling back to wall time when no schedule clock exists."""
    current_wall_time = _wall_time(wall_time)
    configured_clock = clock if clock is not None else get_simulation_clock()
    if configured_clock is None:
        return current_wall_time
    return simulation_time_for_clock(configured_clock, wall_time=current_wall_time)


def _set_running_origin(
    clock: SimulationClock,
    simulation_time: datetime,
    wall_time: datetime,
) -> None:
    speed = float(_speed(clock.speed_multiplier))
    simulated_elapsed = simulation_time - clock.schedule_anchor
    wall_elapsed = timedelta(seconds=simulated_elapsed.total_seconds() / speed)
    clock.wall_clock_started_at = wall_time - wall_elapsed


@transaction.atomic
def initialize_simulation_clock(
    *,
    seed: int,
    schedule_anchor: datetime,
    wall_time: datetime | None = None,
) -> SimulationClock:
    """Create the singleton only when one does not already exist."""
    existing = SimulationClock.objects.select_for_update().filter(pk=SIMULATION_CLOCK_PK).first()
    if existing:
        return _validate_clock(existing)
    return SimulationClock.objects.create(
        pk=SIMULATION_CLOCK_PK,
        seed=seed,
        schedule_anchor=_aware(schedule_anchor, "Schedule anchor"),
        wall_clock_started_at=_wall_time(wall_time),
        speed_multiplier=Decimal("1.00"),
        paused=False,
        paused_simulation_time=None,
    )


@transaction.atomic
def reset_simulation_clock(
    *,
    seed: int | None = None,
    schedule_anchor: datetime | None = None,
    wall_time: datetime | None = None,
) -> SimulationClock:
    """Reset to the immutable schedule anchor, optionally replacing schedule ownership."""
    current_wall_time = _wall_time(wall_time)
    clock = SimulationClock.objects.select_for_update().filter(pk=SIMULATION_CLOCK_PK).first()
    if clock is None:
        if seed is None or schedule_anchor is None:
            raise ClockNotConfiguredError("No simulation clock is configured.")
        clock = SimulationClock(pk=SIMULATION_CLOCK_PK)
    elif (seed is None) != (schedule_anchor is None):
        raise ClockConfigurationError("Seed and schedule anchor must be replaced together.")

    if seed is not None:
        clock.seed = seed
        clock.schedule_anchor = _aware(schedule_anchor, "Schedule anchor")
    else:
        _validate_clock(clock)
    clock.wall_clock_started_at = current_wall_time
    clock.speed_multiplier = Decimal("1.00")
    clock.paused = False
    clock.paused_simulation_time = None
    clock.save()
    return clock


@transaction.atomic
def pause_simulation_clock(*, wall_time: datetime | None = None) -> SimulationClock:
    current_wall_time = _wall_time(wall_time)
    clock = SimulationClock.objects.select_for_update().filter(pk=SIMULATION_CLOCK_PK).first()
    if clock is None:
        raise ClockNotConfiguredError("No simulation clock is configured.")
    _validate_clock(clock)
    if clock.paused:
        return clock
    clock.paused_simulation_time = simulation_time_for_clock(
        clock,
        wall_time=current_wall_time,
    )
    clock.paused = True
    clock.save(update_fields=["paused", "paused_simulation_time", "updated_at"])
    return clock


@transaction.atomic
def resume_simulation_clock(*, wall_time: datetime | None = None) -> SimulationClock:
    current_wall_time = _wall_time(wall_time)
    clock = SimulationClock.objects.select_for_update().filter(pk=SIMULATION_CLOCK_PK).first()
    if clock is None:
        raise ClockNotConfiguredError("No simulation clock is configured.")
    _validate_clock(clock)
    if not clock.paused:
        return clock
    paused_time = clock.paused_simulation_time
    _set_running_origin(clock, paused_time, current_wall_time)
    clock.paused = False
    clock.paused_simulation_time = None
    clock.save(
        update_fields=[
            "wall_clock_started_at",
            "paused",
            "paused_simulation_time",
            "updated_at",
        ]
    )
    return clock


@transaction.atomic
def set_simulation_speed(
    speed_multiplier,
    *,
    wall_time: datetime | None = None,
) -> SimulationClock:
    current_wall_time = _wall_time(wall_time)
    clock = SimulationClock.objects.select_for_update().filter(pk=SIMULATION_CLOCK_PK).first()
    if clock is None:
        raise ClockNotConfiguredError("No simulation clock is configured.")
    _validate_clock(clock)
    current_simulation_time = simulation_time_for_clock(
        clock,
        wall_time=current_wall_time,
    )
    clock.speed_multiplier = _speed(speed_multiplier)
    update_fields = ["speed_multiplier", "updated_at"]
    if not clock.paused:
        _set_running_origin(clock, current_simulation_time, current_wall_time)
        update_fields.append("wall_clock_started_at")
    clock.save(update_fields=update_fields)
    return clock

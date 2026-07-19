"""Authoritative flight lifecycle and estimated-progress calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.utils import timezone

from tracker.models import Flight

DELAY_THRESHOLD = timedelta(minutes=5)
CHECK_IN_WINDOW = timedelta(hours=3)
BOARDING_WINDOW = timedelta(minutes=45)
GATE_CLOSED_WINDOW = timedelta(minutes=15)
DEPARTED_WINDOW = timedelta(minutes=10)


@dataclass(frozen=True)
class FlightStatusResult:
    code: str
    label: str


def effective_departure(flight: Flight) -> datetime:
    return flight.actual_departure or flight.estimated_departure or flight.scheduled_departure


def effective_arrival(flight: Flight) -> datetime:
    return flight.actual_arrival or flight.estimated_arrival or flight.scheduled_arrival


def get_flight_status(flight: Flight, at_time: datetime | None = None) -> FlightStatusResult:
    """Derive one status at one timezone-aware instant for every application surface."""
    at_time = at_time or timezone.now()
    if timezone.is_naive(at_time):
        raise ValueError("Status evaluation requires a timezone-aware instant.")
    if flight.status == Flight.Status.CANCELLED:
        return FlightStatusResult(Flight.Status.CANCELLED, Flight.Status.CANCELLED.label)
    if (
        flight.diversion_airport_id
        and flight.status == Flight.Status.DIVERTED
        and at_time >= effective_departure(flight)
    ):
        return FlightStatusResult(Flight.Status.DIVERTED, Flight.Status.DIVERTED.label)
    if flight.actual_arrival and at_time >= flight.actual_arrival:
        return FlightStatusResult(Flight.Status.ARRIVED, Flight.Status.ARRIVED.label)

    departure = effective_departure(flight)
    arrival = effective_arrival(flight)
    if at_time >= arrival:
        return FlightStatusResult(Flight.Status.ARRIVED, Flight.Status.ARRIVED.label)
    if at_time >= departure:
        code = (
            Flight.Status.DEPARTED
            if at_time < departure + DEPARTED_WINDOW
            else Flight.Status.EN_ROUTE
        )
        return FlightStatusResult(code, Flight.Status(code).label)
    delayed = (
        flight.estimated_departure is not None
        and flight.estimated_departure - flight.scheduled_departure >= DELAY_THRESHOLD
    )
    if delayed:
        return FlightStatusResult(Flight.Status.DELAYED, Flight.Status.DELAYED.label)
    if at_time >= departure - GATE_CLOSED_WINDOW:
        code = Flight.Status.GATE_CLOSED
    elif at_time >= departure - BOARDING_WINDOW:
        code = Flight.Status.BOARDING
    elif at_time >= departure - CHECK_IN_WINDOW:
        code = Flight.Status.CHECK_IN
    else:
        code = Flight.Status.SCHEDULED
    return FlightStatusResult(code, Flight.Status(code).label)


def estimated_progress(flight: Flight, at_time: datetime | None = None) -> int:
    """Return clamped journey-time progress; this is not a live aircraft position."""
    at_time = at_time or timezone.now()
    departure = effective_departure(flight)
    arrival = effective_arrival(flight)
    if arrival <= departure:
        return 0
    ratio = (at_time - departure).total_seconds() / (arrival - departure).total_seconds()
    return round(max(0.0, min(1.0, ratio)) * 100)

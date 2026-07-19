"""Aircraft-level operational summaries derived from simulated schedules."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from tracker.models import Aircraft, Flight, MaintenanceBlock

from .presentation import duration_label, serialize_flight, utc_label
from .status import effective_arrival, effective_departure, get_flight_status


def _minutes_between(start: datetime, end: datetime) -> int:
    return max(0, round((end - start).total_seconds() / 60))


def aircraft_snapshot(
    aircraft: Aircraft,
    flights: list[Flight],
    blocks: list[MaintenanceBlock],
    at_time: datetime,
) -> dict[str, object]:
    """Return operational state, statistics, and a merged chronological timeline."""
    flights = sorted(flights, key=lambda item: item.scheduled_departure)
    completed = [
        item
        for item in flights
        if item.status != Flight.Status.CANCELLED and effective_arrival(item) <= at_time
    ]
    active = next(
        (
            item
            for item in flights
            if item.status != Flight.Status.CANCELLED
            and effective_departure(item) <= at_time < effective_arrival(item)
            and item.actual_arrival is None
        ),
        None,
    )
    next_flight = next(
        (
            item
            for item in flights
            if item.status != Flight.Status.CANCELLED and effective_departure(item) > at_time
        ),
        None,
    )
    current_block = next(
        (block for block in blocks if block.starts_at <= at_time < block.ends_at),
        None,
    )

    current_airport = aircraft.base_airport
    for item in completed:
        current_airport = item.diversion_airport or item.arrival_airport

    last_completed = completed[-1] if completed else None
    ready_at = None
    if last_completed:
        ready_at = effective_arrival(last_completed) + timedelta(
            minutes=aircraft.aircraft_type.minimum_turnaround_minutes
        )

    if current_block:
        operational_state = "In simulated maintenance"
    elif active:
        operational_state = f"Operating {active.flight_number}"
    elif not aircraft.active or aircraft.maintenance_status == Aircraft.MaintenanceStatus.GROUNDED:
        operational_state = "Grounded"
    elif ready_at and at_time < ready_at:
        operational_state = "Turnaround in progress"
    else:
        operational_state = "Available on ground"

    total_distance = sum(item.distance_km for item in completed)
    total_minutes = sum(
        _minutes_between(effective_departure(item), effective_arrival(item)) for item in completed
    )
    if flights:
        period_minutes = max(
            1,
            _minutes_between(flights[0].scheduled_departure, flights[-1].scheduled_arrival),
        )
    else:
        period_minutes = 1
    utilization = min(100, round(total_minutes / period_minutes * 100))
    on_time = (
        round(sum(item.delay_minutes <= 15 for item in completed) / len(completed) * 100)
        if completed
        else 0
    )
    average_delay = (
        round(sum(item.delay_minutes for item in completed) / len(completed)) if completed else 0
    )
    routes = {
        (item.departure_airport_id, (item.diversion_airport or item.arrival_airport).pk)
        for item in completed
    }
    airport_frequency: Counter[str] = Counter()
    for item in completed:
        airport_frequency[item.departure_airport.display_code] += 1
        airport_frequency[(item.diversion_airport or item.arrival_airport).display_code] += 1

    current_row = serialize_flight(active, at_time) if active else None
    if current_row:
        current_row["elapsed"] = duration_label(
            _minutes_between(effective_departure(active), at_time)
        )
        current_row["remaining"] = duration_label(
            _minutes_between(at_time, effective_arrival(active))
        )

    timeline: list[dict[str, object]] = []
    for item in flights:
        status = get_flight_status(item, at_time)
        result = item.diversion_airport or item.arrival_airport
        timeline.append(
            {
                "kind": "flight",
                "sort_at": item.scheduled_departure,
                "status_code": status.code,
                "status_label": status.label,
                "flight_number": item.flight_number,
                "flight_url": serialize_flight(item, at_time)["flight_url"],
                "route": (f"{item.departure_airport.display_code} → {result.display_code}"),
                "type_label": item.get_flight_type_display(),
                "time": utc_label(item.scheduled_departure),
                "delay": item.delay_minutes,
            }
        )
    for block in blocks:
        timeline.append(
            {
                "kind": "maintenance",
                "sort_at": block.starts_at,
                "status_code": "maintenance",
                "status_label": "Maintenance",
                "title": block.reason,
                "route": "Aircraft unavailable",
                "type_label": "Maintenance block",
                "time": f"{utc_label(block.starts_at)} — {utc_label(block.ends_at)}",
                "delay": 0,
            }
        )
    timeline.sort(key=lambda item: item["sort_at"])

    turnaround_remaining = None
    if ready_at and at_time < ready_at:
        turnaround_remaining = duration_label(_minutes_between(at_time, ready_at))

    return {
        "operational_state": operational_state,
        "current_airport": current_airport,
        "current_flight": current_row,
        "next_flight": serialize_flight(next_flight, at_time) if next_flight else None,
        "current_maintenance": current_block,
        "turnaround_remaining": turnaround_remaining,
        "completed_count": len(completed),
        "total_distance": f"{total_distance:,} km",
        "utilization": utilization,
        "route_count": len(routes),
        "on_time_percentage": on_time,
        "average_delay": average_delay,
        "frequent_airports": airport_frequency.most_common(5),
        "timeline": timeline,
    }

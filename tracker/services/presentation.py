"""Server-authored presentation data for HTML and polling responses."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.urls import reverse
from django.templatetags.static import static

from tracker.models import Flight

from .status import effective_arrival, effective_departure, estimated_progress, get_flight_status


def utc_iso(value: datetime) -> str:
    return value.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z")


def utc_label(value: datetime) -> str:
    return value.astimezone(dt_timezone.utc).strftime("%d %b %Y · %H:%M UTC")


def airport_local_label(value: datetime, timezone_name: str) -> str:
    return value.astimezone(ZoneInfo(timezone_name)).strftime("%d %b · %H:%M %Z")


def duration_label(minutes: int) -> str:
    hours, remainder = divmod(max(0, round(minutes)), 60)
    if hours and remainder:
        return f"{hours}h {remainder}m"
    if hours:
        return f"{hours}h"
    return f"{remainder}m"


def serialize_flight(flight: Flight, at_time: datetime) -> dict[str, object]:
    """Build one canonical row used by initial HTML and live JSON refreshes."""
    status = get_flight_status(flight, at_time)
    departure = effective_departure(flight)
    arrival = effective_arrival(flight)
    is_active = (
        flight.status != Flight.Status.CANCELLED
        and departure <= at_time < arrival
        and flight.actual_arrival is None
    )
    result_airport = flight.diversion_airport or flight.arrival_airport

    # Serialize crew members assigned to this flight
    crew_list = []
    for fc in flight.flight_crew.select_related("crew_member").all():
        crew_member = fc.crew_member
        picture_url = None
        if crew_member.profile_picture:
            picture_url = static(crew_member.profile_picture.name)
        crew_list.append({
            "full_name": crew_member.full_name(),
            "role": crew_member.get_role_display(),
            "role_code": crew_member.role,
            "profile_picture": picture_url,
        })
    crew_list.sort(key=lambda c: (c["role"], c["full_name"]))

    return {
        "flight_number": flight.flight_number,
        "flight_url": reverse("tracker:flight_detail", args=[flight.flight_number]),
        "flight_type": flight.flight_type,
        "flight_type_label": flight.get_flight_type_display(),
        "aircraft_registration": flight.aircraft.registration,
        "aircraft_name": flight.aircraft.display_name,
        "aircraft_type": str(flight.aircraft.aircraft_type),
        "aircraft_url": reverse("tracker:aircraft_detail", args=[flight.aircraft.registration]),
        "departure_code": flight.departure_airport.display_code,
        "departure_city": flight.departure_airport.city,
        "departure_timezone": flight.departure_airport.timezone,
        "arrival_code": flight.arrival_airport.display_code,
        "arrival_city": flight.arrival_airport.city,
        "arrival_timezone": flight.arrival_airport.timezone,
        "result_code": result_airport.display_code,
        "result_timezone": result_airport.timezone,
        "diverted": flight.diversion_airport_id is not None,
        "scheduled_departure_utc": utc_label(flight.scheduled_departure),
        "scheduled_departure_iso": utc_iso(flight.scheduled_departure),
        "scheduled_departure_local": airport_local_label(
            flight.scheduled_departure, flight.departure_airport.timezone
        ),
        "effective_departure_utc": utc_label(departure),
        "effective_departure_iso": utc_iso(departure),
        "effective_departure_local": airport_local_label(
            departure, flight.departure_airport.timezone
        ),
        "scheduled_arrival_utc": utc_label(flight.scheduled_arrival),
        "scheduled_arrival_iso": utc_iso(flight.scheduled_arrival),
        "scheduled_arrival_local": airport_local_label(
            flight.scheduled_arrival, flight.arrival_airport.timezone
        ),
        "effective_arrival_utc": utc_label(arrival),
        "effective_arrival_iso": utc_iso(arrival),
        "effective_arrival_local": airport_local_label(arrival, result_airport.timezone),
        "departure_changed": departure != flight.scheduled_departure,
        "arrival_changed": arrival != flight.scheduled_arrival,
        "status_code": status.code,
        "status_label": status.label,
        "delay_minutes": flight.delay_minutes,
        "progress": estimated_progress(flight, at_time) if is_active else None,
        "is_active": is_active,
        "distance": f"{flight.distance_km:,} km",
        "duration": duration_label(flight.planned_duration_minutes),
        "gate": flight.departure_gate or "TBA",
        "crew": crew_list,
    }

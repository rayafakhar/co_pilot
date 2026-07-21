"""Thin server-rendered views for the simulated operations showcase."""

from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.utils import timezone

from .models import Aircraft, Airport, Flight, MaintenanceBlock
from .services.analytics import aircraft_snapshot
from .services.distance import practical_range_km
from .services.presentation import serialize_flight, utc_iso, utc_label

BOARD_CANDIDATE_LIMIT = 1000
BOARD_LIMIT = 250


def _board_rows(request, at_time):
    queryset = Flight.objects.select_related(
        "aircraft__aircraft_type",
        "departure_airport",
        "arrival_airport",
        "diversion_airport",
    )
    search = request.GET.get("q", "").strip()
    aircraft = request.GET.get("aircraft", "").strip()
    airport = request.GET.get("airport", "").strip()
    date_value = request.GET.get("date", "").strip()
    status = request.GET.get("status", "").strip()

    if search:
        queryset = queryset.filter(
            Q(flight_number__icontains=search)
            | Q(aircraft__registration__icontains=search)
            | Q(departure_airport__iata_code__icontains=search)
            | Q(arrival_airport__iata_code__icontains=search)
            | Q(departure_airport__city__icontains=search)
            | Q(arrival_airport__city__icontains=search)
        )
    if aircraft:
        queryset = queryset.filter(aircraft__registration__iexact=aircraft)
    if airport:
        queryset = queryset.filter(
            Q(departure_airport__iata_code__iexact=airport)
            | Q(arrival_airport__iata_code__iexact=airport)
            | Q(diversion_airport__iata_code__iexact=airport)
        )
    if date_value:
        try:
            selected_date = date.fromisoformat(date_value)
        except ValueError:
            selected_date = None
        if selected_date:
            queryset = queryset.filter(scheduled_departure__date=selected_date)
    else:
        queryset = queryset.filter(
            scheduled_departure__gte=at_time - timedelta(days=7),
            scheduled_departure__lte=at_time + timedelta(days=14),
        )

    # Derived lifecycle states cannot be filtered safely in SQL. Keep evaluation bounded,
    # but apply the public result limit only after the authoritative status filter.
    rows = [
        serialize_flight(item, at_time)
        for item in queryset.order_by("scheduled_departure", "flight_number")[
            :BOARD_CANDIDATE_LIMIT
        ]
    ]
    valid_statuses = {choice for choice, _ in Flight.Status.choices}
    if status in valid_statuses:
        rows = [row for row in rows if row["status_code"] == status]
    return rows[:BOARD_LIMIT]


def _summary(rows):
    return {
        "total": len(rows),
        "active": sum(bool(row["is_active"]) for row in rows),
        "delayed": sum(row["status_code"] == Flight.Status.DELAYED for row in rows),
        "disrupted": sum(
            row["status_code"] in {Flight.Status.CANCELLED, Flight.Status.DIVERTED} for row in rows
        ),
    }


def flight_board(request):
    at_time = timezone.now()
    rows = _board_rows(request, at_time)
    context = {
        "rows": rows,
        "summary": _summary(rows),
        "generated_at": utc_label(at_time),
        "generated_at_iso": utc_iso(at_time),
        "aircraft_options": Aircraft.objects.filter(active=True).only("registration"),
        "airport_options": Airport.objects.exclude(iata_code=None).only("iata_code", "city"),
        "status_options": Flight.Status.choices,
        "filters": request.GET,
    }
    return render(request, "tracker/flight_board.html", context)


def flight_board_data(request):
    """Return server-authored rows; browser time never determines flight state."""
    at_time = timezone.now()
    rows = _board_rows(request, at_time)
    html = render_to_string("tracker/partials/flight_rows.html", {"rows": rows})
    response = JsonResponse(
        {
            "generated_at": utc_iso(at_time),
            "generated_at_label": utc_label(at_time),
            "summary": _summary(rows),
            "flights": rows,
            "html": html,
        }
    )
    response["Cache-Control"] = "no-store"
    return response


def aircraft_detail(request, registration):
    aircraft = get_object_or_404(
        Aircraft.objects.select_related("aircraft_type", "base_airport", "last_known_airport"),
        registration__iexact=registration,
    )
    flights = list(
        aircraft.flights.select_related(
            "aircraft__aircraft_type",
            "departure_airport",
            "arrival_airport",
            "diversion_airport",
        ).order_by("scheduled_departure")
    )
    blocks = list(MaintenanceBlock.objects.filter(aircraft=aircraft).order_by("starts_at"))
    at_time = timezone.now()
    return render(
        request,
        "tracker/aircraft_detail.html",
        {
            "aircraft": aircraft,
            "snapshot": aircraft_snapshot(aircraft, flights, blocks, at_time),
            "practical_range_km": round(practical_range_km(aircraft.aircraft_type)),
            "generated_at": utc_label(at_time),
        },
    )


def flight_detail(request, flight_number):
    flight = get_object_or_404(
        Flight.objects.select_related(
            "aircraft__aircraft_type",
            "departure_airport",
            "arrival_airport",
            "diversion_airport",
        ),
        flight_number__iexact=flight_number,
    )
    at_time = timezone.now()
    return render(
        request,
        "tracker/flight_detail.html",
        {
            "flight": flight,
            "row": serialize_flight(flight, at_time),
            "generated_at": utc_label(at_time),
        },
    )

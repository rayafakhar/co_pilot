"""Thin server-rendered views for the simulated operations showcase."""

from __future__ import annotations

from datetime import date, timedelta

from django.conf import settings
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone

from .models import Aircraft, Airport, Flight, MaintenanceBlock
from .services.analytics import aircraft_snapshot
from .services.clock import (
    ClockConfigurationError,
    get_simulation_clock,
    get_simulation_time,
    simulation_time_for_clock,
)
from .services.distance import practical_range_km
from .services.map_data import build_network_map_payload
from .services.presentation import flight_crew_prefetch, serialize_flight, utc_iso, utc_label

BOARD_CANDIDATE_LIMIT = 1000
BOARD_LIMIT = 250


def _request_times():
    generated_at = timezone.now()
    return get_simulation_time(wall_time=generated_at), generated_at


def _board_rows(request, at_time):
    queryset = Flight.objects.select_related(
        "aircraft__aircraft_type",
        "departure_airport",
        "arrival_airport",
        "diversion_airport",
    ).prefetch_related(flight_crew_prefetch())
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
    at_time, generated_at = _request_times()
    rows = _board_rows(request, at_time)
    context = {
        "rows": rows,
        "summary": _summary(rows),
        "simulation_time": utc_label(at_time),
        "simulation_time_iso": utc_iso(at_time),
        "generated_at": utc_label(generated_at),
        "generated_at_iso": utc_iso(generated_at),
        "aircraft_options": Aircraft.objects.filter(active=True).only("registration"),
        "airport_options": Airport.objects.exclude(iata_code=None).only("iata_code", "city"),
        "status_options": Flight.Status.choices,
        "filters": request.GET,
    }
    return render(request, "tracker/flight_board.html", context)


def flight_board_data(request):
    """Return server-authored rows; browser time never determines flight state."""
    at_time, generated_at = _request_times()
    rows = _board_rows(request, at_time)
    html = render_to_string("tracker/partials/flight_rows.html", {"rows": rows})
    response = JsonResponse(
        {
            "simulation_time": utc_iso(at_time),
            "simulation_time_label": utc_label(at_time),
            "generated_at": utc_iso(generated_at),
            "generated_at_label": utc_label(generated_at),
            "summary": _summary(rows),
            "flights": rows,
            "html": html,
        }
    )
    response["Cache-Control"] = "no-store"
    return response


def network_map(request):
    simulation_time, generated_at = _request_times()
    return render(
        request,
        "tracker/network_map.html",
        {
            "simulation_time": utc_label(simulation_time),
            "generated_at": utc_label(generated_at),
            "map_config": {
                "dataUrl": reverse("tracker:network_map_data"),
                "tileUrl": settings.MAP_TILE_URL,
                "tileAttribution": settings.MAP_TILE_ATTRIBUTION,
                "aircraftIconUrl": static("tracker/images/aircraft-map-icon.svg"),
                "flightBoardUrl": reverse("tracker:flight_board"),
            },
        },
    )


def network_map_data(request):
    """Return bounded, server-authoritative simulated network state."""
    generated_at = timezone.now()
    try:
        clock = get_simulation_clock()
        simulation_time = (
            simulation_time_for_clock(clock, wall_time=generated_at)
            if clock is not None
            else generated_at
        )
        payload = build_network_map_payload(
            simulation_time=simulation_time,
            generated_at=generated_at,
            clock=clock,
        )
    except ClockConfigurationError:
        response = JsonResponse(
            {
                "schema_version": 1,
                "error": "simulation_clock_invalid",
                "message": "The simulation clock is unavailable.",
                "generated_at": utc_iso(generated_at),
            },
            status=503,
        )
    else:
        response = JsonResponse(payload)
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
        )
        .prefetch_related(flight_crew_prefetch())
        .order_by("scheduled_departure")
    )
    blocks = list(MaintenanceBlock.objects.filter(aircraft=aircraft).order_by("starts_at"))
    at_time, generated_at = _request_times()
    return render(
        request,
        "tracker/aircraft_detail.html",
        {
            "aircraft": aircraft,
            "snapshot": aircraft_snapshot(aircraft, flights, blocks, at_time),
            "practical_range_km": round(practical_range_km(aircraft.aircraft_type)),
            "simulation_time": utc_label(at_time),
            "generated_at": utc_label(generated_at),
        },
    )


def flight_detail(request, flight_number):
    flight = get_object_or_404(
        Flight.objects.select_related(
            "aircraft__aircraft_type",
            "departure_airport",
            "arrival_airport",
            "diversion_airport",
        ).prefetch_related(flight_crew_prefetch()),
        flight_number__iexact=flight_number,
    )
    at_time, generated_at = _request_times()
    return render(
        request,
        "tracker/flight_detail.html",
        {
            "flight": flight,
            "row": serialize_flight(flight, at_time),
            "simulation_time": utc_label(at_time),
            "generated_at": utc_label(generated_at),
        },
    )

"""Admin forms surface cross-flight and maintenance schedule violations."""

from datetime import datetime, timedelta, timezone

from django.test import TestCase

from tracker.admin import FlightAdminForm, MaintenanceBlockAdminForm
from tracker.models import Flight
from tracker.services.distance import calculate_duration, haversine_distance_km

from .helpers import aircraft, aircraft_type, airport, flight


class ScheduleAdminFormTests(TestCase):
    def setUp(self):
        self.origin = airport("AAA", latitude=51, longitude=0)
        self.middle = airport("BBB", latitude=52, longitude=1)
        self.other = airport("CCC", latitude=53, longitude=2)
        self.kind = aircraft_type()
        self.plane = aircraft(self.origin, self.kind)
        self.start = datetime(2026, 7, 19, 8, tzinfo=timezone.utc)
        distance = round(haversine_distance_km(self.origin, self.middle))
        duration = calculate_duration(distance, self.kind).total_minutes
        self.first = flight(
            self.plane,
            self.origin,
            self.middle,
            flight_number="TS501",
            scheduled_departure=self.start,
            scheduled_arrival=self.start + timedelta(minutes=duration),
            distance_km=distance,
            planned_duration_minutes=duration,
        )
        self.first.save()

    def test_flight_form_rejects_aircraft_overlap(self):
        departure = self.start + timedelta(minutes=20)
        distance = round(haversine_distance_km(self.middle, self.other))
        duration = calculate_duration(distance, self.kind).total_minutes
        form = FlightAdminForm(
            data={
                "flight_number": "TS502",
                "aircraft": self.plane.pk,
                "departure_airport": self.middle.pk,
                "arrival_airport": self.other.pk,
                "scheduled_departure": departure.isoformat(),
                "scheduled_arrival": (departure + timedelta(minutes=duration)).isoformat(),
                "status": Flight.Status.SCHEDULED,
                "flight_type": Flight.FlightType.PASSENGER,
                "distance_km": distance,
                "planned_duration_minutes": duration,
                "delay_minutes": 0,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("overlap", str(form.non_field_errors()).lower())

    def test_maintenance_form_rejects_flight_conflict(self):
        form = MaintenanceBlockAdminForm(
            data={
                "aircraft": self.plane.pk,
                "starts_at": (self.start + timedelta(minutes=10)).isoformat(),
                "ends_at": (self.first.scheduled_arrival + timedelta(minutes=10)).isoformat(),
                "reason": "Simulated inspection",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("overlaps", str(form.non_field_errors()).lower())

"""Aircraft summaries preserve cancellation and diversion location semantics."""

from datetime import datetime, timedelta, timezone

from django.test import TestCase

from tracker.models import Flight
from tracker.services.analytics import aircraft_snapshot

from .helpers import aircraft, aircraft_type, airport, flight


class AircraftAnalyticsTests(TestCase):
    def test_completed_diversion_updates_resulting_location_but_cancellation_does_not(self):
        origin = airport("AAA")
        planned = airport("BBB", latitude=52, longitude=1)
        diversion = airport("CCC", latitude=53, longitude=2)
        kind = aircraft_type()
        plane = aircraft(origin, kind)
        start = datetime(2026, 7, 19, 8, tzinfo=timezone.utc)
        diverted = flight(
            plane,
            origin,
            planned,
            flight_number="TS401",
            scheduled_departure=start,
            scheduled_arrival=start + timedelta(hours=2),
            actual_departure=start,
            actual_arrival=start + timedelta(hours=2),
            status=Flight.Status.DIVERTED,
            diversion_airport=diversion,
        )
        cancelled = flight(
            plane,
            diversion,
            origin,
            flight_number="TS402",
            scheduled_departure=start + timedelta(hours=4),
            scheduled_arrival=start + timedelta(hours=6),
            status=Flight.Status.CANCELLED,
        )
        snapshot = aircraft_snapshot(
            plane,
            [diverted, cancelled],
            [],
            start + timedelta(hours=8),
        )
        self.assertEqual(snapshot["current_airport"], diversion)
        self.assertEqual(snapshot["completed_count"], 1)
        self.assertEqual(snapshot["route_count"], 1)

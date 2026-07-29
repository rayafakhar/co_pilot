"""Exact lifecycle boundaries for the single authoritative status engine."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from django.test import TestCase

from tracker.models import Flight
from tracker.services.status import estimated_progress, get_flight_status

from .helpers import aircraft, aircraft_type, airport, flight


class FlightStatusTests(TestCase):
    def setUp(self):
        self.origin = airport(
            "JFK", timezone_name="America/New_York", latitude=40.6, longitude=-73.7
        )
        self.destination = airport(
            "LHR", timezone_name="Europe/London", latitude=51.4, longitude=-0.4
        )
        self.plane = aircraft(self.origin, aircraft_type())
        self.departure = datetime(2026, 7, 19, 12, tzinfo=timezone.utc)
        self.item = flight(
            self.plane,
            self.origin,
            self.destination,
            scheduled_departure=self.departure,
            scheduled_arrival=self.departure + timedelta(hours=2),
        )

    def status_at(self, instant):
        return get_flight_status(self.item, instant).code

    def test_preflight_boundaries(self):
        self.assertEqual(
            self.status_at(self.departure - timedelta(hours=3, seconds=1)), Flight.Status.SCHEDULED
        )
        self.assertEqual(
            self.status_at(self.departure - timedelta(hours=3)), Flight.Status.CHECK_IN
        )
        self.assertEqual(
            self.status_at(self.departure - timedelta(minutes=45)), Flight.Status.BOARDING
        )
        self.assertEqual(
            self.status_at(self.departure - timedelta(minutes=15)), Flight.Status.GATE_CLOSED
        )

    def test_departure_and_arrival_boundaries(self):
        self.assertEqual(self.status_at(self.departure), Flight.Status.DEPARTED)
        self.assertEqual(
            self.status_at(self.departure + timedelta(minutes=9, seconds=59)),
            Flight.Status.DEPARTED,
        )
        self.assertEqual(
            self.status_at(self.departure + timedelta(minutes=10)), Flight.Status.EN_ROUTE
        )
        self.assertEqual(self.status_at(self.item.scheduled_arrival), Flight.Status.ARRIVED)

    def test_delay_uses_estimates_before_schedule(self):
        self.item.estimated_departure = self.departure + timedelta(minutes=30)
        self.item.estimated_arrival = self.item.scheduled_arrival + timedelta(minutes=30)
        self.assertEqual(self.status_at(self.departure - timedelta(hours=2)), Flight.Status.DELAYED)
        self.assertEqual(self.status_at(self.item.estimated_departure), Flight.Status.DEPARTED)
        self.assertEqual(self.status_at(self.item.estimated_arrival), Flight.Status.ARRIVED)

    def test_actual_arrival_cancelled_and_diverted_override_clock_windows(self):
        self.item.actual_departure = self.departure
        self.item.actual_arrival = self.departure + timedelta(hours=1, minutes=50)
        self.assertEqual(
            self.status_at(self.item.actual_arrival - timedelta(seconds=1)),
            Flight.Status.EN_ROUTE,
        )
        self.assertEqual(self.status_at(self.item.actual_arrival), Flight.Status.ARRIVED)

        self.item.actual_departure = None
        self.item.actual_arrival = None
        self.item.status = Flight.Status.CANCELLED
        self.assertEqual(self.status_at(self.departure), Flight.Status.CANCELLED)

        self.item.status = Flight.Status.DIVERTED
        self.item.diversion_airport = airport("CDG", latitude=49, longitude=2)
        self.assertEqual(
            self.status_at(self.departure - timedelta(seconds=1)),
            Flight.Status.GATE_CLOSED,
        )
        self.assertEqual(self.status_at(self.departure), Flight.Status.DIVERTED)

    def test_diversion_transitions_to_arrived_at_its_effective_arrival(self):
        self.item.status = Flight.Status.DIVERTED
        self.item.diversion_airport = airport("CDG", latitude=49, longitude=2)
        self.assertEqual(
            self.status_at(self.item.scheduled_arrival - timedelta(seconds=1)),
            Flight.Status.DIVERTED,
        )
        self.assertEqual(self.status_at(self.item.scheduled_arrival), Flight.Status.ARRIVED)

        self.item.actual_departure = self.departure
        self.item.actual_arrival = self.departure + timedelta(hours=1, minutes=40)
        self.assertEqual(
            self.status_at(self.item.actual_arrival - timedelta(seconds=1)),
            Flight.Status.DIVERTED,
        )
        self.assertEqual(self.status_at(self.item.actual_arrival), Flight.Status.ARRIVED)

    def test_same_instant_in_multiple_timezones_has_same_status(self):
        utc_instant = self.departure - timedelta(minutes=30)
        new_york = utc_instant.astimezone(ZoneInfo("America/New_York"))
        london = utc_instant.astimezone(ZoneInfo("Europe/London"))
        self.assertEqual(
            get_flight_status(self.item, new_york), get_flight_status(self.item, london)
        )

    def test_naive_status_instant_is_rejected(self):
        with self.assertRaises(ValueError):
            get_flight_status(self.item, datetime(2026, 7, 19, 12))

    def test_estimated_journey_progress_is_clamped(self):
        self.assertEqual(estimated_progress(self.item, self.departure - timedelta(hours=1)), 0)
        self.assertEqual(estimated_progress(self.item, self.departure + timedelta(hours=1)), 50)
        self.assertEqual(estimated_progress(self.item, self.departure + timedelta(hours=3)), 100)

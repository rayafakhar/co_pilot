"""Model validation and display behavior."""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from tracker.models import Aircraft, AircraftType, Airport, Flight

from .helpers import aircraft, aircraft_type, airport, flight


class AirportModelTests(TestCase):
    def test_codes_are_normalized_and_displayed_professionally(self):
        item = Airport(
            name="Test International",
            city="Example",
            country="Testland",
            iata_code="tst",
            icao_code="ttst",
            timezone="Europe/London",
            latitude=Decimal("51.5"),
            longitude=Decimal("-0.1"),
        )
        item.full_clean()
        self.assertEqual((item.iata_code, item.icao_code), ("TST", "TTST"))
        self.assertEqual(str(item), "Example, Testland - TST/TTST")

    def test_rejects_invalid_timezone_and_coordinates(self):
        item = Airport(
            name="Broken",
            city="Nowhere",
            country="Testland",
            iata_code="BAD",
            icao_code="TBAD",
            timezone="Mars/Olympus",
            latitude=91,
            longitude=10,
        )
        with self.assertRaises(ValidationError) as caught:
            item.full_clean()
        self.assertIn("timezone", caught.exception.message_dict)
        self.assertIn("latitude", caught.exception.message_dict)

    def test_requires_coordinate_pair(self):
        item = Airport(
            name="Partial",
            city="Nowhere",
            country="Testland",
            iata_code="PAR",
            icao_code="TPAR",
            timezone="UTC",
            latitude=10,
        )
        with self.assertRaises(ValidationError):
            item.full_clean()


class AircraftModelTests(TestCase):
    def setUp(self):
        self.base = airport("AAA")
        self.kind = aircraft_type()

    def test_performance_fields_must_be_positive(self):
        invalid = AircraftType(
            manufacturer="Test",
            model="Invalid",
            icao_type_code="FAIL",
            category=AircraftType.Category.NARROW_BODY,
            typical_cruise_speed_kmh=0,
            maximum_range_km=0,
            minimum_turnaround_minutes=0,
            passenger_capacity=0,
        )
        with self.assertRaises(ValidationError):
            invalid.full_clean()

    def test_registration_is_unique_and_normalized(self):
        first = aircraft(self.base, self.kind, "N100TS")
        duplicate = Aircraft(
            registration="n100ts",
            display_name="Duplicate",
            aircraft_type=self.kind,
        )
        with self.assertRaises(ValidationError):
            duplicate.full_clean()
        self.assertEqual(str(first), "N100TS - Test aircraft")


class FlightModelTests(TestCase):
    def setUp(self):
        self.origin = airport("AAA")
        self.destination = airport("BBB", latitude=52, longitude=1)
        self.kind = aircraft_type()
        self.plane = aircraft(self.origin, self.kind)

    def test_rejects_same_airport_and_reversed_times(self):
        item = flight(self.plane, self.origin, self.origin)
        item.scheduled_arrival = item.scheduled_departure - timedelta(minutes=1)
        with self.assertRaises(ValidationError) as caught:
            item.full_clean()
        self.assertIn("arrival_airport", caught.exception.message_dict)
        self.assertIn("scheduled_arrival", caught.exception.message_dict)

    def test_rejects_incoherent_estimated_and_actual_times(self):
        item = flight(
            self.plane,
            self.origin,
            self.destination,
            estimated_arrival=flight(self.plane, self.origin, self.destination).scheduled_arrival,
            actual_departure=flight(self.plane, self.origin, self.destination).scheduled_departure,
            actual_arrival=flight(self.plane, self.origin, self.destination).scheduled_departure,
        )
        with self.assertRaises(ValidationError) as caught:
            item.full_clean()
        self.assertIn("estimated_departure", caught.exception.message_dict)
        self.assertIn("actual_arrival", caught.exception.message_dict)

    def test_cancelled_flight_cannot_move_aircraft(self):
        item = flight(
            self.plane,
            self.origin,
            self.destination,
            status=Flight.Status.CANCELLED,
            actual_departure=flight(self.plane, self.origin, self.destination).scheduled_departure,
        )
        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_display_uses_flight_number_and_route(self):
        item = flight(self.plane, self.origin, self.destination, flight_number="ts200")
        item.full_clean()
        self.assertEqual(str(item), "TS200: AAA -> BBB")

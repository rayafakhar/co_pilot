"""Versioned map API contract, lifecycle selection, geometry, and query bounds."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from tracker.models import Flight, SimulationClock
from tracker.services.clock import ClockConfigurationError, reset_simulation_clock
from tracker.services.map_data import network_bounds

from .helpers import aircraft, aircraft_type, airport, flight

SIMULATION_TIME = datetime(2026, 7, 19, 12, tzinfo=timezone.utc)
WALL_TIME = datetime(2030, 1, 1, 9, tzinfo=timezone.utc)


class NetworkMapDataTests(TestCase):
    def setUp(self):
        self.origin = airport(
            "JFK",
            timezone_name="America/New_York",
            latitude=40.6413,
            longitude=-73.7781,
        )
        self.destination = airport(
            "LHR",
            timezone_name="Europe/London",
            latitude=51.47,
            longitude=-0.4543,
        )
        self.diversion = airport(
            "CDG",
            timezone_name="Europe/Paris",
            latitude=49.0097,
            longitude=2.5479,
        )
        self.plane = aircraft(self.origin, aircraft_type())
        reset_simulation_clock(
            seed=20260719,
            schedule_anchor=SIMULATION_TIME,
            wall_time=WALL_TIME,
        )

    def create_flight(self, flight_number="TS100", **overrides):
        item = flight(
            self.plane,
            self.origin,
            self.destination,
            flight_number=flight_number,
            scheduled_departure=overrides.pop(
                "scheduled_departure",
                SIMULATION_TIME - timedelta(hours=1),
            ),
            scheduled_arrival=overrides.pop(
                "scheduled_arrival",
                SIMULATION_TIME + timedelta(hours=1),
            ),
            **overrides,
        )
        item.save()
        return item

    def assert_no_database_ids(self, value):
        if isinstance(value, dict):
            self.assertNotIn("id", value)
            self.assertNotIn("pk", value)
            for nested in value.values():
                self.assert_no_database_ids(nested)
        elif isinstance(value, list):
            for nested in value:
                self.assert_no_database_ids(nested)

    def get_payload(self):
        with patch("tracker.views.timezone.now", return_value=WALL_TIME):
            response = self.client.get(reverse("tracker:network_map_data"))
        return response, response.json()

    def test_no_generated_schedule_and_no_clock(self):
        SimulationClock.objects.all().delete()
        response, payload = self.get_payload()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(payload["simulation"]["active"])
        self.assertEqual(payload["simulation"]["time"], "2030-01-01T09:00:00Z")
        self.assertEqual(payload["flights"], [])
        self.assertEqual(payload["airports"]["features"], [])
        self.assertIsNone(payload["bounds"])

    def test_invalid_clock_returns_no_store_service_error(self):
        with (
            patch("tracker.views.timezone.now", return_value=WALL_TIME),
            patch(
                "tracker.views.get_simulation_clock",
                side_effect=ClockConfigurationError("invalid clock"),
            ),
        ):
            response = self.client.get(reverse("tracker:network_map_data"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response.json()["error"], "simulation_clock_invalid")

    def test_active_flight_payload_uses_public_identity_and_lon_lat_order(self):
        item = self.create_flight()
        response, payload = self.get_payload()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["generated_at"], "2030-01-01T09:00:00Z")
        self.assertEqual(
            payload["simulation"],
            {
                "active": True,
                "time": "2026-07-19T12:00:00Z",
                "speed_multiplier": "1.00",
                "paused": False,
            },
        )
        self.assertEqual(payload["summary"]["active_flights"], 1)
        serialized = payload["flights"][0]
        self.assertEqual(serialized["flight_number"], item.flight_number)
        self.assertEqual(serialized["origin"]["coordinates"], [-73.7781, 40.6413])
        self.assertEqual(serialized["result_destination"]["coordinates"], [-0.4543, 51.47])
        self.assertEqual(serialized["progress"], 50)
        self.assert_no_database_ids(payload)

    def test_progress_is_clamped_at_departure_midpoint_and_near_arrival(self):
        self.create_flight(
            "TS000",
            scheduled_departure=SIMULATION_TIME,
            scheduled_arrival=SIMULATION_TIME + timedelta(hours=2),
        )
        self.create_flight("TS050")
        self.create_flight(
            "TS099",
            scheduled_departure=SIMULATION_TIME - timedelta(minutes=99),
            scheduled_arrival=SIMULATION_TIME + timedelta(minutes=1),
        )
        _, payload = self.get_payload()
        progress = {item["flight_number"]: item["progress"] for item in payload["flights"]}
        self.assertEqual(progress, {"TS099": 99, "TS050": 50, "TS000": 0})

    def test_delayed_predeparture_cancelled_and_arrived_flights_are_excluded(self):
        future_departure = SIMULATION_TIME + timedelta(minutes=30)
        self.create_flight(
            "DELAYED",
            scheduled_departure=future_departure - timedelta(minutes=20),
            scheduled_arrival=future_departure + timedelta(hours=2),
            estimated_departure=future_departure,
            estimated_arrival=future_departure + timedelta(hours=2, minutes=20),
            delay_minutes=20,
        )
        self.create_flight("CANCELLED", status=Flight.Status.CANCELLED)
        self.create_flight(
            "ARRIVED",
            scheduled_departure=SIMULATION_TIME - timedelta(hours=3),
            scheduled_arrival=SIMULATION_TIME - timedelta(hours=1),
            actual_departure=SIMULATION_TIME - timedelta(hours=3),
            actual_arrival=SIMULATION_TIME - timedelta(hours=1),
            status=Flight.Status.ARRIVED,
        )
        _, payload = self.get_payload()
        self.assertEqual(payload["flights"], [])
        self.assertEqual(payload["summary"]["active_flights"], 0)

    def test_diversion_preserves_planned_destination_and_uses_result_destination(self):
        self.create_flight(
            "DIVERTED",
            status=Flight.Status.DIVERTED,
            diversion_airport=self.diversion,
            delay_minutes=15,
        )
        _, payload = self.get_payload()
        item = payload["flights"][0]
        self.assertTrue(item["diverted"])
        self.assertEqual(item["status_code"], Flight.Status.DIVERTED)
        self.assertEqual(item["planned_destination"]["code"], "LHR")
        self.assertEqual(item["result_destination"]["code"], "CDG")
        self.assertEqual(payload["summary"]["diverted_flights"], 1)
        self.assertEqual(payload["summary"]["delayed_flights"], 1)

    def test_missing_coordinates_omit_only_the_malformed_flight(self):
        self.create_flight()
        self.origin.latitude = None
        self.origin.longitude = None
        self.origin.save(update_fields=["latitude", "longitude"])
        response, payload = self.get_payload()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["flights"], [])
        self.assertEqual(payload["summary"]["omitted_flights"], 1)

    def test_endpoint_uses_one_clock_and_one_bounded_flight_query(self):
        for index in range(4):
            self.create_flight(f"QUERY{index}")

        with patch("tracker.views.timezone.now", return_value=WALL_TIME):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(reverse("tracker:network_map_data"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(queries), 2)
        flight_query = next(query["sql"] for query in queries if "tracker_flight" in query["sql"])
        self.assertIn("LIMIT 500", flight_query)

    def test_network_bounds_use_narrow_antimeridian_interval(self):
        features = [
            {"geometry": {"coordinates": [170.0, 10.0]}},
            {"geometry": {"coordinates": [-170.0, 20.0]}},
        ]
        self.assertEqual(
            network_bounds(features),
            {
                "southwest": [170.0, 10.0],
                "northeast": [190.0, 20.0],
            },
        )

    @override_settings(
        MAP_TILE_URL="https://tiles.example.test/{z}/{x}/{y}.png",
        MAP_TILE_ATTRIBUTION="Example public tiles",
        SECRET_KEY="must-not-appear-in-map-config",
    )
    def test_map_page_renders_public_config_bundles_navigation_and_fallback(self):
        with (
            patch("tracker.views.timezone.now", return_value=WALL_TIME),
            patch("tracker.views.get_simulation_time", return_value=SIMULATION_TIME),
        ):
            response = self.client.get(reverse("tracker:network_map"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Live simulation")
        self.assertContains(response, "/static/tracker/dist/network-map.css")
        self.assertContains(response, "/static/tracker/dist/network-map.js")
        self.assertContains(response, "map-bundle-failed")
        self.assertContains(response, "Map bundle unavailable")
        self.assertContains(response, "Open the flight board")
        self.assertContains(response, "Retry map renderer")
        self.assertContains(response, "https://tiles.example.test/{z}/{x}/{y}.png")
        self.assertContains(response, "Example public tiles")
        self.assertContains(response, "/static/tracker/images/aircraft-map-icon.svg")
        self.assertContains(response, "<noscript>", html=False)
        self.assertContains(response, "Live network map")
        self.assertContains(response, reverse("tracker:flight_board"))
        self.assertNotContains(response, "must-not-appear-in-map-config")

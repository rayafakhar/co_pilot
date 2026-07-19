"""Board polling, filters, detail routes, query bounds, and semantic markup."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from tracker.models import Aircraft, Flight
from tracker.services.generator import GenerationConfig, generate_schedule
from tracker.services.status import get_flight_status

ANCHOR = datetime(2026, 7, 19, 12, tzinfo=timezone.utc)


class OperationsViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        generate_schedule(
            GenerationConfig(
                seed=20260719,
                clear=True,
                anchor_time=ANCHOR,
                aircraft_count=3,
                min_flights_per_aircraft=5,
                max_flights_per_aircraft=5,
            )
        )

    def request_at_anchor(self, url):
        with patch("tracker.views.timezone.now", return_value=ANCHOR):
            return self.client.get(url)

    def test_board_renders_timezone_labels_and_accessible_fallback(self):
        response = self.request_at_anchor(reverse("tracker:flight_board"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "UTC · server authority")
        self.assertContains(response, "Your device time")
        self.assertContains(response, "<caption", html=False)
        self.assertContains(response, "<noscript>", html=False)
        self.assertNotContains(response, 'http-equiv="refresh"')
        self.assertTrue(response.context["rows"])

    def test_board_filters_aircraft_airport_date_search_and_status(self):
        item = Flight.objects.select_related("aircraft", "departure_airport").first()
        status = get_flight_status(item, ANCHOR).code
        url = reverse("tracker:flight_board")
        response = self.request_at_anchor(
            f"{url}?q={item.flight_number}&aircraft={item.aircraft.registration}"
            f"&airport={item.departure_airport.iata_code}"
            f"&date={item.scheduled_departure.date().isoformat()}&status={status}"
        )
        self.assertEqual(
            [row["flight_number"] for row in response.context["rows"]], [item.flight_number]
        )

    def test_json_endpoint_uses_server_status_and_one_flight_query(self):
        url = reverse("tracker:flight_board_data")
        with patch("tracker.views.timezone.now", return_value=ANCHOR):
            with self.assertNumQueries(1):
                response = self.client.get(url)
        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertIn("html", payload)
        self.assertIn("generated_at", payload)
        self.assertTrue(payload["flights"])
        item = Flight.objects.get(pk=payload["flights"][0]["id"])
        self.assertEqual(payload["flights"][0]["status_code"], get_flight_status(item, ANCHOR).code)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_board_queries_are_bounded(self):
        with patch("tracker.views.timezone.now", return_value=ANCHOR):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(reverse("tracker:flight_board"))
                self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries), 3)

    def test_aircraft_detail_and_missing_registration(self):
        item = Aircraft.objects.first()
        url = reverse("tracker:aircraft_detail", args=[item.registration.lower()])
        with patch("tracker.views.timezone.now", return_value=ANCHOR):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, item.registration)
        self.assertContains(response, "Operations timeline")
        self.assertContains(response, "simulated", count=None)
        self.assertLessEqual(len(queries), 3)
        missing = self.client.get(reverse("tracker:aircraft_detail", args=["MISSING"]))
        self.assertEqual(missing.status_code, 404)

    def test_flight_detail_displays_estimated_progress(self):
        item = Flight.objects.first()
        item.scheduled_departure = ANCHOR - timedelta(hours=1)
        item.scheduled_arrival = ANCHOR + timedelta(hours=1)
        item.estimated_departure = None
        item.estimated_arrival = None
        item.actual_departure = item.scheduled_departure
        item.actual_arrival = None
        item.status = Flight.Status.EN_ROUTE
        item.save(
            update_fields=[
                "scheduled_departure",
                "scheduled_arrival",
                "estimated_departure",
                "estimated_arrival",
                "actual_departure",
                "actual_arrival",
                "status",
            ]
        )
        response = self.request_at_anchor(
            reverse("tracker:flight_detail", args=[item.flight_number])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Estimated journey progress")
        self.assertContains(response, "50%")

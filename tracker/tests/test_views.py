"""Board polling, filters, detail routes, query bounds, and semantic markup."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from tracker.models import Aircraft, Flight
from tracker.services.distance import practical_range_km
from tracker.services.generator import GenerationConfig, generate_schedule
from tracker.services.presentation import utc_iso
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
        with (
            patch("tracker.views.timezone.now", return_value=ANCHOR),
            patch("tracker.views.get_simulation_time", return_value=ANCHOR),
        ):
            return self.client.get(url)

    def test_board_renders_timezone_labels_and_accessible_fallback(self):
        response = self.request_at_anchor(reverse("tracker:flight_board"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Simulation time · UTC")
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

    def test_board_search_finds_a_diversion_airport_and_city(self):
        item = Flight.objects.select_related("departure_airport", "arrival_airport").first()
        Flight.objects.exclude(pk=item.pk).delete()
        diversion = (
            item.departure_airport.__class__.objects.exclude(
                pk__in=[item.departure_airport_id, item.arrival_airport_id]
            )
            .exclude(iata_code=None)
            .first()
        )
        self.assertIsNotNone(diversion)
        item.status = Flight.Status.DIVERTED
        item.diversion_airport = diversion
        item.save(update_fields=["status", "diversion_airport"])

        board_url = reverse("tracker:flight_board")
        for query in (diversion.iata_code.lower(), diversion.city.lower()):
            with self.subTest(query=query):
                response = self.request_at_anchor(f"{board_url}?q={query}")
                self.assertEqual(
                    [row["flight_number"] for row in response.context["rows"]],
                    [item.flight_number],
                )

    def test_json_endpoint_uses_server_status_and_bounded_flight_queries(self):
        url = reverse("tracker:flight_board_data")
        with (
            patch("tracker.views.timezone.now", return_value=ANCHOR),
            patch("tracker.views.get_simulation_time", return_value=ANCHOR),
        ):
            with self.assertNumQueries(2):
                response = self.client.get(url)
        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertIn("html", payload)
        self.assertIn("generated_at", payload)
        self.assertEqual(payload["simulation_time"], utc_iso(ANCHOR))
        self.assertTrue(payload["flights"])
        self.assertNotIn("id", payload["flights"][0])
        item = Flight.objects.get(flight_number=payload["flights"][0]["flight_number"])
        self.assertEqual(payload["flights"][0]["status_code"], get_flight_status(item, ANCHOR).code)
        self.assertIn(
            f'data-flight-id="{item.flight_number}"',
            payload["html"],
        )
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_delayed_board_time_attributes_match_effective_values(self):
        item = Flight.objects.first()
        item.scheduled_departure = ANCHOR + timedelta(hours=1)
        item.scheduled_arrival = ANCHOR + timedelta(hours=3)
        item.estimated_departure = item.scheduled_departure + timedelta(minutes=30)
        item.estimated_arrival = item.scheduled_arrival + timedelta(minutes=30)
        item.actual_departure = None
        item.actual_arrival = None
        item.delay_minutes = 30
        item.status = Flight.Status.DELAYED
        item.save()

        response = self.request_at_anchor(
            f"{reverse('tracker:flight_board')}?q={item.flight_number}"
        )
        row = response.context["rows"][0]
        self.assertEqual(row["effective_departure_iso"], utc_iso(item.estimated_departure))
        self.assertEqual(row["effective_arrival_iso"], utc_iso(item.estimated_arrival))
        self.assertContains(response, f'datetime="{utc_iso(item.estimated_departure)}"')
        self.assertContains(response, f'datetime="{utc_iso(item.estimated_arrival)}"')

    def test_diversion_uses_resulting_airport_timezone_label(self):
        item = Flight.objects.select_related("arrival_airport").first()
        diversion = (
            item.departure_airport.__class__.objects.exclude(
                pk__in=[item.departure_airport_id, item.arrival_airport_id]
            )
            .exclude(timezone=item.arrival_airport.timezone)
            .first()
        )
        self.assertIsNotNone(diversion)
        item.scheduled_departure = ANCHOR - timedelta(hours=1)
        item.scheduled_arrival = ANCHOR + timedelta(hours=1)
        item.estimated_departure = None
        item.estimated_arrival = None
        item.actual_departure = item.scheduled_departure
        item.actual_arrival = None
        item.status = Flight.Status.DIVERTED
        item.diversion_airport = diversion
        item.save()

        response = self.request_at_anchor(
            reverse("tracker:flight_detail", args=[item.flight_number])
        )
        self.assertEqual(response.context["row"]["result_timezone"], diversion.timezone)
        self.assertContains(response, f"Resulting arrival · {diversion.timezone}")

    def test_status_filter_is_applied_before_final_board_limit(self):
        seed_flight = Flight.objects.select_related(
            "aircraft", "departure_airport", "arrival_airport"
        ).first()
        Flight.objects.all().delete()
        first_departure = ANCHOR + timedelta(hours=6)
        Flight.objects.create(
            flight_number="LIMIT100",
            aircraft=seed_flight.aircraft,
            departure_airport=seed_flight.departure_airport,
            arrival_airport=seed_flight.arrival_airport,
            scheduled_departure=first_departure,
            scheduled_arrival=first_departure + timedelta(hours=2),
            distance_km=1000,
            planned_duration_minutes=120,
        )
        delayed_departure = ANCHOR + timedelta(hours=7)
        Flight.objects.create(
            flight_number="LIMIT101",
            aircraft=seed_flight.aircraft,
            departure_airport=seed_flight.departure_airport,
            arrival_airport=seed_flight.arrival_airport,
            scheduled_departure=delayed_departure,
            scheduled_arrival=delayed_departure + timedelta(hours=2),
            estimated_departure=delayed_departure + timedelta(minutes=30),
            estimated_arrival=delayed_departure + timedelta(hours=2, minutes=30),
            delay_minutes=30,
            distance_km=1000,
            planned_duration_minutes=120,
        )

        with (
            patch("tracker.views.timezone.now", return_value=ANCHOR),
            patch("tracker.views.get_simulation_time", return_value=ANCHOR),
            patch("tracker.views.BOARD_CANDIDATE_LIMIT", 2),
            patch("tracker.views.BOARD_LIMIT", 1),
        ):
            response = self.client.get(
                f"{reverse('tracker:flight_board')}?status={Flight.Status.DELAYED}"
            )
        self.assertEqual(
            [row["flight_number"] for row in response.context["rows"]],
            ["LIMIT101"],
        )

    def test_board_queries_are_bounded(self):
        with (
            patch("tracker.views.timezone.now", return_value=ANCHOR),
            patch("tracker.views.get_simulation_time", return_value=ANCHOR),
        ):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(reverse("tracker:flight_board"))
                self.assertEqual(response.status_code, 200)
        # Flights and their crew are fetched in two bounded queries; filter options use two more.
        self.assertLessEqual(len(queries), 4)

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
        self.assertContains(response, item.aircraft_type.image_alt_text)
        self.assertContains(response, item.aircraft_type.image_author)
        self.assertContains(response, item.aircraft_type.image_license)
        self.assertContains(response, item.aircraft_type.image_source_url)
        # Aircraft, flights, crew, maintenance, and the simulation clock stay constant-size.
        self.assertLessEqual(len(queries), 5)
        missing = self.client.get(reverse("tracker:aircraft_detail", args=["MISSING"]))
        self.assertEqual(missing.status_code, 404)

    def test_aircraft_detail_distinguishes_configured_and_practical_range(self):
        item = Aircraft.objects.first()
        response = self.request_at_anchor(
            reverse("tracker:aircraft_detail", args=[item.registration])
        )
        expected_practical = round(practical_range_km(item.aircraft_type))
        self.assertEqual(response.context["practical_range_km"], expected_practical)
        self.assertContains(response, "Configured maximum range")
        self.assertContains(response, f"{item.aircraft_type.maximum_range_km} km")
        self.assertContains(response, "Simulation practical range")
        self.assertContains(response, f"{expected_practical} km")

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

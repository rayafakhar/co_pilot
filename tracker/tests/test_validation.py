"""Focused tests proving the structured validator reports unsafe schedules."""

from datetime import datetime, timedelta, timezone

from django.test import TestCase

from tracker.models import CrewMember, Flight, FlightCrew, MaintenanceBlock
from tracker.services.distance import calculate_duration, haversine_distance_km
from tracker.services.validation import validate_schedule, violation_counts

from .helpers import aircraft, aircraft_type, airport, flight


class ScheduleValidationTests(TestCase):
    def setUp(self):
        self.origin = airport("AAA", latitude=51, longitude=0)
        self.middle = airport("BBB", latitude=52, longitude=1)
        self.other = airport("CCC", latitude=48, longitude=2)
        self.kind = aircraft_type(minimum_turnaround_minutes=45)
        self.plane = aircraft(self.origin, self.kind)
        self.start = datetime(2026, 7, 19, 8, tzinfo=timezone.utc)

    def plausible_flight(self, number, origin, destination, departure):
        distance = round(haversine_distance_km(origin, destination))
        duration = calculate_duration(distance, self.kind).total_minutes
        return flight(
            self.plane,
            origin,
            destination,
            flight_number=number,
            scheduled_departure=departure,
            scheduled_arrival=departure + timedelta(minutes=duration),
            distance_km=distance,
            planned_duration_minutes=duration,
        )

    def test_reports_overlap_turnaround_continuity_range_and_duration(self):
        first = self.plausible_flight("TS101", self.origin, self.middle, self.start)
        second = self.plausible_flight(
            "TS102", self.other, self.origin, self.start + timedelta(minutes=30)
        )
        second.distance_km = self.kind.maximum_range_km
        second.planned_duration_minutes = 1
        counts = violation_counts(validate_schedule([first, second]))
        self.assertGreater(counts["overlap"], 0)
        self.assertGreater(counts["continuity"], 0)
        self.assertGreater(counts["range"], 0)
        self.assertGreater(counts["duration"], 0)

    def test_reports_turnaround_and_maintenance_conflict(self):
        first = self.plausible_flight("TS201", self.origin, self.middle, self.start)
        second = self.plausible_flight(
            "TS202",
            self.middle,
            self.other,
            first.scheduled_arrival + timedelta(minutes=20),
        )
        block = MaintenanceBlock(
            aircraft=self.plane,
            starts_at=second.scheduled_departure - timedelta(minutes=10),
            ends_at=second.scheduled_arrival + timedelta(minutes=10),
        )
        counts = violation_counts(validate_schedule([first, second], [block]))
        self.assertEqual(counts["turnaround"], 1)
        self.assertEqual(counts["maintenance"], 1)

    def test_reports_cancelled_movement_invalid_actuals_and_diversion(self):
        item = self.plausible_flight("TS301", self.origin, self.middle, self.start)
        item.status = Flight.Status.CANCELLED
        item.actual_departure = item.scheduled_departure
        item.actual_arrival = item.scheduled_departure
        item.diversion_airport = self.middle
        counts = violation_counts(validate_schedule([item]))
        self.assertEqual(counts["cancelled_movement"], 1)
        self.assertEqual(counts["actual_time"], 1)
        self.assertEqual(counts["invalid_diversion"], 1)

    def test_crew_continuity_reports_people_and_airports_for_iterables(self):
        first = self.plausible_flight("TS401", self.origin, self.middle, self.start)
        second = self.plausible_flight(
            "TS402",
            self.other,
            self.origin,
            self.start + timedelta(hours=10),
        )
        first.save()
        second.save()
        crew_member = CrewMember.objects.create(
            first_name="Avery",
            last_name="Stone",
            role=CrewMember.Role.PILOT,
        )
        FlightCrew.objects.bulk_create(
            [
                FlightCrew(flight=first, crew_member=crew_member),
                FlightCrew(flight=second, crew_member=crew_member),
            ]
        )

        with self.assertNumQueries(2):
            violations = validate_schedule(iter([first, second]))
        continuity = next(item for item in violations if item.code == "geo_continuity")

        self.assertEqual(continuity.crew_member_name, "Avery Stone")
        self.assertIn(self.middle.display_code, continuity.message)
        self.assertIn(self.other.display_code, continuity.message)

    def test_crew_validation_ignores_cancelled_flights(self):
        first = self.plausible_flight("TS501", self.origin, self.middle, self.start)
        second = self.plausible_flight(
            "TS502",
            self.other,
            self.origin,
            self.start + timedelta(hours=10),
        )
        first.status = Flight.Status.CANCELLED
        first.save()
        second.save()
        crew_member = CrewMember.objects.create(
            first_name="Avery",
            last_name="Stone",
            role=CrewMember.Role.PILOT,
        )
        FlightCrew.objects.bulk_create(
            [
                FlightCrew(flight=first, crew_member=crew_member),
                FlightCrew(flight=second, crew_member=crew_member),
            ]
        )

        violations = validate_schedule([first, second])
        # Since the first flight is cancelled, the crew member is not flying it,
        # so there should be no geo_continuity violations.
        self.assertEqual(
            len(
                [
                    v
                    for v in violations
                    if v.code in ("geo_continuity", "insufficient_rest", "double_booking")
                ]
            ),
            0,
        )


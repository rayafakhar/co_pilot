"""Deterministic generation and cross-flight invariant coverage."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from django.test import TestCase

from tracker.models import Aircraft, CrewMember, Flight, MaintenanceBlock
from tracker.services.distance import practical_range_km
from tracker.services.generator import GenerationConfig, generate_schedule, generation_anchor
from tracker.services.status import effective_arrival, effective_departure, get_flight_status
from tracker.services.validation import validate_schedule

ANCHOR = datetime(2026, 7, 19, 12, tzinfo=timezone.utc)


def config(seed: int, **overrides) -> GenerationConfig:
    values = {
        "seed": seed,
        "clear": True,
        "anchor_time": ANCHOR,
        "aircraft_count": 8,
        "days_back": 3,
        "days_forward": 7,
        "min_flights_per_aircraft": 8,
        "max_flights_per_aircraft": 8,
    }
    values.update(overrides)
    return GenerationConfig(**values)


def stored_schedule():
    flights = list(
        Flight.objects.select_related(
            "aircraft__aircraft_type",
            "aircraft__base_airport",
            "departure_airport",
            "arrival_airport",
            "diversion_airport",
        ).order_by("aircraft_id", "scheduled_departure")
    )
    blocks = list(MaintenanceBlock.objects.select_related("aircraft"))
    return flights, blocks


def schedule_signature() -> tuple:
    return tuple(
        Flight.objects.order_by("aircraft__registration", "scheduled_departure").values_list(
            "flight_number",
            "aircraft__registration",
            "departure_airport__iata_code",
            "arrival_airport__iata_code",
            "scheduled_departure",
            "scheduled_arrival",
            "estimated_departure",
            "estimated_arrival",
            "status",
            "flight_type",
            "diversion_airport__iata_code",
        )
    )


class GeneratedScheduleInvariantTests(TestCase):
    def test_seed_alone_determines_anchor(self):
        dated = generation_anchor(GenerationConfig(seed=20260719))
        generic = generation_anchor(GenerationConfig(seed=12345))
        self.assertEqual(dated, ANCHOR)
        self.assertEqual(
            generic,
            datetime(2020, 1, 1, 12, tzinfo=timezone.utc) + timedelta(days=12345 % 3653),
        )

    def test_several_hundred_generated_operations_are_valid(self):
        checked = 0
        for seed in (101, 202, 303, 404, 505):
            generate_schedule(config(seed))
            flights, blocks = stored_schedule()
            checked += len(flights)
            self.assertEqual(validate_schedule(flights, blocks), [], f"seed {seed}")
            self._assert_explicit_invariants(flights)
        self.assertGreaterEqual(checked, 300)

    def _assert_explicit_invariants(self, flights):
        itineraries = defaultdict(list)
        for item in flights:
            itineraries[item.aircraft_id].append(item)
            self.assertLessEqual(
                item.distance_km,
                practical_range_km(item.aircraft.aircraft_type),
            )
            if item.actual_arrival:
                self.assertIsNotNone(item.actual_departure)
                self.assertLess(item.actual_departure, item.actual_arrival)
            if item.status == Flight.Status.CANCELLED:
                self.assertIsNone(item.actual_departure)
                self.assertIsNone(item.actual_arrival)
            if item.scheduled_departure > ANCHOR:
                self.assertNotIn(
                    get_flight_status(item, ANCHOR).code,
                    {Flight.Status.ARRIVED, Flight.Status.LANDED},
                )

        for itinerary in itineraries.values():
            current_airport_id = itinerary[0].aircraft.base_airport_id
            previous_operating = None
            for item in itinerary:
                self.assertEqual(item.departure_airport_id, current_airport_id)
                if item.status == Flight.Status.CANCELLED:
                    continue
                if previous_operating:
                    minimum_ready = effective_arrival(previous_operating) + timedelta(
                        minutes=item.aircraft.aircraft_type.minimum_turnaround_minutes
                    )
                    self.assertGreaterEqual(effective_departure(item), minimum_ready)
                current_airport_id = item.diversion_airport_id or item.arrival_airport_id
                previous_operating = item

    def test_same_seed_and_anchor_create_identical_schedule(self):
        generate_schedule(config(909))
        first = schedule_signature()
        generate_schedule(config(909))
        self.assertEqual(first, schedule_signature())

    def test_different_seeds_create_different_valid_schedules(self):
        generate_schedule(config(111))
        first = schedule_signature()
        generate_schedule(config(222))
        second = schedule_signature()
        self.assertNotEqual(first, second)
        flights, blocks = stored_schedule()
        self.assertEqual(validate_schedule(flights, blocks), [])

    def test_no_clear_appends_without_deleting_existing_rows(self):
        generate_schedule(
            config(707, aircraft_count=3, min_flights_per_aircraft=4, max_flights_per_aircraft=4)
        )
        original_numbers = set(Flight.objects.values_list("flight_number", flat=True))
        original_crew = set(
            CrewMember.objects.values_list(
                "first_name",
                "last_name",
                "role",
                "profile_picture",
            )
        )
        append_config = config(
            808,
            clear=False,
            aircraft_count=2,
            min_flights_per_aircraft=4,
            max_flights_per_aircraft=4,
        )
        generate_schedule(append_config)
        self.assertTrue(
            original_numbers.issubset(set(Flight.objects.values_list("flight_number", flat=True)))
        )
        self.assertEqual(Aircraft.objects.count(), 5)
        self.assertEqual(CrewMember.objects.count(), 20)
        self.assertEqual(
            set(
                CrewMember.objects.values_list(
                    "first_name",
                    "last_name",
                    "role",
                    "profile_picture",
                )
            ),
            original_crew,
        )

    def test_append_mode_fills_registration_gap_without_collision(self):
        generate_schedule(
            config(
                707,
                aircraft_count=3,
                min_flights_per_aircraft=4,
                max_flights_per_aircraft=4,
            )
        )
        Aircraft.objects.get(registration="N002NS").delete()
        generate_schedule(
            config(
                808,
                clear=False,
                aircraft_count=1,
                min_flights_per_aircraft=4,
                max_flights_per_aircraft=4,
            )
        )
        self.assertEqual(Aircraft.objects.filter(registration="N002NS").count(), 1)
        self.assertEqual(Aircraft.objects.count(), 3)

    def test_operational_variations_remain_explicit_and_coherent(self):
        generate_schedule(
            config(
                20260719,
                aircraft_count=12,
                min_flights_per_aircraft=10,
                max_flights_per_aircraft=10,
                cancellation_rate=0.20,
                diversion_rate=0.25,
                ferry_rate=0.30,
                delay_rate=0.60,
            )
        )
        flights, blocks = stored_schedule()
        self.assertEqual(validate_schedule(flights, blocks), [])
        self.assertTrue(any(item.status == Flight.Status.CANCELLED for item in flights))
        self.assertTrue(any(item.status == Flight.Status.DIVERTED for item in flights))
        self.assertTrue(any(item.flight_type == Flight.FlightType.FERRY for item in flights))
        self.assertTrue(any(item.delay_minutes for item in flights))

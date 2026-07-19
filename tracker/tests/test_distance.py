"""Distance, practical range, and transparent duration assumptions."""

from django.test import TestCase

from tracker.services.distance import (
    calculate_duration,
    haversine_distance_km,
    practical_range_km,
)

from .helpers import aircraft_type, airport


class DistanceEngineTests(TestCase):
    def test_haversine_distance_is_plausible_for_jfk_lhr(self):
        jfk = airport("JFK", latitude=40.6413, longitude=-73.7781)
        lhr = airport("LHR", latitude=51.47, longitude=-0.4543)
        self.assertAlmostEqual(haversine_distance_km(jfk, lhr), 5_540, delta=30)

    def test_duration_scales_with_route_length(self):
        kind = aircraft_type(maximum_range_km=15_000)
        short = calculate_duration(500, kind)
        long = calculate_duration(8_000, kind)
        self.assertGreater(short.total_minutes, 60)
        self.assertGreater(long.total_minutes, short.total_minutes * 5)
        self.assertEqual(practical_range_km(kind), 13_500)

    def test_distance_requires_coordinate_pairs(self):
        origin = airport("AAA")
        destination = airport("BBB")
        destination.latitude = None
        destination.longitude = None
        with self.assertRaises(ValueError):
            haversine_distance_km(origin, destination)

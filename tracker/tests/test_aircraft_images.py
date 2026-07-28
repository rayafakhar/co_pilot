"""Aircraft image assets and attribution metadata stay complete and local."""

from urllib.parse import urlparse

from django.conf import settings
from django.test import SimpleTestCase

from tracker.services.fixtures import AIRCRAFT_TYPES


class AircraftImageFixtureTests(SimpleTestCase):
    def test_each_reference_type_has_a_unique_local_attributed_jpeg(self):
        images = set()
        sources = set()

        for aircraft_type in AIRCRAFT_TYPES:
            with self.subTest(type_code=aircraft_type["icao_type_code"]):
                image = aircraft_type["image"]
                source = aircraft_type["image_source_url"]
                asset = settings.BASE_DIR / "tracker" / "static" / image

                self.assertNotIn(image, images)
                self.assertNotIn(source, sources)
                self.assertTrue(asset.is_file(), f"Missing static aircraft image: {asset}")
                self.assertGreater(asset.stat().st_size, 20_000)
                with asset.open("rb") as image_file:
                    self.assertEqual(image_file.read(3), b"\xff\xd8\xff")

                self.assertTrue(aircraft_type["image_alt_text"])
                self.assertTrue(aircraft_type["image_author"])
                self.assertEqual(aircraft_type["image_license"], "CC BY-SA 4.0")
                self.assertEqual(urlparse(source).netloc, "commons.wikimedia.org")

                images.add(image)
                sources.add(source)

        self.assertEqual(len(images), 9)
        self.assertEqual(len(sources), 9)
        self.assertEqual(
            {aircraft_type["category"] for aircraft_type in AIRCRAFT_TYPES},
            {"narrow_body", "wide_body", "regional", "turboprop"},
        )

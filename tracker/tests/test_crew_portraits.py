"""Engine-generated crew portraits stay distinct, faceless, and gender-aligned."""

from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

from django.test import SimpleTestCase, TestCase

from tracker.models import CrewMember
from tracker.services.generator import (
    _FEMALE_HAIR,
    _MALE_HAIR,
    _create_crew,
    _crew_profiles,
    _generate_crew_svgs,
)


class CrewPortraitGenerationTests(SimpleTestCase):
    def generate(self, seed: int, output_dir: Path) -> list[str]:
        profiles = _crew_profiles(20, seed)
        _generate_crew_svgs(profiles, output_dir, seed)
        return [
            (output_dir / f"crew_{profile.slot:02d}.svg").read_text(encoding="utf-8")
            for profile in profiles
        ]

    def test_twenty_profiles_are_unique_and_role_balanced(self):
        profiles = _crew_profiles(20, 20260719)
        names = {(profile.identity.first_name, profile.identity.last_name) for profile in profiles}
        self.assertEqual(len(names), 20)
        self.assertEqual(
            [profile.role for profile in profiles].count(CrewMember.Role.PILOT),
            10,
        )
        self.assertEqual(
            [profile.role for profile in profiles].count(CrewMember.Role.FLIGHT_ATTENDANT),
            10,
        )

    def test_generated_svgs_are_distinct_faceless_and_gender_aligned(self):
        profiles = _crew_profiles(20, 20260719)
        male_hair = {style[0] for style in _MALE_HAIR}
        female_hair = {style[0] for style in _FEMALE_HAIR}
        with TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            contents = self.generate(20260719, output_dir)

        self.assertEqual(len(contents), 20)
        self.assertEqual(
            len({hashlib.sha256(content.encode()).hexdigest() for content in contents}),
            20,
        )
        for profile, content in zip(profiles, contents, strict=True):
            root = ElementTree.fromstring(content)
            self.assertEqual(root.attrib["data-gender"], profile.identity.gender)
            self.assertEqual(root.attrib["data-role"], profile.role)
            self.assertEqual(root.attrib["data-style"], "faceless")
            self.assertEqual(root.attrib["data-facial-features"], "none")
            allowed_hair = male_hair if profile.identity.gender == "male" else female_hair
            self.assertIn(root.attrib["data-hair"], allowed_hair)
            self.assertIn(
                f"{profile.identity.first_name} {profile.identity.last_name}",
                content,
            )
            self.assertNotIn("<text", content)
            self.assertNotIn("eye", content.lower())
            self.assertNotIn("mouth", content.lower())

    def test_seed_reproduces_and_changes_the_art(self):
        with TemporaryDirectory() as first, TemporaryDirectory() as second:
            first_contents = self.generate(111, Path(first))
            repeated_contents = self.generate(111, Path(second))
            self.assertEqual(first_contents, repeated_contents)

        with TemporaryDirectory() as third:
            changed_contents = self.generate(222, Path(third))
        self.assertNotEqual(first_contents, changed_contents)

    def test_roster_rejects_more_people_than_identity_pool(self):
        with self.assertRaisesMessage(ValueError, "crew count must be between 0 and 30"):
            _crew_profiles(31, 1)


class CrewPortraitPersistenceTests(TestCase):
    def test_created_crew_use_the_runtime_generated_svg_slots(self):
        with TemporaryDirectory() as temporary_directory:
            crew = _create_crew(20, seed=404, output_dir=Path(temporary_directory))
            generated_files = sorted(Path(temporary_directory).glob("crew_*.svg"))

        self.assertEqual(len(crew), 20)
        self.assertEqual(len(generated_files), 20)
        self.assertEqual(len({member.full_name() for member in crew}), 20)
        self.assertEqual(len({member.profile_picture for member in crew}), 20)
        self.assertEqual(
            [member.profile_picture for member in crew],
            [f"tracker/images/crew/crew_{slot:02d}.svg" for slot in range(1, 21)],
        )

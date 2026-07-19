"""Management-command behavior, reports, deletion safeguards, and rollback."""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from tracker.models import Flight
from tracker.services.validation import ScheduleViolation


class GenerateDataCommandTests(TestCase):
    def run_command(self, *args):
        output = StringIO()
        call_command("generate_data", *args, stdout=output, stderr=output)
        return output.getvalue()

    def test_seeded_generation_prints_deterministic_validation_report(self):
        args = (
            "--seed",
            "12345",
            "--aircraft-count",
            "2",
            "--min-flights-per-aircraft",
            "3",
            "--max-flights-per-aircraft",
            "3",
            "--clear",
        )
        first = self.run_command(*args)
        second = self.run_command(*args)
        self.assertEqual(first, second)
        self.assertIn("flights created: 6", first)
        self.assertIn("overlap violations: 0", first)
        self.assertIn("continuity violations: 0", first)
        self.assertIn("range violations: 0", first)
        self.assertIn("seed used: 12345", first)

    def test_existing_data_is_not_deleted_without_clear(self):
        self.run_command(
            "--seed",
            "10",
            "--aircraft-count",
            "1",
            "--min-flights-per-aircraft",
            "2",
            "--max-flights-per-aircraft",
            "2",
            "--clear",
        )
        original = set(Flight.objects.values_list("flight_number", flat=True))
        self.run_command(
            "--seed",
            "20",
            "--aircraft-count",
            "1",
            "--min-flights-per-aircraft",
            "2",
            "--max-flights-per-aircraft",
            "2",
        )
        self.assertTrue(
            original.issubset(set(Flight.objects.values_list("flight_number", flat=True)))
        )
        self.assertEqual(Flight.objects.count(), 4)

    def test_validate_only_does_not_mutate_data(self):
        self.run_command(
            "--seed",
            "30",
            "--aircraft-count",
            "1",
            "--min-flights-per-aircraft",
            "2",
            "--max-flights-per-aircraft",
            "2",
            "--clear",
        )
        before = list(Flight.objects.values_list("flight_number", flat=True))
        output = self.run_command("--validate-only")
        self.assertEqual(before, list(Flight.objects.values_list("flight_number", flat=True)))
        self.assertIn("0 violations", output)

    def test_invalid_options_exit_nonzero(self):
        with self.assertRaises(CommandError):
            self.run_command("--days-back", "0", "--days-forward", "0")
        with self.assertRaises(CommandError):
            self.run_command("--delay-rate", "1.5")
        with self.assertRaises(CommandError):
            self.run_command("--maintenance-rate", "1.5")
        with self.assertRaises(CommandError):
            self.run_command("--validate-only", "--clear")

    def test_validation_failure_rolls_back_clear_and_generation(self):
        self.run_command(
            "--seed",
            "40",
            "--aircraft-count",
            "1",
            "--min-flights-per-aircraft",
            "2",
            "--max-flights-per-aircraft",
            "2",
            "--clear",
        )
        original = set(Flight.objects.values_list("flight_number", flat=True))
        violation = ScheduleViolation("overlap", "Injected test violation", "N001NS", "NS0000101")
        with patch("tracker.services.generator.validate_schedule", return_value=[violation]):
            with self.assertRaises(CommandError):
                self.run_command(
                    "--seed",
                    "50",
                    "--aircraft-count",
                    "2",
                    "--min-flights-per-aircraft",
                    "2",
                    "--max-flights-per-aircraft",
                    "2",
                    "--clear",
                )
        self.assertEqual(original, set(Flight.objects.values_list("flight_number", flat=True)))

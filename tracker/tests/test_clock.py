"""Persistent simulation-clock calculations, mutations, commands, and generation."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from tracker.models import SimulationClock
from tracker.services.clock import (
    get_simulation_clock,
    get_simulation_time,
    pause_simulation_clock,
    reset_simulation_clock,
    resume_simulation_clock,
    set_simulation_speed,
    simulation_time_for_clock,
)
from tracker.services.generator import (
    GenerationConfig,
    ScheduleGenerationError,
    generate_schedule,
)
from tracker.services.validation import ScheduleViolation

ANCHOR = datetime(2026, 7, 19, 12, tzinfo=timezone.utc)
WALL_START = datetime(2030, 1, 1, 9, tzinfo=timezone.utc)


class SimulationClockServiceTests(TestCase):
    def create_clock(self):
        return reset_simulation_clock(
            seed=20260719,
            schedule_anchor=ANCHOR,
            wall_time=WALL_START,
        )

    def test_missing_clock_falls_back_to_aware_wall_time_without_creating(self):
        result = get_simulation_time(wall_time=WALL_START)
        self.assertEqual(result, WALL_START)
        self.assertIsNone(get_simulation_clock())
        self.assertEqual(SimulationClock.objects.count(), 0)
        self.assertIsNotNone(result.tzinfo)

    def test_running_clock_advances_from_schedule_anchor(self):
        clock = self.create_clock()
        instant = simulation_time_for_clock(
            clock,
            wall_time=WALL_START + timedelta(seconds=90),
        )
        self.assertEqual(instant, ANCHOR + timedelta(seconds=90))
        self.assertIsNotNone(instant.tzinfo)

    def test_paused_clock_remains_fixed(self):
        self.create_clock()
        paused = pause_simulation_clock(wall_time=WALL_START + timedelta(minutes=5))
        self.assertTrue(paused.paused)
        self.assertEqual(paused.paused_simulation_time, ANCHOR + timedelta(minutes=5))
        self.assertEqual(
            simulation_time_for_clock(
                paused,
                wall_time=WALL_START + timedelta(days=2),
            ),
            ANCHOR + timedelta(minutes=5),
        )

    def test_pause_and_resume_preserve_continuity(self):
        self.create_clock()
        pause_simulation_clock(wall_time=WALL_START + timedelta(minutes=5))
        resumed = resume_simulation_clock(wall_time=WALL_START + timedelta(hours=3))
        self.assertFalse(resumed.paused)
        self.assertIsNone(resumed.paused_simulation_time)
        self.assertEqual(
            simulation_time_for_clock(
                resumed,
                wall_time=WALL_START + timedelta(hours=3, minutes=2),
            ),
            ANCHOR + timedelta(minutes=7),
        )

    def test_speed_change_preserves_instant_then_uses_new_multiplier(self):
        self.create_clock()
        changed_at = WALL_START + timedelta(minutes=10)
        clock = set_simulation_speed(Decimal("2.5"), wall_time=changed_at)
        self.assertEqual(clock.speed_multiplier, Decimal("2.50"))
        self.assertEqual(
            simulation_time_for_clock(clock, wall_time=changed_at), ANCHOR + timedelta(minutes=10)
        )
        self.assertEqual(
            simulation_time_for_clock(
                clock,
                wall_time=changed_at + timedelta(minutes=4),
            ),
            ANCHOR + timedelta(minutes=20),
        )

    def test_reset_returns_to_anchor_running_at_normal_speed(self):
        self.create_clock()
        set_simulation_speed(5, wall_time=WALL_START + timedelta(minutes=10))
        pause_simulation_clock(wall_time=WALL_START + timedelta(minutes=20))
        reset = reset_simulation_clock(wall_time=WALL_START + timedelta(days=1))
        self.assertEqual(reset.schedule_anchor, ANCHOR)
        self.assertEqual(reset.speed_multiplier, Decimal("1.00"))
        self.assertFalse(reset.paused)
        self.assertEqual(
            simulation_time_for_clock(
                reset,
                wall_time=WALL_START + timedelta(days=1, seconds=30),
            ),
            ANCHOR + timedelta(seconds=30),
        )


class SimulationClockGenerationTests(TestCase):
    def generation_config(self, seed, *, clear):
        return GenerationConfig(
            seed=seed,
            clear=clear,
            anchor_time=ANCHOR + timedelta(days=seed % 2),
            aircraft_count=1,
            min_flights_per_aircraft=2,
            max_flights_per_aircraft=2,
        )

    def test_clear_generation_resets_clock_with_seed_and_anchor(self):
        with patch("tracker.services.generator.timezone.now", return_value=WALL_START):
            report = generate_schedule(self.generation_config(100, clear=True))
        clock = get_simulation_clock()
        self.assertEqual(clock.seed, 100)
        self.assertEqual(clock.schedule_anchor, report.anchor_time)
        self.assertEqual(clock.wall_clock_started_at, WALL_START)
        self.assertEqual(clock.speed_multiplier, Decimal("1.00"))
        self.assertFalse(clock.paused)

    def test_append_generation_preserves_existing_clock(self):
        with patch("tracker.services.generator.timezone.now", return_value=WALL_START):
            generate_schedule(self.generation_config(100, clear=True))
        set_simulation_speed(3, wall_time=WALL_START + timedelta(minutes=1))
        pause_simulation_clock(wall_time=WALL_START + timedelta(minutes=2))
        before = SimulationClock.objects.values().get(pk=1)

        with patch(
            "tracker.services.generator.timezone.now",
            return_value=WALL_START + timedelta(days=1),
        ):
            generate_schedule(self.generation_config(101, clear=False))

        after = SimulationClock.objects.values().get(pk=1)
        self.assertEqual(after, before)

    def test_failed_clear_generation_rolls_back_previous_clock(self):
        with patch("tracker.services.generator.timezone.now", return_value=WALL_START):
            generate_schedule(self.generation_config(100, clear=True))
        before = SimulationClock.objects.values().get(pk=1)
        violation = ScheduleViolation("overlap", "Injected failure", "N001NS", "NS001")

        with patch("tracker.services.generator.validate_schedule", return_value=[violation]):
            with self.assertRaises(ScheduleGenerationError):
                generate_schedule(self.generation_config(102, clear=True))

        self.assertEqual(SimulationClock.objects.values().get(pk=1), before)


class SimulationClockCommandTests(TestCase):
    def run_command(self, *args):
        output = StringIO()
        call_command("simulation_clock", *args, stdout=output, stderr=output)
        return output.getvalue()

    def test_status_reports_inactive_clock_without_creating_one(self):
        with patch(
            "tracker.management.commands.simulation_clock.timezone.now",
            return_value=WALL_START,
        ):
            output = self.run_command("--status")
        self.assertIn("Simulation clock: inactive", output)
        self.assertIn("Wall time: 2030-01-01T09:00:00Z", output)
        self.assertEqual(SimulationClock.objects.count(), 0)

    def test_command_controls_and_reports_clock(self):
        reset_simulation_clock(
            seed=20260719,
            schedule_anchor=ANCHOR,
            wall_time=WALL_START,
        )
        command_time = WALL_START + timedelta(minutes=5)
        with patch(
            "tracker.management.commands.simulation_clock.timezone.now",
            return_value=command_time,
        ):
            speed_output = self.run_command("--speed", "5")
            pause_output = self.run_command("--pause")
            status_output = self.run_command("--status")
            resume_output = self.run_command("--resume")
            reset_output = self.run_command("--reset")
        self.assertIn("Speed: 5.00x", speed_output)
        self.assertIn("Paused: yes", pause_output)
        self.assertIn("Simulation time:", status_output)
        self.assertIn("Paused: no", resume_output)
        self.assertIn("Simulation time: 2026-07-19T12:00:00Z", reset_output)

    def test_command_rejects_missing_clock_and_invalid_speed(self):
        with self.assertRaises(CommandError):
            self.run_command("--pause")
        reset_simulation_clock(
            seed=20260719,
            schedule_anchor=ANCHOR,
            wall_time=WALL_START,
        )
        with self.assertRaises(CommandError):
            self.run_command("--speed", "0")
        with self.assertRaises(CommandError):
            self.run_command("--speed", "1001")

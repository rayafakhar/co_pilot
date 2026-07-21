"""Administrative controls for the persistent simulation clock."""

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tracker.services.clock import (
    ClockConfigurationError,
    get_simulation_clock,
    pause_simulation_clock,
    reset_simulation_clock,
    resume_simulation_clock,
    set_simulation_speed,
    simulation_time_for_clock,
)
from tracker.services.presentation import utc_iso


class Command(BaseCommand):
    help = "Inspect or control the server-authoritative simulation clock"

    def add_arguments(self, parser):
        operations = parser.add_mutually_exclusive_group(required=True)
        operations.add_argument("--status", action="store_true")
        operations.add_argument("--pause", action="store_true")
        operations.add_argument("--resume", action="store_true")
        operations.add_argument("--speed", type=Decimal, metavar="MULTIPLIER")
        operations.add_argument("--reset", action="store_true")

    def handle(self, *args, **options):
        wall_time = timezone.now()
        try:
            if options["status"]:
                clock = get_simulation_clock()
                if clock is None:
                    self.stdout.write("Simulation clock: inactive")
                    self.stdout.write(f"Wall time: {utc_iso(wall_time)}")
                    return
            elif options["pause"]:
                clock = pause_simulation_clock(wall_time=wall_time)
            elif options["resume"]:
                clock = resume_simulation_clock(wall_time=wall_time)
            elif options["speed"] is not None:
                clock = set_simulation_speed(options["speed"], wall_time=wall_time)
            else:
                clock = reset_simulation_clock(wall_time=wall_time)
        except ClockConfigurationError as exc:
            raise CommandError(str(exc)) from exc

        simulation_time = simulation_time_for_clock(clock, wall_time=wall_time)
        self.stdout.write("Simulation clock: active")
        self.stdout.write(f"Wall time: {utc_iso(wall_time)}")
        self.stdout.write(f"Simulation time: {utc_iso(simulation_time)}")
        self.stdout.write(f"Schedule anchor: {utc_iso(clock.schedule_anchor)}")
        self.stdout.write(f"Seed: {clock.seed}")
        self.stdout.write(f"Speed: {clock.speed_multiplier}x")
        self.stdout.write(f"Paused: {'yes' if clock.paused else 'no'}")

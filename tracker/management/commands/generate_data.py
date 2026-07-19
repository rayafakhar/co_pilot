"""CLI for deterministic schedule generation and invariant validation."""

from datetime import date, datetime, time, timezone

from django.core.management.base import BaseCommand, CommandError

from tracker.models import Flight, MaintenanceBlock
from tracker.services.generator import (
    GenerationConfig,
    ScheduleGenerationError,
    generate_schedule,
)
from tracker.services.validation import validate_schedule, violation_counts


class Command(BaseCommand):
    help = "Generate reproducible aircraft itineraries for the aviation showcase"

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=int, default=20260719)
        parser.add_argument(
            "--anchor-date",
            type=date.fromisoformat,
            help="UTC schedule anchor as YYYY-MM-DD (defaults deterministically from seed)",
        )
        parser.add_argument(
            "--clear", action="store_true", help="Delete existing simulation data first"
        )
        parser.add_argument("--aircraft-count", type=int, default=12)
        parser.add_argument("--days-back", type=int, default=3)
        parser.add_argument("--days-forward", type=int, default=7)
        parser.add_argument("--min-flights-per-aircraft", type=int, default=4)
        parser.add_argument("--max-flights-per-aircraft", type=int, default=10)
        parser.add_argument("--delay-rate", type=float, default=0.18)
        parser.add_argument("--cancellation-rate", type=float, default=0.04)
        parser.add_argument("--diversion-rate", type=float, default=0.03)
        parser.add_argument("--ferry-rate", type=float, default=0.08)
        parser.add_argument("--maintenance-rate", type=float, default=0.06)
        parser.add_argument(
            "--validate-only",
            action="store_true",
            help="Validate stored schedules without changing the database",
        )

    def handle(self, *args, **options):
        if options["validate_only"]:
            if options["clear"]:
                raise CommandError("--validate-only cannot be combined with --clear")
            self._validate_stored_schedule()
            return

        config = GenerationConfig(
            seed=options["seed"],
            anchor_time=(
                datetime.combine(options["anchor_date"], time(12), tzinfo=timezone.utc)
                if options["anchor_date"]
                else None
            ),
            clear=options["clear"],
            aircraft_count=options["aircraft_count"],
            days_back=options["days_back"],
            days_forward=options["days_forward"],
            min_flights_per_aircraft=options["min_flights_per_aircraft"],
            max_flights_per_aircraft=options["max_flights_per_aircraft"],
            delay_rate=options["delay_rate"],
            cancellation_rate=options["cancellation_rate"],
            diversion_rate=options["diversion_rate"],
            ferry_rate=options["ferry_rate"],
            maintenance_rate=options["maintenance_rate"],
        )
        try:
            report = generate_schedule(config)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        except ScheduleGenerationError as exc:
            for violation in exc.violations:
                self.stderr.write(
                    f"{violation.code}: {violation.aircraft_registration} "
                    f"{violation.flight_number} - {violation.message}"
                )
            raise CommandError("Schedule validation failed; transaction rolled back.") from exc

        zero_codes = ("maintenance", "overlap", "continuity", "range")
        values = {
            "airports created": report.airports_created,
            "aircraft types created": report.aircraft_types_created,
            "aircraft created": report.aircraft_created,
            "flights created": report.flights_created,
            "maintenance blocks created": report.maintenance_blocks_created,
            "completed flights": report.completed_flights,
            "active flights": report.active_flights,
            "future flights": report.future_flights,
            "delayed flights": report.delayed_flights,
            "cancelled flights": report.cancelled_flights,
            "diverted flights": report.diverted_flights,
            "ferry flights": report.ferry_flights,
            **{
                f"{code} violations"
                if code != "maintenance"
                else "maintenance conflicts": report.violation_totals.get(code, 0)
                for code in zero_codes
            },
            "seed used": report.seed,
            "UTC anchor": report.anchor_time.isoformat(),
        }
        self.stdout.write(self.style.SUCCESS("Schedule generation complete"))
        for label, value in values.items():
            self.stdout.write(f"{label}: {value}")

    def _validate_stored_schedule(self):
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
        violations = validate_schedule(flights, blocks)
        if violations:
            counts = violation_counts(violations)
            for code, count in sorted(counts.items()):
                self.stderr.write(f"{code}: {count}")
            raise CommandError(f"Stored schedule contains {len(violations)} violation(s).")
        self.stdout.write(self.style.SUCCESS(f"Validated {len(flights)} flights: 0 violations"))

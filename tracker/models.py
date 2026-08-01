"""Core aviation-domain models for the simulated operations showcase."""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q

from .validators import validate_iana_timezone, validate_iata_code, validate_icao_code


class SimulationClock(models.Model):
    """Singleton configuration for server-authoritative simulation time."""

    seed = models.BigIntegerField()
    schedule_anchor = models.DateTimeField()
    wall_clock_started_at = models.DateTimeField()
    speed_multiplier = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("1.00"),
    )
    paused = models.BooleanField(default=False)
    paused_simulation_time = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(speed_multiplier__gt=0),
                name="simulation_clock_speed_positive",
            ),
            models.CheckConstraint(
                condition=(
                    Q(paused=True, paused_simulation_time__isnull=False)
                    | Q(paused=False, paused_simulation_time__isnull=True)
                ),
                name="simulation_clock_pause_state_consistent",
            ),
        ]

    def __str__(self) -> str:
        state = "paused" if self.paused else "running"
        return f"Simulation clock ({state} at {self.speed_multiplier}x)"


class Airport(models.Model):
    """An airport with real-world location and timezone metadata."""

    name = models.CharField(max_length=255)
    city = models.CharField(max_length=120)
    country = models.CharField(max_length=120)
    iata_code = models.CharField(
        max_length=3, unique=True, null=True, blank=True, validators=[validate_iata_code]
    )
    icao_code = models.CharField(
        max_length=4, unique=True, null=True, blank=True, validators=[validate_icao_code]
    )
    timezone = models.CharField(max_length=64, default="UTC", validators=[validate_iana_timezone])
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    minimum_connection_minutes = models.PositiveSmallIntegerField(default=45)

    class Meta:
        ordering = ["iata_code", "name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(minimum_connection_minutes__gt=0),
                name="airport_connection_minutes_positive",
            )
        ]

    @property
    def display_code(self) -> str:
        return self.iata_code or self.icao_code or "---"

    def clean(self) -> None:
        super().clean()
        self.iata_code = self.iata_code.upper() if self.iata_code else None
        self.icao_code = self.icao_code.upper() if self.icao_code else None
        if (self.latitude is None) != (self.longitude is None):
            raise ValidationError("Latitude and longitude must be provided together.")

    def __str__(self) -> str:
        codes = "/".join(code for code in (self.iata_code, self.icao_code) if code)
        return f"{self.city}, {self.country} - {codes or self.name}"


class AircraftType(models.Model):
    """Reusable performance and physical characteristics for an aircraft family."""

    class Category(models.TextChoices):
        NARROW_BODY = "narrow_body", "Narrow-body"
        WIDE_BODY = "wide_body", "Wide-body"
        REGIONAL = "regional", "Regional"
        TURBOPROP = "turboprop", "Turboprop"

    manufacturer = models.CharField(max_length=80)
    model = models.CharField(max_length=80)
    icao_type_code = models.CharField(max_length=4, unique=True, validators=[validate_icao_code])
    category = models.CharField(max_length=20, choices=Category.choices)
    typical_cruise_speed_kmh = models.PositiveSmallIntegerField()
    maximum_range_km = models.PositiveIntegerField()
    minimum_turnaround_minutes = models.PositiveSmallIntegerField()
    passenger_capacity = models.PositiveSmallIntegerField()
    crew_count = models.PositiveSmallIntegerField(default=6)
    wingspan_m = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    length_m = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    image = models.CharField(
        max_length=255,
        default="tracker/images/aircraft-silhouette.svg",
        help_text="Repository-local static asset path; remote hotlinks are not accepted.",
    )
    image_alt_text = models.CharField(max_length=255, default="Side profile aircraft silhouette")
    image_source_url = models.URLField(blank=True)
    image_author = models.CharField(max_length=160, blank=True)
    image_license = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["manufacturer", "model"]
        constraints = [
            models.CheckConstraint(
                condition=Q(typical_cruise_speed_kmh__gt=0), name="aircraft_type_speed_positive"
            ),
            models.CheckConstraint(
                condition=Q(maximum_range_km__gt=0), name="aircraft_type_range_positive"
            ),
            models.CheckConstraint(
                condition=Q(minimum_turnaround_minutes__gt=0),
                name="aircraft_type_turnaround_positive",
            ),
            models.CheckConstraint(
                condition=Q(passenger_capacity__gt=0), name="aircraft_type_capacity_positive"
            ),
        ]

    def clean(self) -> None:
        super().clean()
        self.icao_type_code = self.icao_type_code.upper()
        if self.image.startswith(("http://", "https://")):
            raise ValidationError({"image": "Use a repository-local image path, not a remote URL."})

    def __str__(self) -> str:
        return f"{self.manufacturer} {self.model} ({self.icao_type_code})"


class Aircraft(models.Model):
    """An individually registered aircraft that owns a chronological flight chain."""

    class MaintenanceStatus(models.TextChoices):
        AVAILABLE = "available", "Available"
        SCHEDULED = "scheduled", "Maintenance scheduled"
        IN_MAINTENANCE = "maintenance", "In maintenance"
        GROUNDED = "grounded", "Grounded"

    registration = models.CharField(max_length=20, unique=True)
    display_name = models.CharField(max_length=255)
    aircraft_type = models.ForeignKey(
        AircraftType, on_delete=models.PROTECT, related_name="aircraft"
    )
    operator = models.CharField(max_length=120, default="Northstar Demo Air")
    base_airport = models.ForeignKey(
        Airport, on_delete=models.SET_NULL, null=True, blank=True, related_name="based_aircraft"
    )
    manufactured_year = models.PositiveSmallIntegerField(null=True, blank=True)
    serial_number = models.CharField(max_length=80, blank=True)
    active = models.BooleanField(default=True)
    maintenance_status = models.CharField(
        max_length=20,
        choices=MaintenanceStatus.choices,
        default=MaintenanceStatus.AVAILABLE,
        db_index=True,
    )
    last_known_airport = models.ForeignKey(
        Airport, on_delete=models.SET_NULL, null=True, blank=True, related_name="parked_aircraft"
    )

    class Meta:
        ordering = ["registration"]
        verbose_name_plural = "Aircraft"
        indexes = [models.Index(fields=["active", "maintenance_status"], name="aircraft_state_idx")]

    def clean(self) -> None:
        super().clean()
        self.registration = self.registration.upper()
        if self.manufactured_year and not 1950 <= self.manufactured_year <= 2100:
            raise ValidationError({"manufactured_year": "Enter a plausible manufacture year."})

    def __str__(self) -> str:
        return f"{self.registration} - {self.display_name}"


class Flight(models.Model):
    """A passenger or operational movement in an aircraft's itinerary."""

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        CHECK_IN = "check_in", "Check-in"
        BOARDING = "boarding", "Boarding"
        GATE_CLOSED = "gate_closed", "Gate closed"
        DELAYED = "delayed", "Delayed"
        DEPARTED = "departed", "Departed"
        EN_ROUTE = "en_route", "En route"
        LANDED = "landed", "Landed"
        ARRIVED = "arrived", "Arrived"
        CANCELLED = "cancelled", "Cancelled"
        DIVERTED = "diverted", "Diverted"

    class FlightType(models.TextChoices):
        PASSENGER = "passenger", "Passenger"
        CARGO = "cargo", "Cargo"
        FERRY = "ferry", "Ferry / repositioning"
        TRAINING = "training", "Training"
        MAINTENANCE_POSITIONING = "maintenance_positioning", "Maintenance positioning"

    flight_number = models.CharField(max_length=16, unique=True)
    aircraft = models.ForeignKey(Aircraft, on_delete=models.CASCADE, related_name="flights")
    departure_airport = models.ForeignKey(
        Airport, on_delete=models.PROTECT, related_name="departing_flights"
    )
    arrival_airport = models.ForeignKey(
        Airport, on_delete=models.PROTECT, related_name="arriving_flights"
    )
    scheduled_departure = models.DateTimeField(db_index=True)
    scheduled_arrival = models.DateTimeField(db_index=True)
    estimated_departure = models.DateTimeField(null=True, blank=True)
    estimated_arrival = models.DateTimeField(null=True, blank=True)
    actual_departure = models.DateTimeField(null=True, blank=True)
    actual_arrival = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.SCHEDULED, db_index=True
    )
    flight_type = models.CharField(
        max_length=30, choices=FlightType.choices, default=FlightType.PASSENGER
    )
    distance_km = models.PositiveIntegerField(default=0)
    planned_duration_minutes = models.PositiveIntegerField()
    delay_minutes = models.PositiveIntegerField(default=0)
    departure_terminal = models.CharField(max_length=8, blank=True)
    departure_gate = models.CharField(max_length=8, blank=True)
    arrival_terminal = models.CharField(max_length=8, blank=True)
    arrival_gate = models.CharField(max_length=8, blank=True)
    cancelled_reason = models.CharField(max_length=255, blank=True)
    diversion_airport = models.ForeignKey(
        Airport, on_delete=models.PROTECT, null=True, blank=True, related_name="diverted_flights"
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scheduled_departure", "flight_number"]
        indexes = [
            models.Index(
                fields=["aircraft", "scheduled_departure"], name="flight_aircraft_dep_idx"
            ),
            models.Index(fields=["status", "scheduled_departure"], name="flight_status_dep_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(departure_airport=F("arrival_airport")), name="flight_airports_differ"
            ),
            models.CheckConstraint(
                condition=Q(scheduled_arrival__gt=F("scheduled_departure")),
                name="flight_scheduled_times_ordered",
            ),
            models.CheckConstraint(
                condition=(
                    Q(estimated_departure__isnull=True, estimated_arrival__isnull=True)
                    | Q(
                        estimated_departure__isnull=False,
                        estimated_arrival__isnull=False,
                        estimated_arrival__gt=F("estimated_departure"),
                    )
                ),
                name="flight_estimated_times_ordered",
            ),
            models.CheckConstraint(
                condition=(
                    Q(actual_departure__isnull=True, actual_arrival__isnull=True)
                    | Q(
                        actual_departure__isnull=False,
                        actual_arrival__isnull=False,
                        actual_arrival__gt=F("actual_departure"),
                    )
                    | Q(actual_departure__isnull=False, actual_arrival__isnull=True)
                ),
                name="flight_actual_times_ordered",
            ),
            models.CheckConstraint(
                condition=Q(planned_duration_minutes__gt=0), name="flight_duration_positive"
            ),
        ]

    def clean(self) -> None:
        super().clean()
        self.flight_number = self.flight_number.upper()
        errors: dict[str, str] = {}
        if self.departure_airport_id == self.arrival_airport_id:
            errors["arrival_airport"] = "Arrival airport must differ from departure airport."
        if (
            self.scheduled_departure
            and self.scheduled_arrival
            and self.scheduled_arrival <= self.scheduled_departure
        ):
            errors["scheduled_arrival"] = "Scheduled arrival must follow departure."
        for prefix in ("estimated", "actual"):
            departure = getattr(self, f"{prefix}_departure")
            arrival = getattr(self, f"{prefix}_arrival")
            if arrival and not departure:
                errors[f"{prefix}_departure"] = f"{prefix.title()} departure is required."
            if departure and arrival and arrival <= departure:
                errors[f"{prefix}_arrival"] = f"{prefix.title()} arrival must follow departure."
        if self.status == self.Status.CANCELLED and (
            self.actual_departure or self.actual_arrival or self.diversion_airport_id
        ):
            errors["status"] = (
                "A cancelled flight cannot contain movement timestamps or a diversion."
            )
        if self.diversion_airport_id in {self.departure_airport_id, self.arrival_airport_id}:
            errors["diversion_airport"] = (
                "Diversion airport must differ from both planned airports."
            )
        if self.diversion_airport_id and self.status != self.Status.DIVERTED:
            errors["status"] = "A flight with a diversion airport must use diverted status."
        if errors:
            raise ValidationError(errors)

    @property
    def current_status(self) -> str:
        from .services.status import get_flight_status

        return get_flight_status(self).label

    def __str__(self) -> str:
        return (
            f"{self.flight_number}: {self.departure_airport.display_code} -> "
            f"{self.arrival_airport.display_code}"
        )


class MaintenanceBlock(models.Model):
    """A period during which an aircraft cannot operate a flight."""

    aircraft = models.ForeignKey(
        Aircraft, on_delete=models.CASCADE, related_name="maintenance_blocks"
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    reason = models.CharField(max_length=255, default="Scheduled inspection")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["starts_at"]
        indexes = [
            models.Index(fields=["aircraft", "starts_at", "ends_at"], name="maintenance_window_idx")
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")), name="maintenance_times_ordered"
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "Maintenance must end after it starts."})

    def __str__(self) -> str:
        return f"{self.aircraft.registration}: {self.reason}"


class CrewMember(models.Model):
    class Role(models.TextChoices):
        PILOT = "pilot", "Pilot"
        FLIGHT_ATTENDANT = "flight_attendant", "Flight Attendant"

    first_name = models.CharField(max_length=120)
    last_name = models.CharField(max_length=120)
    role = models.CharField(max_length=20, choices=Role.choices)

    profile_picture = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Repository-local static path for crew profile avatar SVG.",
    )

    class Meta:
        ordering = ["last_name", "first_name", "role"]
        verbose_name = "Crew member"
        verbose_name_plural = "Crew members"

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name} ({self.get_role_display()})"

    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    full_name.short_description = "Full Name"


class FlightCrew(models.Model):
    """Through table linking crew members to flights with uniqueness enforcement."""

    flight = models.ForeignKey(Flight, on_delete=models.CASCADE, related_name="flight_crew")
    crew_member = models.ForeignKey(
        CrewMember, on_delete=models.CASCADE, related_name="assigned_flights"
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["flight", "crew_member"],
                name="unique_crew_flight_assignment",
            )
        ]
        ordering = ["crew_member__last_name", "crew_member__first_name"]

    def __str__(self) -> str:
        return f"{self.crew_member} → {self.flight.flight_number}"

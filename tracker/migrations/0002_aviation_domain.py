"""Expand the legacy showcase schema without deleting existing records."""

import django.core.validators
import django.db.models.deletion
import django.utils.timezone
import tracker.validators
from django.db import migrations, models


def backfill_legacy_records(apps, schema_editor):
    Airport = apps.get_model("tracker", "Airport")
    AircraftType = apps.get_model("tracker", "AircraftType")
    Aircraft = apps.get_model("tracker", "Aircraft")
    Flight = apps.get_model("tracker", "Flight")

    legacy_type, _ = AircraftType.objects.get_or_create(
        icao_type_code="LGCY",
        defaults={
            "manufacturer": "Legacy",
            "model": "Imported aircraft",
            "category": "narrow_body",
            "typical_cruise_speed_kmh": 800,
            "maximum_range_km": 6000,
            "minimum_turnaround_minutes": 45,
            "passenger_capacity": 150,
            "crew_count": 6,
        },
    )
    for airport in Airport.objects.all():
        airport.city = airport.name
        airport.country = "Unknown"
        airport.save(update_fields=["city", "country"])

    for aircraft in Aircraft.objects.all():
        flights = Flight.objects.filter(aircraft_id=aircraft.pk).order_by("scheduled_departure")
        first = flights.first()
        last = flights.last()
        aircraft.aircraft_type_id = legacy_type.pk
        aircraft.base_airport_id = first.departure_airport_id if first else None
        aircraft.last_known_airport_id = last.arrival_airport_id if last else aircraft.base_airport_id
        aircraft.save(update_fields=["aircraft_type", "base_airport", "last_known_airport"])

    now = django.utils.timezone.now()
    for flight in Flight.objects.all():
        duration = max(1, round((flight.scheduled_arrival - flight.scheduled_departure).total_seconds() / 60))
        if now >= flight.scheduled_arrival:
            status = "arrived"
        elif now >= flight.scheduled_departure:
            status = "en_route"
        else:
            status = "scheduled"
        flight.flight_number = f"LEG{flight.pk:06d}"
        flight.planned_duration_minutes = duration
        flight.status = status
        flight.save(update_fields=["flight_number", "planned_duration_minutes", "status"])


class Migration(migrations.Migration):
    dependencies = [("tracker", "0001_initial")]

    operations = [
        migrations.RenameModel(old_name="Airplane", new_name="Aircraft"),
        migrations.RenameModel(old_name="Track", new_name="Flight"),
        migrations.RenameField(model_name="aircraft", old_name="name", new_name="display_name"),
        migrations.RenameField(model_name="aircraft", old_name="tail_number", new_name="registration"),
        migrations.RenameField(model_name="flight", old_name="airplane", new_name="aircraft"),
        migrations.RenameField(model_name="airport", old_name="code", new_name="iata_code"),
        migrations.AlterModelOptions(name="airport", options={"ordering": ["iata_code", "name"]}),
        migrations.AlterModelOptions(
            name="aircraft", options={"ordering": ["registration"], "verbose_name_plural": "Aircraft"}
        ),
        migrations.AlterModelOptions(name="flight", options={"ordering": ["scheduled_departure", "flight_number"]}),
        migrations.CreateModel(
            name="AircraftType",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("manufacturer", models.CharField(max_length=80)),
                ("model", models.CharField(max_length=80)),
                ("icao_type_code", models.CharField(max_length=4, unique=True, validators=[tracker.validators.validate_icao_code])),
                ("category", models.CharField(choices=[("narrow_body", "Narrow-body"), ("wide_body", "Wide-body"), ("regional", "Regional"), ("turboprop", "Turboprop")], max_length=20)),
                ("typical_cruise_speed_kmh", models.PositiveSmallIntegerField()),
                ("maximum_range_km", models.PositiveIntegerField()),
                ("minimum_turnaround_minutes", models.PositiveSmallIntegerField()),
                ("passenger_capacity", models.PositiveSmallIntegerField()),
                ("crew_count", models.PositiveSmallIntegerField(default=6)),
                ("wingspan_m", models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ("length_m", models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ("image", models.CharField(default="tracker/images/aircraft-silhouette.svg", help_text="Repository-local static asset path; remote hotlinks are not accepted.", max_length=255)),
                ("image_alt_text", models.CharField(default="Side profile aircraft silhouette", max_length=255)),
                ("image_source_url", models.URLField(blank=True)),
                ("image_author", models.CharField(blank=True, max_length=160)),
                ("image_license", models.CharField(blank=True, max_length=120)),
            ],
            options={"ordering": ["manufacturer", "model"]},
        ),
        migrations.AddField(model_name="airport", name="city", field=models.CharField(default="Unknown", max_length=120), preserve_default=False),
        migrations.AddField(model_name="airport", name="country", field=models.CharField(default="Unknown", max_length=120), preserve_default=False),
        migrations.AlterField(model_name="airport", name="iata_code", field=models.CharField(blank=True, max_length=3, null=True, unique=True, validators=[tracker.validators.validate_iata_code])),
        migrations.AddField(model_name="airport", name="icao_code", field=models.CharField(blank=True, max_length=4, null=True, unique=True, validators=[tracker.validators.validate_icao_code])),
        migrations.AddField(model_name="airport", name="latitude", field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True, validators=[django.core.validators.MinValueValidator(-90), django.core.validators.MaxValueValidator(90)])),
        migrations.AddField(model_name="airport", name="longitude", field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True, validators=[django.core.validators.MinValueValidator(-180), django.core.validators.MaxValueValidator(180)])),
        migrations.AddField(model_name="airport", name="minimum_connection_minutes", field=models.PositiveSmallIntegerField(default=45)),
        migrations.AddField(model_name="airport", name="timezone", field=models.CharField(default="UTC", max_length=64, validators=[tracker.validators.validate_iana_timezone])),
        migrations.AddField(model_name="aircraft", name="aircraft_type", field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="aircraft", to="tracker.aircrafttype")),
        migrations.AddField(model_name="aircraft", name="operator", field=models.CharField(default="Northstar Demo Air", max_length=120)),
        migrations.AddField(model_name="aircraft", name="base_airport", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="based_aircraft", to="tracker.airport")),
        migrations.AddField(model_name="aircraft", name="manufactured_year", field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="aircraft", name="serial_number", field=models.CharField(blank=True, max_length=80)),
        migrations.AddField(model_name="aircraft", name="active", field=models.BooleanField(default=True)),
        migrations.AddField(
            model_name="aircraft", name="maintenance_status",
            field=models.CharField(choices=[("available", "Available"), ("scheduled", "Maintenance scheduled"), ("maintenance", "In maintenance"), ("grounded", "Grounded")], db_index=True, default="available", max_length=20),
        ),
        migrations.AddField(model_name="aircraft", name="last_known_airport", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="parked_aircraft", to="tracker.airport")),
        migrations.AlterField(model_name="flight", name="aircraft", field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="flights", to="tracker.aircraft")),
        migrations.AlterField(model_name="flight", name="departure_airport", field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="departing_flights", to="tracker.airport")),
        migrations.AlterField(model_name="flight", name="arrival_airport", field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="arriving_flights", to="tracker.airport")),
        migrations.AddField(model_name="flight", name="flight_number", field=models.CharField(max_length=16, null=True, unique=True)),
        migrations.AddField(model_name="flight", name="estimated_departure", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="flight", name="estimated_arrival", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="flight", name="actual_departure", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="flight", name="actual_arrival", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="flight", name="status", field=models.CharField(choices=[("scheduled", "Scheduled"), ("check_in", "Check-in"), ("boarding", "Boarding"), ("gate_closed", "Gate closed"), ("delayed", "Delayed"), ("departed", "Departed"), ("en_route", "En route"), ("landed", "Landed"), ("arrived", "Arrived"), ("cancelled", "Cancelled"), ("diverted", "Diverted")], db_index=True, default="scheduled", max_length=20)),
        migrations.AddField(model_name="flight", name="flight_type", field=models.CharField(choices=[("passenger", "Passenger"), ("cargo", "Cargo"), ("ferry", "Ferry / repositioning"), ("training", "Training"), ("maintenance_positioning", "Maintenance positioning")], default="passenger", max_length=30)),
        migrations.AddField(model_name="flight", name="distance_km", field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name="flight", name="planned_duration_minutes", field=models.PositiveIntegerField(default=1), preserve_default=False),
        migrations.AddField(model_name="flight", name="delay_minutes", field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name="flight", name="departure_terminal", field=models.CharField(blank=True, max_length=8)),
        migrations.AddField(model_name="flight", name="departure_gate", field=models.CharField(blank=True, max_length=8)),
        migrations.AddField(model_name="flight", name="arrival_terminal", field=models.CharField(blank=True, max_length=8)),
        migrations.AddField(model_name="flight", name="arrival_gate", field=models.CharField(blank=True, max_length=8)),
        migrations.AddField(model_name="flight", name="cancelled_reason", field=models.CharField(blank=True, max_length=255)),
        migrations.AddField(model_name="flight", name="diversion_airport", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="diverted_flights", to="tracker.airport")),
        migrations.AddField(model_name="flight", name="notes", field=models.TextField(blank=True)),
        migrations.AddField(model_name="flight", name="created_at", field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now), preserve_default=False),
        migrations.AddField(model_name="flight", name="updated_at", field=models.DateTimeField(auto_now=True)),
        migrations.CreateModel(
            name="MaintenanceBlock",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("starts_at", models.DateTimeField()),
                ("ends_at", models.DateTimeField()),
                ("reason", models.CharField(default="Scheduled inspection", max_length=255)),
                ("notes", models.TextField(blank=True)),
                ("aircraft", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="maintenance_blocks", to="tracker.aircraft")),
            ],
            options={"ordering": ["starts_at"]},
        ),
        migrations.RunPython(backfill_legacy_records, migrations.RunPython.noop),
        migrations.AlterField(model_name="aircraft", name="aircraft_type", field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="aircraft", to="tracker.aircrafttype")),
        migrations.AlterField(model_name="flight", name="flight_number", field=models.CharField(max_length=16, unique=True)),
        migrations.AddConstraint(model_name="airport", constraint=models.CheckConstraint(condition=models.Q(("minimum_connection_minutes__gt", 0)), name="airport_connection_minutes_positive")),
        migrations.AddConstraint(model_name="aircrafttype", constraint=models.CheckConstraint(condition=models.Q(("typical_cruise_speed_kmh__gt", 0)), name="aircraft_type_speed_positive")),
        migrations.AddConstraint(model_name="aircrafttype", constraint=models.CheckConstraint(condition=models.Q(("maximum_range_km__gt", 0)), name="aircraft_type_range_positive")),
        migrations.AddConstraint(model_name="aircrafttype", constraint=models.CheckConstraint(condition=models.Q(("minimum_turnaround_minutes__gt", 0)), name="aircraft_type_turnaround_positive")),
        migrations.AddConstraint(model_name="aircrafttype", constraint=models.CheckConstraint(condition=models.Q(("passenger_capacity__gt", 0)), name="aircraft_type_capacity_positive")),
        migrations.AddIndex(model_name="aircraft", index=models.Index(fields=["active", "maintenance_status"], name="aircraft_state_idx")),
        migrations.AddIndex(model_name="flight", index=models.Index(fields=["aircraft", "scheduled_departure"], name="flight_aircraft_dep_idx")),
        migrations.AddIndex(model_name="flight", index=models.Index(fields=["status", "scheduled_departure"], name="flight_status_dep_idx")),
        migrations.AddConstraint(model_name="flight", constraint=models.CheckConstraint(condition=models.Q(("departure_airport", models.F("arrival_airport")), _negated=True), name="flight_airports_differ")),
        migrations.AddConstraint(model_name="flight", constraint=models.CheckConstraint(condition=models.Q(("scheduled_arrival__gt", models.F("scheduled_departure"))), name="flight_scheduled_times_ordered")),
        migrations.AddConstraint(
            model_name="flight",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("estimated_arrival__isnull", True), ("estimated_departure__isnull", True)),
                    models.Q(("estimated_arrival__gt", models.F("estimated_departure")), ("estimated_arrival__isnull", False), ("estimated_departure__isnull", False)),
                    _connector="OR",
                ),
                name="flight_estimated_times_ordered",
            ),
        ),
        migrations.AddConstraint(
            model_name="flight",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("actual_arrival__isnull", True), ("actual_departure__isnull", True)),
                    models.Q(("actual_arrival__gt", models.F("actual_departure")), ("actual_arrival__isnull", False), ("actual_departure__isnull", False)),
                    models.Q(("actual_arrival__isnull", True), ("actual_departure__isnull", False)),
                    _connector="OR",
                ),
                name="flight_actual_times_ordered",
            ),
        ),
        migrations.AddConstraint(model_name="flight", constraint=models.CheckConstraint(condition=models.Q(("planned_duration_minutes__gt", 0)), name="flight_duration_positive")),
        migrations.AddIndex(model_name="maintenanceblock", index=models.Index(fields=["aircraft", "starts_at", "ends_at"], name="maintenance_window_idx")),
        migrations.AddConstraint(model_name="maintenanceblock", constraint=models.CheckConstraint(condition=models.Q(("ends_at__gt", models.F("starts_at"))), name="maintenance_times_ordered")),
    ]

"""Focused Django admin for simulated aviation operations."""

from django import forms
from django.contrib import admin

from .models import (
    Aircraft,
    AircraftType,
    Airport,
    CrewMember,
    Flight,
    FlightCrew,
    MaintenanceBlock,
)
from .services.validation import validate_schedule


class DelayListFilter(admin.SimpleListFilter):
    title = "delay"
    parameter_name = "delay_state"

    def lookups(self, request, model_admin):
        return (("delayed", "Has a delay"), ("on_time", "No recorded delay"))

    def queryset(self, request, queryset):
        if self.value() == "delayed":
            return queryset.filter(delay_minutes__gt=0)
        if self.value() == "on_time":
            return queryset.filter(delay_minutes=0)
        return queryset


class FlightAdminForm(forms.ModelForm):
    """Surface cross-flight invariant failures before an admin save."""

    class Meta:
        model = Flight
        fields = "__all__"

    def _post_clean(self):
        super()._post_clean()
        item = self.instance
        if self.errors or not item.aircraft_id:
            return
        flights = list(
            Flight.objects.filter(aircraft_id=item.aircraft_id)
            .exclude(pk=item.pk)
            .select_related(
                "aircraft__aircraft_type",
                "aircraft__base_airport",
                "departure_airport",
                "arrival_airport",
                "diversion_airport",
            )
        )
        blocks = list(MaintenanceBlock.objects.filter(aircraft_id=item.aircraft_id))
        violations = validate_schedule([*flights, item], blocks)
        if violations:
            summary = "; ".join(
                f"{violation.code}: {violation.flight_number} {violation.message}"
                for violation in violations[:6]
            )
            self.add_error(None, f"Schedule validation failed: {summary}")


class MaintenanceBlockAdminForm(forms.ModelForm):
    """Prevent an admin maintenance window from covering a stored operation."""

    class Meta:
        model = MaintenanceBlock
        fields = "__all__"

    def _post_clean(self):
        super()._post_clean()
        item = self.instance
        if self.errors or not item.aircraft_id:
            return
        flights = list(
            Flight.objects.filter(aircraft_id=item.aircraft_id).select_related(
                "aircraft__aircraft_type",
                "aircraft__base_airport",
                "departure_airport",
                "arrival_airport",
                "diversion_airport",
            )
        )
        blocks = list(
            MaintenanceBlock.objects.filter(aircraft_id=item.aircraft_id).exclude(pk=item.pk)
        )
        violations = [
            violation
            for violation in validate_schedule(flights, [*blocks, item])
            if violation.code == "maintenance"
        ]
        if violations:
            flights_text = ", ".join(violation.flight_number for violation in violations[:6])
            self.add_error(
                None,
                f"Maintenance overlaps scheduled operation(s): {flights_text}.",
            )


@admin.register(Airport)
class AirportAdmin(admin.ModelAdmin):
    list_display = ("iata_code", "icao_code", "name", "city", "country", "timezone")
    list_filter = ("country", "timezone")
    search_fields = ("name", "city", "country", "iata_code", "icao_code")


@admin.register(AircraftType)
class AircraftTypeAdmin(admin.ModelAdmin):
    list_display = ("icao_type_code", "manufacturer", "model", "category", "maximum_range_km")
    list_filter = ("category", "manufacturer")
    search_fields = ("icao_type_code", "manufacturer", "model")


@admin.register(Aircraft)
class AircraftAdmin(admin.ModelAdmin):
    list_display = (
        "registration",
        "display_name",
        "aircraft_type",
        "operator",
        "maintenance_status",
    )
    list_filter = ("active", "maintenance_status", "aircraft_type")
    search_fields = ("display_name", "registration", "operator")
    list_select_related = ("aircraft_type", "base_airport", "last_known_airport")


@admin.register(Flight)
class FlightAdmin(admin.ModelAdmin):
    form = FlightAdminForm
    list_display = (
        "flight_number",
        "aircraft",
        "route",
        "scheduled_departure",
        "status_at_server_time",
        "delay_minutes",
    )
    list_filter = ("status", "flight_type", DelayListFilter, "aircraft", "scheduled_departure")
    search_fields = (
        "flight_number",
        "aircraft__display_name",
        "aircraft__registration",
        "departure_airport__iata_code",
        "arrival_airport__iata_code",
    )
    list_select_related = (
        "aircraft",
        "aircraft__aircraft_type",
        "departure_airport",
        "arrival_airport",
        "diversion_airport",
    )
    date_hierarchy = "scheduled_departure"
    readonly_fields = ("created_at", "updated_at", "status_at_server_time", "route")

    @admin.display(description="Route", ordering="departure_airport__iata_code")
    def route(self, obj):
        return f"{obj.departure_airport.display_code} -> {obj.arrival_airport.display_code}"

    @admin.display(description="Derived status")
    def status_at_server_time(self, obj):
        if not obj.pk:
            return "Calculated after save"
        return obj.current_status


@admin.register(CrewMember)
class CrewMemberAdmin(admin.ModelAdmin):
    list_display = ("full_name", "role", "has_profile_picture")
    list_filter = ("role",)
    search_fields = ("first_name", "last_name", "role")

    @admin.display(boolean=True, description="Has Profile Picture")
    def has_profile_picture(self, obj):
        return bool(obj.profile_picture)


@admin.register(FlightCrew)
class FlightCrewAdmin(admin.ModelAdmin):
    list_display = ("crew_member", "flight", "crew_role")
    list_select_related = ("crew_member", "flight")
    search_fields = ("crew_member__first_name", "crew_member__last_name", "flight__flight_number")

    @admin.display(description="Role")
    def crew_role(self, obj):
        return obj.crew_member.role


@admin.register(MaintenanceBlock)
class MaintenanceBlockAdmin(admin.ModelAdmin):
    form = MaintenanceBlockAdminForm
    list_display = ("aircraft", "starts_at", "ends_at", "reason")
    list_select_related = ("aircraft",)
    search_fields = ("aircraft__registration", "reason")

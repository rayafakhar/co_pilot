"""Focused Django admin for simulated aviation operations."""

from django.contrib import admin

from .models import Aircraft, AircraftType, Airport, Flight, MaintenanceBlock


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
    list_display = ("registration", "display_name", "aircraft_type", "operator", "maintenance_status")
    list_filter = ("active", "maintenance_status", "aircraft_type")
    search_fields = ("display_name", "registration", "operator")
    list_select_related = ("aircraft_type", "base_airport", "last_known_airport")


@admin.register(Flight)
class FlightAdmin(admin.ModelAdmin):
    list_display = ("flight_number", "aircraft", "route", "scheduled_departure", "status")
    list_filter = ("status", "flight_type", "aircraft", "scheduled_departure")
    search_fields = ("flight_number", "aircraft__display_name", "aircraft__registration")
    list_select_related = ("aircraft", "departure_airport", "arrival_airport")
    date_hierarchy = "scheduled_departure"

    @admin.display(description="Route", ordering="departure_airport__iata_code")
    def route(self, obj):
        return f"{obj.departure_airport.display_code} -> {obj.arrival_airport.display_code}"


@admin.register(MaintenanceBlock)
class MaintenanceBlockAdmin(admin.ModelAdmin):
    list_display = ("aircraft", "starts_at", "ends_at", "reason")
    list_select_related = ("aircraft",)
    search_fields = ("aircraft__registration", "reason")

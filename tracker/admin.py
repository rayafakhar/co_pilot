"""
Admin configuration for tracker app.
"""

from django.contrib import admin
from .models import Airport, Airplane, Track


@admin.register(Airport)
class AirportAdmin(admin.ModelAdmin):
    """Admin configuration for Airport model."""

    list_display = ('code', 'name')
    list_filter = ('code',)
    search_fields = ('name', 'code')


@admin.register(Airplane)
class AirplaneAdmin(admin.ModelAdmin):
    """Admin configuration for Airplane model."""

    list_display = ('tail_number', 'name')
    search_fields = ('name', 'tail_number')


@admin.register(Track)
class TrackAdmin(admin.ModelAdmin):
    """Admin configuration for Track model with optimized queries."""

    list_display = (
        'airplane',
        'route',
        'scheduled_departure',
        'scheduled_arrival',
        'current_status',
    )
    list_filter = ('airplane', 'scheduled_departure')
    search_fields = ('airplane__name', 'airplane__tail_number')
    list_select_related = (
        'airplane',
        'departure_airport',
        'arrival_airport',
    )
    date_hierarchy = 'scheduled_departure'

    def route(self, obj):
        """Display the route as departure → arrival."""
        return f"{obj.departure_airport.code} → {obj.arrival_airport.code}"
    route.short_description = 'Route'
    route.admin_order_field = 'departure_airport__code'

    def current_status(self, obj):
        """Display the current status of the track."""
        return obj.current_status
    current_status.short_description = 'Status'
    current_status.admin_order_field = 'scheduled_departure'
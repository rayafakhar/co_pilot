"""
Tracker models for airline portfolio showcase.
"""

from django.db import models
from django.utils import timezone


class Airport(models.Model):
    """Represents an airport with name and unique code."""

    name = models.CharField(max_length=255)
    code = models.CharField(max_length=4, unique=True)

    class Meta:
        ordering = ['code']
        verbose_name = 'Airport'
        verbose_name_plural = 'Airports'

    def __str__(self):
        return f"{self.name} ({self.code})"


class Airplane(models.Model):
    """Represents an airplane with name and tail number."""

    name = models.CharField(max_length=255)
    tail_number = models.CharField(max_length=20, unique=True)

    class Meta:
        ordering = ['tail_number']
        verbose_name = 'Airplane'
        verbose_name_plural = 'Airplanes'

    def __str__(self):
        return f"{self.tail_number} - {self.name}"


class Track(models.Model):
    """Represents a flight schedule/tracking entry."""

    airplane = models.ForeignKey(Airplane, on_delete=models.CASCADE, related_name='tracks')
    departure_airport = models.ForeignKey(
        Airport,
        on_delete=models.CASCADE,
        related_name='departure_tracks'
    )
    arrival_airport = models.ForeignKey(
        Airport,
        on_delete=models.CASCADE,
        related_name='arrival_tracks'
    )
    scheduled_departure = models.DateTimeField(db_index=True)
    scheduled_arrival = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ['-scheduled_departure']
        verbose_name = 'Track'
        verbose_name_plural = 'Tracks'

    def __str__(self):
        return (
            f"{self.airplane.tail_number}: "
            f"{self.departure_airport.code} → {self.arrival_airport.code}"
        )

    @property
    def current_status(self):
        """
        Calculate and return the current flight status.

        Returns:
            str: One of "Done", "In Route", "30 minutes till take off", or "Scheduled"
        """
        now = timezone.now()
        arrival_delta = now - self.scheduled_arrival
        departure_delta = now - self.scheduled_departure
        thirty_min_delta = timezone.timedelta(minutes=30)

        # Done: arrival time has passed (even by a small margin)
        if arrival_delta >= timezone.timedelta(seconds=0):
            return "Done"
        # In Route: departed but not yet arrived
        elif departure_delta > timezone.timedelta(seconds=0) and arrival_delta < timezone.timedelta(seconds=0):
            return "In Route"
        # 30 minutes till take off: within 30 min window before departure
        elif departure_delta < timezone.timedelta(seconds=0) and departure_delta >= -thirty_min_delta:
            return "30 minutes till take off"
        else:
            return "Scheduled"

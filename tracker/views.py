"""
Views for the tracker app.
"""

from django.shortcuts import render
from .models import Track


def flight_board(request):
    """
    Display a live airport departure board with all tracks.

    Uses select_related to optimize database queries and prevent
    the N+1 query problem when iterating related objects in templates.

    Args:
        request: HTTP request object

    Returns:
        Rendered template with optimized track queryset
    """
    tracks = Track.objects.select_related(
        'airplane',
        'departure_airport',
        'arrival_airport'
    ).order_by('scheduled_departure')

    context = {
        'tracks': tracks,
    }
    return render(request, 'tracker/flight_board.html', context)
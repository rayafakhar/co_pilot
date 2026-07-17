"""
URL configuration for the tracker app.
"""

from django.urls import path

from . import views

app_name = 'tracker'

urlpatterns = [
    path('', views.flight_board, name='flight_board'),
]
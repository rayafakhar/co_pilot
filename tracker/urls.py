"""
URL configuration for the tracker app.
"""

from django.urls import path

from . import views

app_name = "tracker"

urlpatterns = [
    path("", views.flight_board, name="flight_board"),
    path("board/data/", views.flight_board_data, name="flight_board_data"),
    path("aircraft/<str:registration>/", views.aircraft_detail, name="aircraft_detail"),
    path("flights/<str:flight_number>/", views.flight_detail, name="flight_detail"),
]

"""Small, transparent reference dataset for deterministic demo generation."""

from __future__ import annotations

from tracker.models import AircraftType, Airport

# Coordinates and performance values are rounded simulation inputs, not certified data.
AIRPORTS = (
    dict(
        name="John F. Kennedy International Airport",
        city="New York",
        country="United States",
        iata_code="JFK",
        icao_code="KJFK",
        timezone="America/New_York",
        latitude=40.6413,
        longitude=-73.7781,
        minimum_connection_minutes=75,
    ),
    dict(
        name="Heathrow Airport",
        city="London",
        country="United Kingdom",
        iata_code="LHR",
        icao_code="EGLL",
        timezone="Europe/London",
        latitude=51.4700,
        longitude=-0.4543,
        minimum_connection_minutes=75,
    ),
    dict(
        name="Haneda Airport",
        city="Tokyo",
        country="Japan",
        iata_code="HND",
        icao_code="RJTT",
        timezone="Asia/Tokyo",
        latitude=35.5494,
        longitude=139.7798,
        minimum_connection_minutes=60,
    ),
    dict(
        name="Dubai International Airport",
        city="Dubai",
        country="United Arab Emirates",
        iata_code="DXB",
        icao_code="OMDB",
        timezone="Asia/Dubai",
        latitude=25.2532,
        longitude=55.3657,
        minimum_connection_minutes=60,
    ),
    dict(
        name="Charles de Gaulle Airport",
        city="Paris",
        country="France",
        iata_code="CDG",
        icao_code="LFPG",
        timezone="Europe/Paris",
        latitude=49.0097,
        longitude=2.5479,
        minimum_connection_minutes=70,
    ),
    dict(
        name="Changi Airport",
        city="Singapore",
        country="Singapore",
        iata_code="SIN",
        icao_code="WSSS",
        timezone="Asia/Singapore",
        latitude=1.3644,
        longitude=103.9915,
        minimum_connection_minutes=60,
    ),
    dict(
        name="Frankfurt Airport",
        city="Frankfurt",
        country="Germany",
        iata_code="FRA",
        icao_code="EDDF",
        timezone="Europe/Berlin",
        latitude=50.0379,
        longitude=8.5622,
        minimum_connection_minutes=60,
    ),
    dict(
        name="Los Angeles International Airport",
        city="Los Angeles",
        country="United States",
        iata_code="LAX",
        icao_code="KLAX",
        timezone="America/Los_Angeles",
        latitude=33.9416,
        longitude=-118.4085,
        minimum_connection_minutes=70,
    ),
    dict(
        name="O'Hare International Airport",
        city="Chicago",
        country="United States",
        iata_code="ORD",
        icao_code="KORD",
        timezone="America/Chicago",
        latitude=41.9742,
        longitude=-87.9073,
        minimum_connection_minutes=65,
    ),
    dict(
        name="Hartsfield-Jackson Atlanta International Airport",
        city="Atlanta",
        country="United States",
        iata_code="ATL",
        icao_code="KATL",
        timezone="America/New_York",
        latitude=33.6407,
        longitude=-84.4277,
        minimum_connection_minutes=55,
    ),
    dict(
        name="Amsterdam Airport Schiphol",
        city="Amsterdam",
        country="Netherlands",
        iata_code="AMS",
        icao_code="EHAM",
        timezone="Europe/Amsterdam",
        latitude=52.3105,
        longitude=4.7683,
        minimum_connection_minutes=55,
    ),
    dict(
        name="Sydney Airport",
        city="Sydney",
        country="Australia",
        iata_code="SYD",
        icao_code="YSSY",
        timezone="Australia/Sydney",
        latitude=-33.9399,
        longitude=151.1753,
        minimum_connection_minutes=60,
    ),
)

AIRCRAFT_TYPES = (
    dict(
        manufacturer="Airbus",
        model="A320neo",
        icao_type_code="A20N",
        category="narrow_body",
        typical_cruise_speed_kmh=840,
        maximum_range_km=6300,
        minimum_turnaround_minutes=45,
        passenger_capacity=180,
        crew_count=6,
        wingspan_m=35.80,
        length_m=37.57,
    ),
    dict(
        manufacturer="Airbus",
        model="A321neo",
        icao_type_code="A21N",
        category="narrow_body",
        typical_cruise_speed_kmh=840,
        maximum_range_km=7400,
        minimum_turnaround_minutes=50,
        passenger_capacity=220,
        crew_count=7,
        wingspan_m=35.80,
        length_m=44.51,
    ),
    dict(
        manufacturer="Airbus",
        model="A330-300",
        icao_type_code="A333",
        category="wide_body",
        typical_cruise_speed_kmh=870,
        maximum_range_km=11750,
        minimum_turnaround_minutes=75,
        passenger_capacity=277,
        crew_count=11,
        wingspan_m=60.30,
        length_m=63.66,
    ),
    dict(
        manufacturer="Airbus",
        model="A350-900",
        icao_type_code="A359",
        category="wide_body",
        typical_cruise_speed_kmh=900,
        maximum_range_km=15000,
        minimum_turnaround_minutes=90,
        passenger_capacity=325,
        crew_count=12,
        wingspan_m=64.75,
        length_m=66.80,
    ),
    dict(
        manufacturer="Boeing",
        model="737 MAX 8",
        icao_type_code="B38M",
        category="narrow_body",
        typical_cruise_speed_kmh=839,
        maximum_range_km=6500,
        minimum_turnaround_minutes=45,
        passenger_capacity=178,
        crew_count=6,
        wingspan_m=35.92,
        length_m=39.52,
    ),
    dict(
        manufacturer="Boeing",
        model="777-300ER",
        icao_type_code="B77W",
        category="wide_body",
        typical_cruise_speed_kmh=905,
        maximum_range_km=13600,
        minimum_turnaround_minutes=90,
        passenger_capacity=396,
        crew_count=14,
        wingspan_m=64.80,
        length_m=73.86,
    ),
    dict(
        manufacturer="Boeing",
        model="787-9",
        icao_type_code="B789",
        category="wide_body",
        typical_cruise_speed_kmh=903,
        maximum_range_km=14100,
        minimum_turnaround_minutes=85,
        passenger_capacity=290,
        crew_count=11,
        wingspan_m=60.12,
        length_m=62.81,
    ),
)


def load_reference_data() -> tuple[list[Airport], list[AircraftType], int, int]:
    """Upsert reference records and return objects plus created counts."""
    airports: list[Airport] = []
    airport_created = 0
    for values in AIRPORTS:
        airport, created = Airport.objects.update_or_create(
            iata_code=values["iata_code"], defaults=values
        )
        airports.append(airport)
        airport_created += int(created)

    aircraft_types: list[AircraftType] = []
    type_created = 0
    for values in AIRCRAFT_TYPES:
        aircraft_type, created = AircraftType.objects.update_or_create(
            icao_type_code=values["icao_type_code"], defaults=values
        )
        aircraft_types.append(aircraft_type)
        type_created += int(created)
    return airports, aircraft_types, airport_created, type_created

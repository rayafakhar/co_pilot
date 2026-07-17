"""
Django management command to generate random track data.
"""

import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from tracker.models import Airport, Airplane, Track


class Command(BaseCommand):
    help = 'Generate random airport, airplane, and track data for demonstration'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('Starting data generation...'))

        # Clear existing data for idempotency
        self.stdout.write('Clearing existing data...')
        Track.objects.all().delete()
        Airplane.objects.all().delete()
        Airport.objects.all().delete()

        # Generate Airports
        airport_data = [
            ('New York JFK', 'JFK'),
            ('London Heathrow', 'LHR'),
            ('Tokyo Haneda', 'HND'),
            ('Dubai International', 'DXB'),
            ('Paris CDG', 'CDG'),
            ('Singapore Changi', 'SIN'),
            ('Frankfurt Airport', 'FRA'),
            ('Los Angeles Intl', 'LAX'),
            ('Chicago O\'Hare', 'ORD'),
            ('Atlanta Intl', 'ATL'),
        ]

        airports = []
        for name, code in airport_data:
            airport, created = Airport.objects.get_or_create(
                code=code,
                defaults={'name': name}
            )
            airports.append(airport)

        self.stdout.write(self.style.SUCCESS(f'Created {len(airports)} airports'))

        # Generate Airplanes
        airplane_data = [
            ('Boeing 747-8', 'N747BA'),
            ('Airbus A380', 'N380AE'),
            ('Boeing 787 Dreamliner', 'N787DL'),
            ('Airbus A350', 'N350QR'),
            ('Boeing 777-300ER', 'N777EW'),
            ('Airbus A321neo', 'N321NK'),
            ('Boeing 737 MAX', 'N737SM'),
            ('Airbus A330-300', 'N330TK'),
        ]

        airplanes = []
        for name, tail in airplane_data:
            airplane, created = Airplane.objects.get_or_create(
                tail_number=tail,
                defaults={'name': name}
            )
            airplanes.append(airplane)

        self.stdout.write(self.style.SUCCESS(f'Created {len(airplanes)} airplanes'))

        # Generate Tracks with varied timing
        self.stdout.write('Generating tracks...')
        tracks = []
        now = timezone.now()

        # Define time ranges to ensure all statuses are covered
        # We generate tracks with specific time patterns to guarantee all 4 statuses
        # Each tuple: (status_name, departure_offset, arrival_offset)
        track_configs = []
        
        # 5 tracks that should be "Done" (arrived in the past)
        for _ in range(5):
            dep_offset = random.uniform(-7200, -3600)  # 2-1 hours ago
            arr_offset = dep_offset + random.uniform(1800, 3600)  # arrival 30-60 min after departure
            track_configs.append((dep_offset, arr_offset))
        
        # 5 tracks that should be "In Route" (departed, not yet arrived)
        for _ in range(5):
            dep_offset = random.uniform(-1800, -120)  # departed 30 min to 2 min ago
            arr_offset = dep_offset + random.uniform(3600, 14400)  # arrival 1-4 hours after departure
            track_configs.append((dep_offset, arr_offset))
        
        # 5 tracks that should be "30 minutes till take off" (within 30 min window BEFORE departure)
        # This means: now >= departure - 30min AND now < departure
        # So departure offset should be positive (in the future) but < 30 min
        for _ in range(5):
            dep_offset = random.uniform(120, 1740)  # departure in 2-29 min (so now is within 30 min window)
            arr_offset = dep_offset + random.uniform(1800, 3600)  # arrival 30-60 min after departure
            track_configs.append((dep_offset, arr_offset))
        
        # 5 tracks that should be "Scheduled" (more than 30 min before departure)
        for _ in range(5):
            dep_offset = random.uniform(1800, 10800)  # 30 min to 3 hours from now
            arr_offset = dep_offset + random.uniform(3600, 14400)  # arrival 1-4 hours after departure
            track_configs.append((dep_offset, arr_offset))
        
        for dep_offset, arr_offset in track_configs:
            departure_time = now + timedelta(seconds=dep_offset)
            arrival_time = now + timedelta(seconds=arr_offset)

            # Randomly select airplane and airports
            airplane = random.choice(airplanes)
            departure_airport = random.choice(airports)
            arrival_airport = random.choice([a for a in airports if a.code != departure_airport.code])

            tracks.append(Track(
                airplane=airplane,
                departure_airport=departure_airport,
                arrival_airport=arrival_airport,
                scheduled_departure=departure_time,
                scheduled_arrival=arrival_time,
            ))

        # Use bulk_create for efficiency
        Track.objects.bulk_create(tracks)
        self.stdout.write(self.style.SUCCESS(f'Created {len(tracks)} tracks'))

        # Summary
        self.stdout.write(self.style.SUCCESS('\n--- Data Generation Complete ---'))
        self.stdout.write(f'  Airports: {Airport.objects.count()}')
        self.stdout.write(f'  Airplanes: {Airplane.objects.count()}')
        self.stdout.write(f'  Tracks: {Track.objects.count()}')

        # Verify status distribution
        done_count = sum(1 for t in Track.objects.all() if t.current_status == "Done")
        in_route_count = sum(1 for t in Track.objects.all() if t.current_status == "In Route")
        takeoff_count = sum(1 for t in Track.objects.all() if t.current_status == "30 minutes till take off")
        scheduled_count = sum(1 for t in Track.objects.all() if t.current_status == "Scheduled")

        self.stdout.write(self.style.SUCCESS(f'\nStatus Distribution:'))
        self.stdout.write(f'  Done: {done_count}')
        self.stdout.write(f'  In Route: {in_route_count}')
        self.stdout.write(f'  30 minutes till take off: {takeoff_count}')
        self.stdout.write(f'  Scheduled: {scheduled_count}')
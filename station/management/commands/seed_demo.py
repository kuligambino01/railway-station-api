from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from station.models import Crew, Journey, Route, Station, Train, TrainType


class Command(BaseCommand):
    help = "Create sample railway data, without creating users or passwords."

    @transaction.atomic
    def handle(self, *args, **options):
        warsaw, _ = Station.objects.get_or_create(
            name="Warszawa Centralna",
            defaults={"latitude": 52.229, "longitude": 21.003},
        )
        krakow, _ = Station.objects.get_or_create(
            name="Krakow Glowny", defaults={"latitude": 50.067, "longitude": 19.947}
        )
        route, _ = Route.objects.get_or_create(
            source=warsaw, destination=krakow, defaults={"distance": 293}
        )
        kind, _ = TrainType.objects.get_or_create(name="Intercity")
        train, _ = Train.objects.get_or_create(
            name="IC Wawel",
            defaults={"cargo_num": 3, "places_in_cargo": 20, "train_type": kind},
        )
        crew, _ = Crew.objects.get_or_create(first_name="Anna", last_name="Kowalska")
        departure = (timezone.now() + timedelta(days=1)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        journey, _ = Journey.objects.get_or_create(
            route=route,
            train=train,
            departure_time=departure,
            defaults={"arrival_time": departure + timedelta(hours=3)},
        )
        journey.crew.add(crew)
        self.stdout.write(self.style.SUCCESS(f"Demo journey #{journey.pk} ready."))

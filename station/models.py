from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q


class Station(models.Model):
    name = models.CharField(max_length=255, unique=True)
    latitude = models.FloatField(
        validators=[MinValueValidator(-90), MaxValueValidator(90)]
    )
    longitude = models.FloatField(
        validators=[MinValueValidator(-180), MaxValueValidator(180)]
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Route(models.Model):
    source = models.ForeignKey(
        Station, on_delete=models.PROTECT, related_name="departing_routes"
    )
    destination = models.ForeignKey(
        Station, on_delete=models.PROTECT, related_name="arriving_routes"
    )
    distance = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=~Q(source=F("destination")), name="different_stations"
            ),
            models.CheckConstraint(
                condition=Q(distance__gt=0), name="positive_distance"
            ),
            models.UniqueConstraint(
                fields=["source", "destination"], name="unique_route"
            ),
        ]

    def __str__(self):
        return f"{self.source} - {self.destination}"


class TrainType(models.Model):
    name = models.CharField(max_length=255, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Train(models.Model):
    name = models.CharField(max_length=255, unique=True)
    cargo_num = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(100)]
    )
    places_in_cargo = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(200)]
    )
    train_type = models.ForeignKey(
        TrainType, on_delete=models.PROTECT, related_name="trains"
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(cargo_num__gt=0, places_in_cargo__gt=0),
                name="positive_capacity",
            ),
        ]

    @property
    def capacity(self):
        return self.cargo_num * self.places_in_cargo

    def __str__(self):
        return self.name


class Crew(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)

    class Meta:
        ordering = ["last_name", "first_name", "id"]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class Journey(models.Model):
    route = models.ForeignKey(Route, on_delete=models.PROTECT, related_name="journeys")
    train = models.ForeignKey(Train, on_delete=models.PROTECT, related_name="journeys")
    crew = models.ManyToManyField(Crew, related_name="journeys", blank=True)
    departure_time = models.DateTimeField(db_index=True)
    arrival_time = models.DateTimeField()

    class Meta:
        ordering = ["departure_time", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(arrival_time__gt=F("departure_time")),
                name="arrival_after_departure",
            ),
        ]

    def __str__(self):
        return f"{self.route} ({self.departure_time:%Y-%m-%d %H:%M})"


class Order(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders"
    )

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"Order #{self.pk}"


class Ticket(models.Model):
    cargo = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    seat = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    journey = models.ForeignKey(
        Journey, on_delete=models.PROTECT, related_name="tickets"
    )
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="tickets")

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["journey", "cargo", "seat"], name="unique_journey_seat"
            ),
            models.CheckConstraint(
                condition=Q(cargo__gt=0, seat__gt=0), name="positive_seat"
            ),
        ]

    def __str__(self):
        return f"{self.journey}: carriage {self.cargo}, seat {self.seat}"

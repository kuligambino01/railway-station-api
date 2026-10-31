from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from station.models import (
    Crew,
    Journey,
    Order,
    Route,
    Station,
    Ticket,
    Train,
    TrainType,
)
from station.services import reserve_tickets


class StationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Station
        fields = ["id", "name", "latitude", "longitude"]


class RouteSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source="source.name", read_only=True)
    destination_name = serializers.CharField(source="destination.name", read_only=True)

    class Meta:
        model = Route
        fields = [
            "id",
            "source",
            "destination",
            "source_name",
            "destination_name",
            "distance",
        ]

    def validate(self, attrs):
        if self.instance:
            source = attrs.get("source", self.instance.source)
            destination = attrs.get("destination", self.instance.destination)
        else:
            source = attrs["source"]
            destination = attrs["destination"]
        if source == destination:
            raise serializers.ValidationError("Source and destination must differ.")
        return attrs


class TrainTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrainType
        fields = ["id", "name"]


class TrainSerializer(serializers.ModelSerializer):
    capacity = serializers.IntegerField(read_only=True)
    train_type_name = serializers.CharField(source="train_type.name", read_only=True)

    class Meta:
        model = Train
        fields = [
            "id",
            "name",
            "cargo_num",
            "places_in_cargo",
            "train_type",
            "train_type_name",
            "capacity",
        ]


class CrewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Crew
        fields = ["id", "first_name", "last_name"]


class AwareDateTimeField(serializers.DateTimeField):
    def to_internal_value(self, value):
        try:
            parsed = parse_datetime(value) if isinstance(value, str) else value
        except ValueError:
            parsed = None
        if (
            parsed is not None
            and hasattr(parsed, "tzinfo")
            and timezone.is_naive(parsed)
        ):
            raise serializers.ValidationError(
                "Include a UTC offset or Z in the timestamp."
            )
        return super().to_internal_value(value)


class JourneySerializer(serializers.ModelSerializer):
    departure_time = AwareDateTimeField()
    arrival_time = AwareDateTimeField()
    route_name = serializers.CharField(source="route", read_only=True)
    train_name = serializers.CharField(source="train.name", read_only=True)
    available_seats = serializers.SerializerMethodField()

    class Meta:
        model = Journey
        fields = [
            "id",
            "route",
            "route_name",
            "train",
            "train_name",
            "crew",
            "departure_time",
            "arrival_time",
            "available_seats",
        ]

    def get_available_seats(self, obj) -> int:
        if obj.departure_time <= timezone.now():
            return 0
        reserved = getattr(obj, "reserved_seats", None)
        if reserved is None:
            reserved = obj.tickets.count()
        return obj.train.capacity - reserved

    def validate(self, attrs):
        if self.instance:
            departure = attrs.get("departure_time", self.instance.departure_time)
            arrival = attrs.get("arrival_time", self.instance.arrival_time)
        else:
            departure = attrs["departure_time"]
            arrival = attrs["arrival_time"]
        if departure and arrival and arrival <= departure:
            raise serializers.ValidationError("Arrival must be after departure.")
        return attrs


class TicketSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ticket
        fields = ["id", "journey", "cargo", "seat"]
        validators = []


class OrderSerializer(serializers.ModelSerializer):
    tickets = TicketSerializer(many=True, allow_empty=False, max_length=50)

    class Meta:
        model = Order
        fields = ["id", "created_at", "tickets"]
        read_only_fields = ["id", "created_at"]

    def create(self, validated_data):
        return reserve_tickets(self.context["request"].user, validated_data["tickets"])


class UsernameField(serializers.CharField):
    def to_internal_value(self, value):
        return get_user_model().normalize_username(super().to_internal_value(value))


class UserSerializer(serializers.ModelSerializer):
    username = UsernameField(
        max_length=150,
        validators=[
            UnicodeUsernameValidator(),
            UniqueValidator(queryset=get_user_model().objects.all()),
        ],
    )
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    class Meta:
        model = get_user_model()
        fields = ["id", "username", "email", "first_name", "last_name", "password"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        user = get_user_model()(
            **{key: value for key, value in attrs.items() if key != "password"}
        )
        try:
            validate_password(attrs["password"], user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages}) from exc
        return attrs

    def create(self, validated_data):
        return get_user_model().objects.create_user(**validated_data)


class SeatSerializer(serializers.Serializer):
    cargo = serializers.IntegerField()
    seat = serializers.IntegerField()
    available = serializers.BooleanField()


class ErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()

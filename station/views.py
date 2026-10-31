from django.db import transaction
from django.db.models import Count
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import filters, generics, mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from station.filters import JourneyFilter
from station.models import Crew, Journey, Order, Route, Station, Train, TrainType
from station.permissions import IsAdminOrReadOnly
from station.scheduling import save_journey
from station.serializers import (
    CrewSerializer,
    ErrorSerializer,
    JourneySerializer,
    OrderSerializer,
    RouteSerializer,
    SeatSerializer,
    StationSerializer,
    TrainSerializer,
    TrainTypeSerializer,
    UserSerializer,
)


class RailwayViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminOrReadOnly]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    ordering_fields = ["id"]

    def perform_destroy(self, instance):
        try:
            with transaction.atomic():
                instance = get_object_or_404(
                    type(instance).objects.select_for_update(), pk=instance.pk
                )
                if isinstance(instance, Crew) and instance.journeys.exists():
                    raise ValidationError(
                        "A crew member assigned to a journey cannot be deleted."
                    )
                instance.delete()
        except ProtectedError as exc:
            raise ValidationError(
                "This record is referenced by other railway data."
            ) from exc

    def update(self, request, *args, **kwargs):
        with transaction.atomic():
            instance = get_object_or_404(
                self.get_queryset().select_for_update(of=("self",)),
                pk=self.get_object().pk,
            )
            if isinstance(instance, (Train, Route)) and instance.journeys.exists():
                raise ValidationError(
                    "A train or route used by journeys is immutable. "
                    "Create a new record."
                )
            if isinstance(instance, Journey) and instance.tickets.exists():
                raise ValidationError("A journey with reservations is immutable.")
            serializer = self.get_serializer(
                instance, data=request.data, partial=kwargs.get("partial", False)
            )
            serializer.is_valid(raise_exception=True)
            self.perform_update(serializer)
            return Response(serializer.data)


class StationViewSet(RailwayViewSet):
    queryset = Station.objects.all()
    serializer_class = StationSerializer
    search_fields = ["name"]
    ordering_fields = ["id", "name"]


class RouteViewSet(RailwayViewSet):
    queryset = Route.objects.select_related("source", "destination")
    serializer_class = RouteSerializer
    search_fields = ["source__name", "destination__name"]
    ordering_fields = ["id", "distance"]


class TrainTypeViewSet(RailwayViewSet):
    queryset = TrainType.objects.all()
    serializer_class = TrainTypeSerializer
    search_fields = ["name"]
    ordering_fields = ["id", "name"]


class TrainViewSet(RailwayViewSet):
    queryset = Train.objects.select_related("train_type")
    serializer_class = TrainSerializer
    search_fields = ["name", "train_type__name"]
    ordering_fields = ["id", "name", "cargo_num", "places_in_cargo"]


class CrewViewSet(RailwayViewSet):
    queryset = Crew.objects.all()
    serializer_class = CrewSerializer
    permission_classes = [permissions.IsAdminUser]
    search_fields = ["first_name", "last_name"]
    ordering_fields = ["id", "first_name", "last_name"]


@extend_schema_view(
    create=extend_schema(responses={201: JourneySerializer, 409: ErrorSerializer}),
    update=extend_schema(responses={200: JourneySerializer, 409: ErrorSerializer}),
)
class JourneyViewSet(RailwayViewSet):
    queryset = Journey.objects.select_related(
        "route__source", "route__destination", "train"
    ).prefetch_related("crew")
    serializer_class = JourneySerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_class = JourneyFilter
    search_fields = ["route__source__name", "route__destination__name", "train__name"]
    ordering_fields = ["id", "departure_time", "arrival_time"]
    ordering = ["departure_time", "id"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action in {"list", "retrieve"}:
            queryset = queryset.annotate(reserved_seats=Count("tickets"))
        if self.action == "list" and not self.request.user.is_staff:
            queryset = queryset.filter(departure_time__gt=timezone.now())
        return queryset

    def perform_create(self, serializer):
        save_journey(serializer)

    def perform_update(self, serializer):
        save_journey(serializer)

    @extend_schema(responses=SeatSerializer(many=True))
    @action(
        detail=True, methods=["get"], url_path="available-seats", pagination_class=None
    )
    def seats(self, request, pk=None):
        journey = self.get_object()
        occupied = {(ticket.cargo, ticket.seat) for ticket in journey.tickets.all()}
        bookable = journey.departure_time > timezone.now()
        seats = []
        for cargo in range(1, journey.train.cargo_num + 1):
            for seat in range(1, journey.train.places_in_cargo + 1):
                seats.append(
                    {
                        "cargo": cargo,
                        "seat": seat,
                        "available": bookable and (cargo, seat) not in occupied,
                    }
                )
        return Response(seats)


@extend_schema_view(
    create=extend_schema(responses={201: OrderSerializer, 409: ErrorSerializer}),
)
class OrderViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Order.objects.none()
        return Order.objects.filter(user=self.request.user).prefetch_related("tickets")


class RegisterView(generics.CreateAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = []


class ProfileView(generics.RetrieveAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user

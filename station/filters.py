from django import forms
from django.utils import timezone
from django_filters import rest_framework as filters
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field

from station.models import Journey


class PositiveIntegerFilter(filters.NumberFilter):
    field_class = forms.IntegerField


class JourneyFilter(filters.FilterSet):
    source = PositiveIntegerFilter(field_name="route__source_id", min_value=1)
    destination = PositiveIntegerFilter(field_name="route__destination_id", min_value=1)
    route = PositiveIntegerFilter(field_name="route_id", min_value=1)
    train = PositiveIntegerFilter(field_name="train_id", min_value=1)
    date = filters.DateFilter(field_name="departure_time", lookup_expr="date")
    upcoming = filters.TypedChoiceFilter(
        choices=(("true", "true"), ("false", "false")),
        coerce=lambda value: value == "true",
        method="filter_upcoming",
    )

    @extend_schema_field(OpenApiTypes.STR)
    def filter_upcoming(self, queryset, name, value):
        if value:
            return queryset.filter(departure_time__gt=timezone.now())
        return queryset

    class Meta:
        model = Journey
        fields = ["source", "destination", "route", "train", "date", "upcoming"]

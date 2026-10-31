from django.db import transaction
from rest_framework.exceptions import APIException, ValidationError

from station.models import Crew, Journey, Route, Train


class ScheduleConflict(APIException):
    status_code = 409
    default_detail = "The train or crew is assigned to an overlapping journey."


@transaction.atomic
def save_journey(serializer):
    instance = serializer.instance
    values = serializer.validated_data

    if instance:
        values = {
            "train": instance.train,
            "route": instance.route,
            "departure_time": instance.departure_time,
            "arrival_time": instance.arrival_time,
            **values,
        }
    train = values["train"]
    route = values["route"]
    old_crew = set(instance.crew.values_list("pk", flat=True)) if instance else set()
    crew = values.get("crew")
    crew_ids = {member.pk for member in crew} if crew is not None else old_crew
    train_ids = {train.pk}
    if instance:
        train_ids.add(instance.train_id)
    # Every API schedule writer uses this order. Ordinary overlap reads don't
    # lock other journeys, which would invert the booking lock order.
    trains = list(
        Train.objects.select_for_update().filter(pk__in=train_ids).order_by("pk")
    )
    if len(trains) != len(train_ids):
        raise ValidationError("A train no longer exists.")
    if not Route.objects.select_for_update().filter(pk=route.pk).exists():
        raise ValidationError("The route no longer exists.")
    locked_crew = list(
        Crew.objects.select_for_update()
        .filter(pk__in=old_crew | crew_ids)
        .order_by("pk")
    )
    if {member.pk for member in locked_crew} != old_crew | crew_ids:
        raise ValidationError("A crew member no longer exists.")
    overlaps = Journey.objects.filter(
        departure_time__lt=values["arrival_time"],
        arrival_time__gt=values["departure_time"],
    )
    if instance:
        overlaps = overlaps.exclude(pk=instance.pk)
    if overlaps.filter(train_id=train.pk).exists():
        raise ScheduleConflict("The train is assigned to an overlapping journey.")
    if crew_ids and overlaps.filter(crew__pk__in=crew_ids).exists():
        raise ScheduleConflict("A crew member is assigned to an overlapping journey.")
    return serializer.save()

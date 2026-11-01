from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from station.models import Journey, Order, Ticket


class ReservationConflict(APIException):
    status_code = 409
    default_detail = "A requested seat is no longer available. Refresh and try again."


def is_seat_conflict(error):
    """Match only our unique key, never unrelated FK/check/not-null failures."""
    cause = error.__cause__
    diagnostic = getattr(cause, "diag", None)
    if diagnostic is not None:
        return (
            getattr(cause, "sqlstate", None) == "23505"
            and diagnostic.constraint_name == "unique_journey_seat"
        )
    return getattr(cause, "sqlite_errorcode", None) == 2067 and str(cause) == (
        "UNIQUE constraint failed: station_ticket.journey_id, "
        "station_ticket.cargo, station_ticket.seat"
    )


def reserve_tickets(user, tickets):
    """Lock journeys in stable order; the DB unique key is the final safeguard."""
    try:
        with transaction.atomic():
            ids = sorted({item["journey"].pk for item in tickets})
            journeys = {
                j.pk: j
                for j in Journey.objects.select_related("train")
                .select_for_update(of=("self",))
                .filter(pk__in=ids)
                .order_by("pk")
            }
            if len(journeys) != len(ids):
                raise ValidationError("A journey no longer exists.")
            seen = set()
            requested_seats = Q()
            for item in tickets:
                journey = journeys[item["journey"].pk]
                if journey.departure_time <= timezone.now():
                    raise ValidationError("Cannot book a journey that has departed.")
                if not 1 <= item["cargo"] <= journey.train.cargo_num:
                    raise ValidationError(
                        {"cargo": "Carriage is outside train capacity."}
                    )
                if not 1 <= item["seat"] <= journey.train.places_in_cargo:
                    raise ValidationError(
                        {"seat": "Seat is outside carriage capacity."}
                    )
                key = (journey.pk, item["cargo"], item["seat"])
                if key in seen:
                    raise ValidationError("The same seat occurs twice in this order.")
                seen.add(key)
                requested_seats |= Q(
                    journey=journey, cargo=item["cargo"], seat=item["seat"]
                )
            if Ticket.objects.filter(requested_seats).exists():
                raise ReservationConflict()
            order = Order.objects.create(user=user)
            Ticket.objects.bulk_create(
                [Ticket(order=order, **item) for item in tickets]
            )
            return order
    except IntegrityError as exc:
        if is_seat_conflict(exc):
            raise ReservationConflict() from exc
        raise
    except OperationalError as exc:
        if "locked" in str(exc).lower():
            raise ReservationConflict(
                "Database is busy. Retry your reservation."
            ) from exc
        raise

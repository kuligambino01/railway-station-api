from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError
from django.utils import timezone
from rest_framework.test import APIClient

from config.environment import validate_secret
from station.models import Order, Ticket
from station.services import ReservationConflict, reserve_tickets
from station.tests import create_journey


@pytest.mark.parametrize(
    "secret",
    [
        None,
        "",
        "short",
        "local-only-insecure-development-key-change-me",
        "local-development-change-this-key-before-deployment",
        "django-insecure-" + "x" * 64,
    ],
)
def test_public_or_missing_secret_is_rejected(secret):
    with pytest.raises(ImproperlyConfigured):
        validate_secret(secret)


def test_generated_secret_is_accepted():
    import secrets

    secret = secrets.token_urlsafe(64)
    assert validate_secret(secret) == secret


@pytest.mark.django_db
def test_departed_journey_has_consistent_availability():
    journey = create_journey()
    journey.departure_time = timezone.now() - timedelta(hours=1)
    journey.save()
    client = APIClient()
    assert client.get(f"/api/v1/journeys/{journey.pk}/").data["available_seats"] == 0
    seats = client.get(f"/api/v1/journeys/{journey.pk}/available-seats/").data
    assert not any(seat["available"] for seat in seats)


@pytest.mark.django_db
def test_unrelated_integrity_error_propagates_and_rolls_back():
    journey = create_journey()
    user = get_user_model().objects.create_user("traveler")
    with patch(
        "station.services.Ticket.objects.bulk_create",
        side_effect=IntegrityError("unrelated"),
    ):
        with pytest.raises(IntegrityError, match="unrelated"):
            reserve_tickets(user, [{"journey": journey, "cargo": 1, "seat": 1}])
    assert not Order.objects.exists()
    assert not Ticket.objects.exists()


@pytest.mark.django_db
def test_actual_unique_violation_becomes_conflict_and_rolls_back():
    journey = create_journey()
    user = get_user_model().objects.create_user("traveler")
    items = [{"journey": journey, "cargo": 1, "seat": 1}]
    reserve_tickets(user, items)
    # Bypass only the advisory availability query to exercise the real DB key.
    with patch("station.services.Ticket.objects.filter") as query:
        query.return_value.exists.return_value = False
        with pytest.raises(ReservationConflict):
            reserve_tickets(
                user,
                [
                    {"journey": journey, "cargo": 1, "seat": 2},
                    *items,
                ],
            )
    assert Order.objects.count() == 1
    assert Ticket.objects.count() == 1

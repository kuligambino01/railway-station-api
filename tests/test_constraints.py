import os
import subprocess
import sys
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from station.models import Order, Route, Ticket, Train
from station.services import reserve_tickets
from station.tests import create_journey


@pytest.mark.django_db
@pytest.mark.parametrize(
    "invalid", ["route_stations", "distance", "capacity", "times", "seat"]
)
def test_database_constraints_reject_invalid_direct_writes(invalid):
    journey = create_journey()
    with pytest.raises(IntegrityError), transaction.atomic():
        if invalid == "route_stations":
            Route.objects.create(
                source=journey.route.source,
                destination=journey.route.source,
                distance=1,
            )
        elif invalid == "distance":
            Route.objects.filter(pk=journey.route_id).update(distance=0)
        elif invalid == "capacity":
            Train.objects.filter(pk=journey.train_id).update(cargo_num=0)
        elif invalid == "times":
            journey.arrival_time = journey.departure_time - timedelta(seconds=1)
            journey.save()
        else:
            user = get_user_model().objects.create_user("traveler")
            order = Order.objects.create(user=user)
            Ticket.objects.create(order=order, journey=journey, cargo=1, seat=0)


@pytest.mark.django_db(transaction=True)
def test_real_foreign_key_failure_is_not_a_seat_conflict():
    journey = create_journey()
    user = get_user_model().objects.create_user("removed-after-auth")
    get_user_model().objects.filter(pk=user.pk).delete()
    with pytest.raises(IntegrityError):
        reserve_tickets(user, [{"journey": journey, "cargo": 1, "seat": 1}])
    assert not Order.objects.exists()
    assert not Ticket.objects.exists()


def test_production_defaults_enable_security_controls():
    env = os.environ.copy()
    env.update(ENVIRONMENT="production", DEBUG="False", DB_ENGINE="postgresql")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from config import settings as s; "
            "assert not s.DEBUG; assert s.SECURE_SSL_REDIRECT; "
            "assert s.CSRF_COOKIE_SECURE; assert s.SESSION_COOKIE_SECURE; "
            "assert s.DATABASES['default']['ENGINE'] "
            "== 'django.db.backends.postgresql'",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_missing_secret_prevents_startup():
    env = os.environ.copy()
    env["SECRET_KEY"] = ""
    result = subprocess.run(
        [sys.executable, "-c", "import config.settings"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "SECRET_KEY must be a private random value" in result.stderr
